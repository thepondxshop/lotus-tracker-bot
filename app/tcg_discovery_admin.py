"""Admin review notices for games absent from GAME_DATA (alert update A2).

All Redis/Discord I/O happens in a separate background task. A Redis outbox
retains accepted notices across restarts, with a permanent sent-name record.
Names extracted from retailer titles are candidates, not publisher verification.
This module does not create roles, assign members or edit the game dropdown.
"""
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import html
import json
import os
import re
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit
import uuid

import discord

from app.config import GAME_DATA
from app.redis_client import get_redis
from app.tcg_identity import DISCOVERY_GAMES, NEW_TCG, JURASSIC_TCG

VERSION = "1.0.6-A2"
IO_TIMEOUT = 5
SEND_TIMEOUT = 20
RETRY_SECONDS = 60
POLL_SECONDS = 30

# No expiration on sent records: another product/store/restock is not a new game.
_ENQUEUE = """
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 1 then return 0 end
if redis.call('HEXISTS', KEYS[2], ARGV[1]) == 1 then return 2 end
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('ZADD', KEYS[3], ARGV[3], ARGV[1])
return 1
"""
_ACK = """
if redis.call('GET', KEYS[4]) ~= ARGV[3] then return 0 end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
redis.call('DEL', KEYS[4])
return 1
"""
_UNLOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def clean_text(value, limit=250):
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"<[^>]*>", " ", value).replace("@", "＠")
    value = re.sub(r"[*`|~]", "", value)
    value = "".join(c for c in value if not unicodedata.category(c).startswith("C") or c.isspace())
    value = " ".join(value.split())
    return value[:limit]


def _name_key(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"\b(?:trading card game|collectible card game|card game|tcg|ccg)\b", " ", value)
    return re.sub(r"[\W_]+", " ", value).strip()


def _registered(name):
    key = _name_key(name)
    return bool(key) and any(_name_key(game) == key for game, _, _ in GAME_DATA)


def _http_url(value):
    try:
        value = str(value or "").strip()
        if len(value) > 1800 or any(c.isspace() for c in value):
            return ""
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            return ""
        return value
    except ValueError:
        return ""


def _suggested_name(event):
    game = event.get("game")
    if game and game != NEW_TCG:
        return clean_text(game, 95), "Catalog game name — admin review required"
    title = clean_text(event.get("product_name"), 500)
    marker = re.search(r"\b(?:trading card game|collectible card game|card game|tcg|ccg)\b", title, re.I)
    if not marker:
        return "", "Game name unresolved — inspect the product page"
    prefix = title[:marker.start()]
    # Remove common preorder/language labels only at the start, not words
    # inside a franchise name. Avoid using set codes as suggested game names.
    prefix = re.sub(r"^(?:(?:[\[({\s]*)(?:pre[ -]?order|new|english|japanese|korean|sealed)"
                    r"\b[\])}:\s-]*)+", "", prefix, flags=re.I).strip(" [](){}:-–—")
    generic = re.fullmatch(r"(?:(?:booster|box|pack|starter|deck|set|case|display|the|a|\d+)\s*)+", prefix, re.I)
    if not prefix or generic or not any(c.isalpha() for c in prefix):
        return "", "Game name unresolved — inspect the product page"
    if len(prefix) > 75 or re.search(r"\b(?:op|eb|prb|st|ex)[ -]?\d+\b", prefix, re.I):
        return "", "Game name unresolved — inspect the product page"
    return prefix + " TCG", "Suggested name from the listing — not yet verified"


@dataclass(frozen=True)
class Candidate:
    key: str
    name: str
    confidence: str
    product: str
    url: str
    store: str
    image: str
    source: str
    first_seen: float


