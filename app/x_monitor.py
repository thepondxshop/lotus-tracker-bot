"""Inbound X -> private admin review. Does not publish, verify stock, or ping members.

All API access is off unless explicitly enabled with nonzero usage budgets.
Polling is independent of the retailer dispatch worker. No OAuth user secrets
are read here: inbound search uses only the app-only X_BEARER_TOKEN.
"""
import asyncio
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import urlsplit

import aiohttp
import discord
from discord import app_commands

from app.x_monitor_config import Settings, VERSION, PAGE_SIZE, POST_MILLS, USER_MILLS, make_query
from app.x_monitor_store import Store, encode


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value, limit):
    value = re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", str(value or ""))
    value = re.sub(r"<[^>]*>", "", value).replace("@", "＠")
    return discord.utils.escape_markdown(" ".join(value.split()))[:limit]


def safe_image(url):
    try:
        p = urlsplit(url or "")
        if p.scheme == "https" and p.hostname == "pbs.twimg.com" and not p.username and not p.password and p.port in (None, 443):
            return url
    except (ValueError, TypeError):
        pass
    return ""


class APIError(Exception):
    def __init__(self, code, retry_at=0):
        # Never put response bodies, URLs, headers or tokens in errors/logs.
        self.code = int(code)
        self.retry_at = retry_at
        super().__init__(f"X HTTP {self.code}")


async def search_page(bearer, params):
    timeout = aiohttp.ClientTimeout(total=20, connect=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            "https://api.x.com/2/tweets/search/recent", params=params,
            headers={"Authorization": "Bearer " + bearer}, allow_redirects=False,
        ) as response:
            if response.status != 200:
                retry_at = time.time() + 60
                for name, relative in (("retry-after", True), ("x-rate-limit-reset", False)):
                    try:
                        value = float(response.headers.get(name, "0"))
                        retry_at = max(retry_at, time.time() + value if relative else value)
                    except (ValueError, OverflowError):
                        pass
                raise APIError(response.status, retry_at)
            raw = await response.read()
            if len(raw) > 2_000_000:
                raise ValueError("X response too large")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("Invalid X response")
            return result


def parse_page(payload, cfg, now):
    """Validate before advancing; an unexpected schema pauses for inspection."""
    if payload.get("errors"):
        raise ValueError("X returned a partial error")
    rows = payload.get("data", [])
    includes = payload.get("includes", {})
    meta = payload.get("meta")
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE or not isinstance(includes, dict) or not isinstance(meta, dict):
        raise ValueError("Invalid X response structure")
    users = includes.get("users", [])
    media = includes.get("media", [])
    if not isinstance(users, list) or not isinstance(media, list):
        raise ValueError("Invalid X expansions")
    if len(users) > min(PAGE_SIZE, len(cfg.handles)):
        raise ValueError("Unexpected number of X users")
    allowed = {h.lower() for h in cfg.handles}
    authors = {}
    for user in users:
        if not isinstance(user, dict):
            raise ValueError("Invalid X author")
        handle = user.get("username", "")
        if isinstance(handle, str) and handle.lower() in allowed:
            authors[str(user.get("id"))] = handle
    images = {m.get("media_key"): safe_image(m.get("url")) for m in media
              if isinstance(m, dict) and m.get("type") == "photo"}
    jobs = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid X post")
        post_id = str(row.get("id", ""))
        handle = authors.get(str(row.get("author_id")))
        if not re.fullmatch(r"[0-9]{1,19}", post_id) or not handle or not isinstance(row.get("text"), str):
            raise ValueError("Missing post identity or allowed author")
        if row.get("withheld") or row.get("possibly_sensitive"):
            continue
        history = row.get("edit_history_tweet_ids", row.get("edit_history_post_ids", [post_id]))
        if not isinstance(history, list) or not history or any(not re.fullmatch(r"[0-9]{1,19}", str(v)) for v in history):
            raise ValueError("Invalid X edit history")
        canonical = str(min(int(v) for v in history))
        attachments = row.get("attachments") or {}
        if not isinstance(attachments, dict):
            raise ValueError("Invalid X attachments")
        keys = attachments.get("media_keys", [])
        if not isinstance(keys, list):
            raise ValueError("Invalid X media keys")
        image = next((images[k] for k in keys if k in images and images[k]), "")
        jobs.append({
            "id": canonical, "post_id": post_id, "handle": handle,
            "text": clean(row["text"], 1200), "image": image,
            "created_at": str(row.get("created_at", ""))[:40],
            "queued_at": now, "channel_id": cfg.channel_id, "state": "READY",
        })
    token = meta.get("next_token", "")
    if not isinstance(token, str) or len(token) > 4096:
        raise ValueError("Invalid X pagination token")
    return jobs, token, len(rows) * POST_MILLS + len(users) * USER_MILLS


