"""Render live scheduler state separately from process-lifetime counters."""
import discord
import asyncio
from datetime import datetime, timezone

PAGE_SIZE = 6


def page_info(data, page=1):
    rows = sorted(data.get('store_runtime', []), key=lambda r: r['store_id'])
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    return rows, min(max(1, page), pages), pages


def observation_age(row):
    try:
        at = datetime.fromisoformat(row['last_observation_at'])
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc)-at).total_seconds())
    except (KeyError, ValueError, TypeError):
        return None


def safe(value, limit=220):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value)))[:limit]


def build_shopify_status(data, worker_online, page=1):
    heartbeat = data.get('scheduler_heartbeat_age_seconds')
    loop = 'Stopped' if not data.get('running') else ('Responsive' if heartbeat is not None and heartbeat < 40 else 'Heartbeat delayed / unavailable')
    out = discord.Embed(title='🛍️ Lotus Shopify Monitor', colour=0x667ACD,
        description=f"Worker: {'Online' if worker_online else 'Offline'}\nScheduler: {loop}\n"
        f"Scan in progress: {'Yes' if data.get('scan_in_progress') else 'No — see each store below'}\n"
        f"Active stores: {data.get('active_shopify_stores', 0)}\nHeartbeat age: {heartbeat if heartbeat is not None else 'Unknown'}s")
    rows, page, pages = page_info(data, page)
    stale = sum(observation_age(row) is None or observation_age(row) > 300 for row in rows)
    if stale:
        out.description += f'\n⚠️ {stale}/{len(rows)} stores lack a TCG observation within 5 minutes.'
        out.colour = 0xE6A23C
    for row in rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE]:
        phase = row.get('phase', 'UNKNOWN')
        if (row.get('overdue_seconds') or 0) > 30:
            phase += ' • OVERDUE'
        elif phase in ('SCANNING', 'LOAD_SETTINGS') and row.get('phase_age_seconds', 0) > 180:
            phase += ' • LONG RUNNING'
        value = f"{phase} • Last outcome: {row.get('outcome', 'Not yet')}\n"
        age = observation_age(row)
        if age is None or age > 300:
            value += '⚠️ TCG observation: ' + ('Not recorded' if age is None else f'{int(age//60)} minutes old') + '\n'
        if row.get('wait_seconds') is not None:
            value += f"Next attempt in: {row['wait_seconds']}s • {row.get('next_attempt_at')}\n"
        value += f"Cooldown remaining: {row['cooldown_seconds']}s\n"
        value += f"Request spacing: {row['request_interval_seconds']:.2f}s • Recovery: {'Yes' if row['recovery_mode'] else 'No'}\n"
        value += f"Last attempt finished: {row.get('last_finished_at') or 'Not yet'}\n"
        value += f"Last scan without rate limiting: {row.get('last_success_at') or 'Not yet'}\n"
        value += f"Last TCG observation: {row.get('last_observation_at') or 'Not yet'}\n"
        if row.get('last_error'):
            value += 'Error: ' + safe(row['last_error'], 90) + '\n'
        evidence = row.get('last_rate_limit') or {}
        if evidence:
            value += 'Last HTTP 429: ' + safe(evidence.get('purpose', 'Unknown'), 80) + '\n'
            value += '429 time: ' + safe(evidence.get('at', 'Unknown'), 40)
        out.add_field(name=safe(f"#{row['store_id']} • {row.get('store', 'Loading store')}", 80), value=value[:680], inline=False)
    if not rows:
        out.add_field(name='Store workers', value='No per-store state recorded yet. Check scheduler heartbeat and Railway logs.', inline=False)
    out.add_field(name='Since this process started', value=
        f"HTTP 429 responses: {data.get('rate_limit_responses', 0)}\n"
        f"Rate-limited scan attempts: {data.get('rate_limited_scans', 0)}\n"
        f"Other failed scans: {data.get('stores_failed', 0)}\n"
        f"Accumulated requested backoff: {data.get('rate_limit_backoff_seconds', 0):.1f}s\n"
        'Backoff is a total across attempts, not the current wait.', inline=False)
    out.add_field(name='Latest stored scan results', value=
        f"Products seen: {data.get('products_seen', 0)} • Events: {data.get('events_created', 0)} • Flickers: {data.get('flickers_detected', 0)}\n"
        'Results may be from different times; compare each store’s observation time above.', inline=False)
    out.set_footer(text=f"Page {page}/{pages} • Shopify {data.get('component_version', 'unknown')} • Status UI P1\nAll times UTC • Waiting is not a failure. Buttons expire after 10 minutes of inactivity or a restart.")
    return out


class ShopifyStatusView(discord.ui.View):
    """Read fresh in-memory health on clicks; never trigger retailer scans."""
    def __init__(self, owner_id, guild_id, loader, data, page=1):
        super().__init__(timeout=600)
        self.owner_id, self.guild_id, self.loader = owner_id, guild_id, loader
        self.lock = asyncio.Lock()
        self.message = None
        self.set_page(data, page)

    def set_page(self, data, page):
        _, self.page, self.pages = page_info(data, page)
        self.previous.disabled = self.page == 1
        self.next_page.disabled = self.page == self.pages
        self.page_label.label = f'Page {self.page}/{self.pages}'

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Open your own view with /shopifystatus.', ephemeral=True)
            return False
        return True

    async def move(self, interaction, step):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self.lock:
            if self.is_finished():
                await interaction.followup.send('These buttons expired. Run /shopifystatus again.', ephemeral=True)
                return
            old_page, old_pages = self.page, self.pages
            try:
                data, online = self.loader()
                self.set_page(data, self.page + step)
                await interaction.edit_original_response(
                    embed=build_shopify_status(data, online, self.page), view=self,
                    allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                self.page, self.pages = old_page, old_pages
                self.previous.disabled = self.page == 1
                self.next_page.disabled = self.page == self.pages
                self.page_label.label = f'Page {self.page}/{self.pages}'
                await interaction.followup.send('Could not refresh status. Run /shopifystatus again.', ephemeral=True)

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, -1)

    @discord.ui.button(label='Page', style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label='Next', style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 1)

    @discord.ui.button(label='Refresh', style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 0)

    async def on_timeout(self):
        async with self.lock:
            self.stop()
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass
