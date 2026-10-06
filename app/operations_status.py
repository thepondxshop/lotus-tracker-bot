"""OPS1: bounded Discord summaries; no retailer requests or raw error forwarding."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import os
import time

import discord

VERSION = 'OPS1'
CHANNELS = {
    'status': 'CHANNEL_BOT_STATUS',
    'health': 'CHANNEL_MONITOR_HEALTH',
    'errors': 'CHANNEL_MONITOR_ERRORS',
    'development': 'CHANNEL_BOT_DEVELOPMENT',
}
_errors = Counter()
_worker_heartbeat = None
_task = None


def worker_heartbeat():
    global _worker_heartbeat
    _worker_heartbeat = time.monotonic()


def record_worker_error(kind):
    # Only fixed categories leave the process; never exception text or event data.
    if kind not in {'DISPATCH_TIMEOUT', 'DISPATCH_ERROR', 'WORKER_ERROR'}:
        kind = 'WORKER_ERROR'
    _errors[kind] += 1


def channel_id(kind):
    value = os.getenv(CHANNELS[kind], '').strip()
    return int(value) if value.isascii() and value.isdigit() and int(value) > 0 else None


def snapshot(data, now=None):
    now = now or datetime.now(timezone.utc)
    stale = []
    rows = data.get('store_runtime') or []
    for row in rows:
        try:
            at = datetime.fromisoformat(row.get('last_observation_at') or '')
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            age = max(0, (now-at).total_seconds())
        except (ValueError, TypeError):
            age = None
        if age is None or age > 300:
            stale.append((row, age))
    stale.sort(key=lambda pair: float('inf') if pair[1] is None else pair[1], reverse=True)
    hb = data.get('scheduler_heartbeat_age_seconds')
    scheduler = 'Stopped' if not data.get('running') else (
        'Responsive' if hb is not None and hb < 40 else 'Heartbeat delayed / unknown')
    return {'scheduler': scheduler, 'rows': rows, 'stale': stale,
            'fresh': len(rows)-len(stale),
            'partial': sum(r.get('outcome') == 'PARTIAL_COVERAGE' for r in rows),
            'cooldown': sum((r.get('cooldown_seconds') or 0) > 0 for r in rows)}


def safe(value):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value)))[:90]


def health_text(data):
    s = snapshot(data)
    text = (f"**Lotus monitor health — Shopify**\nScheduler: {s['scheduler']}\n"
            f"Fresh TCG observations (5 minutes): {s['fresh']}/{len(s['rows'])}\n"
            f"Active stores: {data.get('active_shopify_stores', 0)}\n"
            f"Latest outcome is partial coverage: {s['partial']} • In cooldown: {s['cooldown']}\n")
    if not s['rows']:
        text += 'No per-store observations recorded yet.\n'
    for row, age in s['stale'][:8]:
        age_text = 'not recorded' if age is None else f'{int(age//60)} minutes old'
        text += f"• #{row.get('store_id')} {safe(row.get('store', 'Unknown'))}: {age_text}\n"
    text += ('Partial coverage can provide alerts but is not a full catalog scan.\n'
             'Use /shopifystatus for store details. This summary does not validate other retailer monitors.')
    return text


class Publisher:
    def __init__(self, bot):
        self.bot = bot
        self.messages = {}
        self.denied = set()

    async def publish(self, kind, content, *, edit=True):
        cid = channel_id(kind)
        if not cid or kind in self.denied:
            return False
        try:
            channel = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
            if kind in self.messages and edit:
                try:
                    await self.messages[kind].edit(content=content[:1900], allowed_mentions=discord.AllowedMentions.none())
                    return True
                except discord.NotFound:
                    self.messages.pop(kind, None)
            msg = await channel.send(content[:1900], allowed_mentions=discord.AllowedMentions.none())
            if edit:
                self.messages[kind] = msg
            return True
        except (discord.Forbidden, discord.NotFound):
            self.denied.add(kind)
            print(f'LOTUS OPS CHANNEL UNAVAILABLE | Kind={kind} | RestartAfterPermissionsFixed=True', flush=True)
        except discord.HTTPException:
            print(f'LOTUS OPS DELIVERY FAILED | Kind={kind} | Retry=NEXT_INTERVAL', flush=True)
        return False


async def run(bot):
    from app.shopify_monitor import get_shopify_monitor_status
    await bot.wait_until_ready()
    publisher = Publisher(bot)
    last_status = last_errors = -float('inf')
    baseline = None
    announced = False
    while not bot.is_closed():
        try:
            if not bot.is_ready():
                await asyncio.sleep(60)
                continue
            now = time.monotonic()
            data = get_shopify_monitor_status()
            stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            if not announced:
                announced = await publisher.publish('development',
                    f'**Lotus process started**\nShopify {data.get("component_version", "unknown")} • GAMES1 • {VERSION}\n'
                    f'{stamp}\nMarketplace and shipping channels are reserved; their data pipelines are not enabled.', edit=False)
                # Missing/denied channels must not retry on every health cycle.
                announced = announced or not channel_id('development') or 'development' in publisher.denied
            if now-last_status >= 600:
                worker_age = None if _worker_heartbeat is None else max(0,now-_worker_heartbeat)
                worker = 'Responsive' if worker_age is not None and worker_age < 90 else 'Heartbeat delayed / unknown'
                await publisher.publish('status', f'**Lotus bot status**\nDiscord connection: Ready\n'
                    f'Event worker: {worker}\nShopify scheduler: {snapshot(data)["scheduler"]}\n'
                    f'Shopify {data.get("component_version", "unknown")} • {VERSION}\n'
                    f'Updated {stamp}\nProcess health does not guarantee retailer access or alert delivery.')
                last_status = now
            await publisher.publish('health', health_text(data) + f'\nUpdated {stamp}')
            totals = {'HTTP_429':int(data.get('rate_limit_responses') or 0),
                      'OTHER_SCAN_FAILURES':int(data.get('stores_failed') or 0), **dict(_errors)}
            if baseline is None:
                baseline = {key:0 for key in totals}
                last_errors = now
            if now-last_errors >= 900:
                delta = {k:max(0,v-baseline.get(k,0)) for k,v in totals.items()}
                if any(delta.values()):
                    ok = await publisher.publish('errors', '**Lotus error summary — last reporting interval**\n' +
                        '\n'.join(f'{k}: {v}' for k,v in delta.items() if v) +
                        f'\n{stamp}\nHTTP 429 means throttling, not a crash. Details remain in Railway logs.', edit=False)
                    if ok:
                        baseline = totals
                else:
                    baseline = totals
                last_errors = now
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Do not echo exceptions into Discord; error strings may contain secrets.
            print(f'LOTUS OPS LOOP ERROR | Type={type(error).__name__}', flush=True)
        await asyncio.sleep(60)


def start_operations_status(bot):
    global _task
    if not any(channel_id(k) for k in CHANNELS):
        return None
    if _task is None or _task.done():
        _task = asyncio.create_task(run(bot), name='lotus-operations-status')
    return _task