def review_card(job):
    url = f"https://x.com/{job['handle']}/status/{job['post_id']}"
    embed = discord.Embed(
        title=f"X lead • @{job['handle']}", url=url,
        description=job["text"] or "Open the original post to review this lead.",
        color=0xB391DD,
    )
    embed.add_field(name="Review status", value="Source post only — availability, release details and game identity need verification.", inline=False)
    if job.get("created_at"):
        embed.add_field(name="Posted on X", value=job["created_at"], inline=True)
    if safe_image(job.get("image")):
        embed.set_image(url=job["image"])
    embed.set_footer(text="Lotus X lead • " + job["id"])
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Open original X post", url=url))
    return embed, view


class XMonitor:
    def __init__(self, bot, cfg=None, store_factory=Store, api=search_page):
        self.bot = bot
        self.error = ""
        try:
            self.cfg = cfg or Settings.from_env()
        except ValueError as error:
            self.cfg = Settings()
            self.error = str(error)
        self.store_factory = store_factory
        self.api = api
        self.status = self.error or self.cfg.blocker() or "WAITING FOR DISCORD"
        self.task = None

    def destination(self):
        if not self.bot.guilds:
            return None, None, "Discord guild unavailable"
        # Same primary-guild convention used by the existing Lotus worker.
        guild = self.bot.guilds[0]
        channel = guild.get_channel(self.cfg.channel_id)
        if not isinstance(channel, discord.TextChannel) or not guild.me:
            return guild, None, "Configured admin text channel unavailable"
        if channel.permissions_for(guild.default_role).view_channel:
            return guild, None, "Admin channel must deny View Channel to @everyone"
        perms = channel.permissions_for(guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links and perms.read_message_history):
            return guild, None, "Bot needs View Channel, Send Messages, Embed Links and Read Message History"
        return guild, channel, ""

    async def run(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Exception text may contain request details; log only the class.
                self.status = "TEMPORARY ERROR — " + type(error).__name__
                print("LOTUS X MONITOR | " + self.status, flush=True)
            await asyncio.sleep(5)

    async def tick(self):
        blocker = self.error or self.cfg.blocker()
        if blocker:
            self.status = blocker
            return
        guild, channel, blocker = self.destination()
        if blocker:
            self.status = "BLOCKED — " + blocker
            return
        store = self.store_factory(guild.id)
        async with store.lease() as acquired:
            if not acquired:
                self.status = "STANDBY — another instance holds the lease"
                return
            state = await store.state()
            if state.get("paused"):
                self.status = "PAUSED — " + state["paused"]
                return
            # One bounded Discord delivery per iteration; API errors cannot
            # starve already-durable leads. No member/event queues are involved.
            await self.deliver_one(store, guild, channel, time.time())
            now = time.time()
            if state.get("fingerprint") != self.cfg.fingerprint:
                state = {"fingerprint": self.cfg.fingerprint, "baseline": int(now),
                         "cursor": int(now), "next_poll": now + self.cfg.interval}
                await store.save(state)
                self.status = "READY — baseline set; no historical posts sent"
                return
            if state.get("next_poll", 0) > now:
                self.status = state.get("status", "READY — waiting for next poll")
                return
            if await store.call("hlen", store.key("jobs")) >= 500:
                self.status = "BLOCKED — review outbox full (500); no more API reads"
                return
            await self.poll(store, state, now)

    async def poll(self, store, state, now):
        # Search only recent data. Don't silently abandon a gap outside X's
        # seven-day window; make the admin explicitly resume from the present.
        start = state.get("window_start", max(state["baseline"], state["cursor"] - 120))
        if start < now - 6 * 86400:
            state["paused"] = "Monitoring gap exceeds six days; use /xmonitor restart_window"
            await store.save(state)
            self.status = "PAUSED — " + state["paused"]
            return
        end = state.get("window_end", int(now) - 15)
        if end <= start:
            return
        keys = await store.reserve(self.cfg, now)
        if keys is None:
            self.status = "BUDGET LIMIT — waiting for budget capacity or request limit reset"
            return
        params = {
            "query": make_query(self.cfg.handles), "max_results": PAGE_SIZE,
            "start_time": utc(start), "end_time": utc(end), "sort_order": "recency",
            "tweet.fields": "author_id,created_at,attachments,possibly_sensitive,withheld",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username", "media.fields": "type,url",
        }
        if state.get("next_token"):
            params["next_token"] = state["next_token"]
        # Persist the exact window before network I/O, including the conservative
        # retry wait. A process crash won't create an immediate paid retry storm.
        state.update(window_start=start, window_end=end, next_poll=now + self.cfg.interval)
        await store.save(state)
        try:
            payload = await self.api(self.cfg.bearer, params)
            jobs, next_token, actual = parse_page(payload, self.cfg, now)
        except APIError as error:
            state["status"] = f"X HTTP {error.code} — inspect developer access/credits or request settings"
            if error.code in (400, 401, 402, 403, 404, 422) or 300 <= error.code < 400:
                state["paused"] = state["status"]
            else:
                failures = min(6, state.get("failures", 0) + 1)
                state["failures"] = failures
                state["next_poll"] = max(now + min(3600, 60 * 2**failures), error.retry_at)
            await store.save(state)
            self.status = state["status"]
            return
        except (aiohttp.ClientError, TimeoutError, OSError):
            state["status"] = "X network error — cursor retained; retry deferred"
            state["next_poll"] = now + max(120, self.cfg.interval)
            await store.save(state)
            self.status = state["status"]
            return
        except (ValueError, TypeError, KeyError):
            state["paused"] = "Unexpected X response; cursor retained. Check logs/code before /xmonitor resume"
            await store.save(state)
            self.status = "PAUSED — " + state["paused"]
            return
        # Settle once. If anything subsequently fails, retrying is a separate
        # paid request with a new reservation. Successful cursor commit is atomic.
        await store.settle(keys, self.cfg.request_reserve, actual)
        state.update(last_success=now, failures=0, status="RUNNING — last X request successful")
        state["observed_handles"] = sorted(set(state.get("observed_handles", [])) | {j["handle"] for j in jobs})
        if next_token:
            if next_token == state.get("next_token"):
                state["paused"] = "Repeated X pagination token; cursor retained"
            else:
                state["next_token"] = next_token
                state["next_poll"] = now + 5
        else:
            state["cursor"] = end
            for key in ("window_start", "window_end", "next_token"):
                state.pop(key, None)
            state["next_poll"] = now + self.cfg.interval
        await store.enqueue_page(state, jobs, now)
        self.status = state["status"]

    async def deliver_one(self, store, guild, channel, now):
        due = await store.call("zrangebyscore", store.key("due"), "-inf", now, start=0, num=1)
        if not due:
            return
        job_id = due[0]
        raw = await store.call("hget", store.key("jobs"), job_id)
        if not raw:
            await store.write([["ZREM", store.key("due"), job_id]])
            return
        job = json.loads(raw)
        if job["channel_id"] != channel.id or job["handle"].lower() not in {h.lower() for h in self.cfg.handles}:
            await store.finish(job_id, "destination_or_source_changed")
            return
        if now - job["queued_at"] > 86400:
            await store.finish(job_id, "expired_" + job["state"].lower())
            return
        if job["state"] in ("SENDING", "UNCERTAIN"):
            # An interrupted send may already exist. Never blindly resend it.
            marker = "Lotus X lead • " + job_id
            after = datetime.fromtimestamp(job.get("attempt_at", job["queued_at"]) - 5, timezone.utc)
            try:
                async with asyncio.timeout(15):
                    async for message in channel.history(limit=100, after=after, oldest_first=True):
                        if message.author.id == self.bot.user.id and any(e.footer.text == marker for e in message.embeds):
                            await store.finish(job_id, "reconciled")
                            return
            except (discord.HTTPException, TimeoutError):
                pass
            job["state"] = "UNCERTAIN"
            await store.set_job(job, now + 300)
            return
        job.update(state="SENDING", attempt_at=now)
        await store.set_job(job, now + 60)
        embed, view = review_card(job)
        role = guild.get_role(self.cfg.role_id) if self.cfg.role_id else None
        if role is not None and role.is_default():
            role = None
        summary = "📰 X lead • @" + job["handle"] + " — " + job["text"][:160]
        content = (role.mention + "\n" if role else "") + summary
        try:
            await asyncio.wait_for(channel.send(
                content=content, embed=embed, view=view,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=[role] if role else [], replied_user=False),
            ), 20)
        except discord.Forbidden:
            job["state"] = "READY"
            await store.set_job(job, now + 300)
            return
        except discord.HTTPException as error:
            job["state"] = "READY" if error.status in (400, 404, 429) else "UNCERTAIN"
            await store.set_job(job, now + 300)
            return
        except (TimeoutError, OSError, aiohttp.ClientError):
            job["state"] = "UNCERTAIN"
            await store.set_job(job, now + 300)
            return
        # If this write fails, SENDING remains durable for history reconciliation.
        await store.finish(job_id, "sent")