def candidate_from_event(event):
    game = event.get("game")
    if not game or event.get("source_type") == "simulation" or str(event.get("event_type", "")).startswith("QUEUE_"):
        return None
    # Existing supported games must not generate new-game admin notices just
    # because a Railway role ID has not been configured yet.
    if _registered(game):
        return None
    if game not in DISCOVERY_GAMES:
        return None
    name, confidence = _suggested_name(event)
    if name and _registered(name):
        return None
    url = _http_url(event.get("product_url"))
    product = clean_text(event.get("product_name"), 300) or "Unknown product"
    if name:
        identity = "name:" + _name_key(name)
    else:
        # Unresolved titles are grouped by product, not all collapsed into
        # one 'Unknown TCG'. Query tracking parameters do not split a page.
        parsed = urlsplit(url)
        identity = "unresolved:" + (urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")) if url else product.casefold())
    return Candidate(
        key=hashlib.sha256(identity.encode()).hexdigest(),
        name=name or "Unidentified TCG", confidence=confidence,
        product=product, url=url, store=clean_text(event.get("store_name"), 100) or "Unknown store",
        image=_http_url(event.get("image_url")), source=clean_text(event.get("source_type"), 60),
        first_seen=time.time(),
    )


def build_admin_notice(candidate, guild):
    safe_name = discord.utils.escape_markdown(candidate.name)
    embed = discord.Embed(
        title="🆕 TCG needs admin review",
        description=f"**{safe_name}**\n{candidate.confidence}",
        color=discord.Color.purple(),
        url=candidate.url or None,
    )
    embed.add_field(name="Example product", value=discord.utils.escape_markdown(candidate.product), inline=False)
    embed.add_field(name="Store", value=discord.utils.escape_markdown(candidate.store), inline=True)
    existing = next((role for role in guild.roles if _name_key(role.name) == _name_key(candidate.name)
                     and not role.is_default()), None) if candidate.name != "Unidentified TCG" else None
    role_step = (f"A matching role already exists: {discord.utils.escape_markdown(existing.name)}. Link that role to the game."
                 if existing else "Create a dedicated Discord role using the confirmed game name.")
    embed.add_field(
        name="Admin steps",
        value=("1. Review the product page and confirm the game name.\n"
               f"2. {role_step}\n"
               "3. Register the game, classifier name/aliases and role ID in Lotus.\n"
               "4. Refresh the roles dropdown with `/setupgames` after that update."),
        inline=False,
    )
    embed.set_footer(text="Lotus Tracker Bot • New-game review • A2")
    if candidate.image:
        embed.set_thumbnail(url=candidate.image)
    return embed


class DiscoveryNotifier:
    def __init__(self, bot, channel_id, admin_role_id=None):
        self.bot = bot
        self.channel_id = channel_id
        self.admin_role_id = admin_role_id
        self.pending = {}
        self.seen = set()
        self.delivered = {}  # Prevent repeat sends after an ACK retry in this process.
        self.wake = asyncio.Event()
        self.task = None

    def submit(self, event):
        candidate = candidate_from_event(event)
        if candidate and candidate.key not in self.seen:
            self.pending.setdefault(candidate.key, candidate)
            self.wake.set()

    async def _io(self, awaitable):
        return await asyncio.wait_for(awaitable, IO_TIMEOUT)

    def _base(self, guild):
        return f"lotus:tcg_discovery:v1:{guild.id}:{self.channel_id}"

    async def _flush(self, redis, base):
        for key, candidate in list(self.pending.items())[:50]:
            await self._io(redis.eval(_ENQUEUE, 3, base+":sent", base+":jobs", base+":due",
                                     key, json.dumps(asdict(candidate)), time.time()))
            self.pending.pop(key, None)
            self.seen.add(key)

    async def _channel(self, guild):
        channel = guild.get_channel(self.channel_id)
        if channel is None:
            # Cached guild channels are normally sufficient. A missing or
            # wrong-guild channel stays queued for correction, with no fallback.
            raise RuntimeError("CHANNEL_TCG_DISCOVERIES is not a text channel in the primary server")
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError("CHANNEL_TCG_DISCOVERIES must point to a server text channel")
        if channel.permissions_for(guild.default_role).view_channel:
            raise RuntimeError("Make CHANNEL_TCG_DISCOVERIES private: disable View Channel for @everyone")
        permissions = channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            raise RuntimeError("Lotus needs View Channel, Send Messages and Embed Links in CHANNEL_TCG_DISCOVERIES")
        return channel

    async def _deliver(self, redis, base, guild, key):
        token = uuid.uuid4().hex
        lock = base+":lock:"+key
        if not await self._io(redis.set(lock, token, nx=True, ex=90)):
            return False
        try:
            payload = await self._io(redis.hget(base+":jobs", key))
            if not payload:
                await self._io(redis.zrem(base+":due", key))
                return True
            candidate = Candidate(**json.loads(payload))
            if _registered(candidate.name):
                message_id = "already_registered"
            elif key in self.delivered:
                message_id = self.delivered[key]
            else:
                channel = await self._channel(guild)
                role = guild.get_role(self.admin_role_id) if self.admin_role_id else None
                if role is not None and role.is_default():
                    role = None
                if self.admin_role_id and role is None:
                    print("TCG ADMIN ROLE NOT FOUND | Notice will post without a role ping")
                content = f"🆕 TCG review: {discord.utils.escape_markdown(candidate.name)}"
                if role:
                    content += "\n" + role.mention
                message = await asyncio.wait_for(channel.send(
                    content=content, embed=build_admin_notice(candidate, guild),
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, users=False, roles=[role] if role else [], replied_user=False,
                    ),
                ), SEND_TIMEOUT)
                message_id = str(message.id)
                self.delivered[key] = message_id
                print(f"TCG ADMIN NOTICE SENT | Game={candidate.name} | Channel={self.channel_id} | Message={message_id}")
            acknowledged = await self._io(redis.eval(_ACK, 4, base+":sent", base+":jobs", base+":due", lock,
                                                    key, message_id, token))
            if not acknowledged:
                raise RuntimeError("Admin notice sent but outbox acknowledgement must retry")
            self.delivered.pop(key, None)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"TCG ADMIN NOTICE RETRY | Candidate={key[:12]} | {type(error).__name__}: {error}")
            await self._io(redis.zadd(base+":due", {key:time.time()+RETRY_SECONDS}))
            return False
        finally:
            try:
                await self._io(redis.eval(_UNLOCK, 1, lock, token))
            except Exception:
                pass  # The short lock expires even if Redis is unavailable.

    async def tick(self):
        redis = get_redis()
        if redis is None or not self.bot.guilds:
            return
        guild = self.bot.guilds[0]  # Matches the member-alert worker's guild selection.
        base = self._base(guild)
        await self._flush(redis, base)
        keys = await self._io(redis.zrangebyscore(base+":due", "-inf", time.time(), start=0, num=10))
        progressed = False
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode()
            progressed = await self._deliver(redis, base, guild, key) or progressed
        if self.pending or (len(keys) == 10 and progressed):
            self.wake.set()

    async def run(self):
        print(f"TCG ADMIN NOTIFIER {VERSION} started | Channel={self.channel_id}")
        while not self.bot.is_closed():
            self.wake.clear()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(f"TCG ADMIN NOTIFIER ERROR | {type(error).__name__}: {error}")
            try:
                await asyncio.wait_for(self.wake.wait(), POLL_SECONDS)
            except asyncio.TimeoutError:
                pass


def start_tcg_discovery_notifier(bot):
    existing = getattr(bot, "_lotus_tcg_discovery_notifier", None)
    if existing is not None and existing.task and not existing.task.done():
        return existing
    raw = os.getenv("CHANNEL_TCG_DISCOVERIES", "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        print("TCG ADMIN NOTIFIER DISABLED | Set CHANNEL_TCG_DISCOVERIES to the private admin text channel ID")
        return None
    role_raw = os.getenv("ROLE_TCG_DISCOVERY_ADMIN", "").strip()
    notifier = existing or DiscoveryNotifier(bot, int(raw), int(role_raw) if role_raw.isdigit() else None)
    notifier.task = asyncio.create_task(notifier.run(), name="lotus-tcg-admin-notices")
    bot._lotus_tcg_discovery_notifier = notifier
    return notifier


def queue_tcg_discovery_review(bot, event):
    """Synchronous enqueue only: never await admin I/O on the alert path."""
    notifier = getattr(bot, "_lotus_tcg_discovery_notifier", None)
    if notifier is not None:
        try:
            notifier.submit(event)
        except Exception as error:
            print(f"TCG ADMIN CANDIDATE ERROR | {type(error).__name__}: {error}")