def runtime(bot):
    monitor = getattr(bot, "lotus_x_monitor", None)
    if monitor is None:
        monitor = XMonitor(bot)
        bot.lotus_x_monitor = monitor
    return monitor


def start_x_monitor(bot):
    monitor = runtime(bot)
    if monitor.task is None or monitor.task.done():
        monitor.task = asyncio.create_task(monitor.run(), name="lotus-x-monitor")
    return monitor.task


async def stop_x_monitor(bot):
    monitor = getattr(bot, "lotus_x_monitor", None)
    if monitor and monitor.task:
        monitor.task.cancel()
        try:
            await monitor.task
        except asyncio.CancelledError:
            pass


def register_x_monitor_commands(bot):
    """Register before existing main.py tree.sync; all responses are private."""
    group = app_commands.Group(name="xmonitor", description="Admin X monitoring status and recovery",
                               default_permissions=discord.Permissions(administrator=True), guild_only=True)

    async def admin(interaction):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Administrator permission is required.", ephemeral=True)
            return False
        if not bot.guilds or interaction.guild.id != bot.guilds[0].id:
            await interaction.response.send_message("Use this command in Lotus's primary server.", ephemeral=True)
            return False
        await interaction.response.defer(ephemeral=True)
        return True

    @group.command(name="status", description="Show monitoring, usage estimates and delivery state; no X API call")
    async def status(interaction: discord.Interaction):
        if not await admin(interaction):
            return
        monitor = runtime(bot)
        cfg = monitor.cfg
        store = monitor.store_factory(interaction.guild.id)
        embed = discord.Embed(title="Lotus X Monitor " + VERSION, color=0xB391DD)
        blocker = monitor.error or cfg.blocker() or monitor.destination()[2]
        embed.add_field(name="State", value=blocker or monitor.status, inline=False)
        embed.add_field(name="Worker", value="RUNNING" if monitor.task and not monitor.task.done() else "STOPPED", inline=True)
        embed.add_field(name="Sources / interval", value=f"{len(cfg.handles)} handles / {cfg.interval}s", inline=True)
        embed.add_field(name="Configured sources", value="\n".join("@" + h for h in cfg.handles), inline=False)
        embed.add_field(name="Delivery", value=f"<#{cfg.channel_id}> • admin review only" if cfg.channel_id else "Channel not configured", inline=False)
        try:
            state = await store.state()
            amounts = await store.call("mget", store.budget_keys(time.time()))
            day, month, calls = [int(v or 0) for v in amounts]
            embed.add_field(name="Local usage estimate (UTC)", value=(
                f"Today: ${day / 1000:.3f} / ${cfg.daily_mills / 1000:.2f}\n"
                f"Calendar month: ${month / 1000:.3f} / ${cfg.monthly_mills / 1000:.2f}\n"
                f"Requests today: {calls} / {cfg.daily_requests}"), inline=False)
            pending = await store.call("hlen", store.key("jobs"))
            totals = await store.call("hgetall", store.key("totals"))
            embed.add_field(name="Review deliveries", value=f"Pending/uncertain: {pending}\nTotals: {totals or 'None yet'}"[:1024], inline=False)
            embed.add_field(name="Last successful X read", value=utc(state["last_success"]) if state.get("last_success") else "None — account/API access not yet verified", inline=False)
            if state.get("paused"):
                embed.add_field(name="Persistent pause", value=state["paused"][:1024], inline=False)
            observed = state.get("observed_handles", [])
            embed.add_field(name="Accounts observed through API", value=", ".join("@" + h for h in observed) or "None yet; configured handles are not proof of working access.", inline=False)
        except Exception:
            embed.add_field(name="Redis", value="Unavailable — no X requests can proceed", inline=False)
        embed.set_footer(text="Estimates are not X invoices. Set a spending limit in the X console. X publishing is not included in this module.")
        await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="pause", description="Pause X reads and admin lead delivery immediately")
    async def pause(interaction: discord.Interaction):
        if not await admin(interaction):
            return
        store = runtime(bot).store_factory(interaction.guild.id)
        async with store.lease() as acquired:
            if not acquired:
                await interaction.followup.send("A request is finishing. Try again in a few seconds.", ephemeral=True)
                return
            state = await store.state()
            state["paused"] = "Paused by admin"
            await store.save(state)
        await interaction.followup.send("X monitoring paused. Existing store alerts continue.", ephemeral=True)

    @group.command(name="resume", description="Clear a pause; still requires enabled flag, channel, credentials and budgets")
    async def resume(interaction: discord.Interaction):
        if not await admin(interaction):
            return
        monitor = runtime(bot)
        blocker = monitor.error or monitor.cfg.blocker() or monitor.destination()[2]
        if blocker:
            await interaction.followup.send(blocker, ephemeral=True)
            return
        store = monitor.store_factory(interaction.guild.id)
        async with store.lease() as acquired:
            if not acquired:
                await interaction.followup.send("Monitor busy; try again shortly.", ephemeral=True)
                return
            state = await store.state()
            state.pop("paused", None)
            # Respect existing rate-limit backoff when resuming.
            await store.save(state)
        await interaction.followup.send("Pause cleared. Monitoring resumes within its configured limits.", ephemeral=True)

    @group.command(name="restart_window", description="Discard a stale search backlog and monitor only posts created from now")
    async def restart_window(interaction: discord.Interaction):
        if not await admin(interaction):
            return
        monitor = runtime(bot)
        store = monitor.store_factory(interaction.guild.id)
        async with store.lease() as acquired:
            if not acquired:
                await interaction.followup.send("Monitor busy; try again shortly.", ephemeral=True)
                return
            state = await store.state()
            for key in ("window_start", "window_end", "next_token", "paused"):
                state.pop(key, None)
            now = int(time.time())
            state.update(fingerprint=monitor.cfg.fingerprint, baseline=now, cursor=now,
                         next_poll=now + monitor.cfg.interval, status="READY — new search window")
            await store.save(state)
        await interaction.followup.send("Search window restarted from now. Previously queued reviews remain; spending counters were preserved.", ephemeral=True)

    @group.command(name="pending", description="List up to 15 pending/uncertain reviews; no X API call")
    async def pending(interaction: discord.Interaction):
        if not await admin(interaction):
            return
        monitor = runtime(bot)
        store = monitor.store_factory(interaction.guild.id)
        ids = await store.call("zrange", store.key("due"), 0, 14)
        lines = []
        for job_id in ids:
            raw = await store.call("hget", store.key("jobs"), job_id)
            if raw:
                job = json.loads(raw)
                lines.append(f"`{job_id}` • {job['state']} • @{job['handle']}")
        await interaction.followup.send("\n".join(lines) or "No pending reviews.", ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="resolve", description="After checking Discord history, resolve an uncertain lead delivery")
    @app_commands.choices(decision=[
        app_commands.Choice(name="Already delivered — do not send again", value="delivered"),
        app_commands.Choice(name="Not delivered — retry (check history first)", value="retry"),
    ])
    async def resolve(interaction: discord.Interaction, lead_id: str, decision: app_commands.Choice[str]):
        if not await admin(interaction):
            return
        if not re.fullmatch(r"[0-9]{1,19}", lead_id):
            await interaction.followup.send("Use the numeric lead ID from /xmonitor pending.", ephemeral=True)
            return
        store = runtime(bot).store_factory(interaction.guild.id)
        async with store.lease() as acquired:
            if not acquired:
                await interaction.followup.send("Monitor busy; try again shortly.", ephemeral=True)
                return
            raw = await store.call("hget", store.key("jobs"), lead_id)
            job = json.loads(raw) if raw else None
            if not job or job["state"] not in ("SENDING", "UNCERTAIN"):
                await interaction.followup.send("That lead has no uncertain delivery to resolve.", ephemeral=True)
                return
            if decision.value == "delivered":
                await store.finish(lead_id, "admin_confirmed")
            else:
                job["state"] = "READY"
                await store.set_job(job, time.time())
        await interaction.followup.send("Delivery marked as resolved." if decision.value == "delivered" else
                                        "Retry queued within the existing monitoring gates.", ephemeral=True)

    bot.tree.add_command(group)
