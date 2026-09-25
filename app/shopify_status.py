"""Render live scheduler state separately from process-lifetime counters."""
import discord
from datetime import datetime, timezone


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


def build_shopify_status(data, worker_online):
    heartbeat = data.get('scheduler_heartbeat_age_seconds')
    loop = 'Stopped' if not data.get('running') else ('Responsive' if heartbeat is not None and heartbeat < 40 else 'Heartbeat delayed / unavailable')
    out = discord.Embed(title='🛍️ Lotus Shopify Monitor', colour=0x667ACD,
        description=f"Worker: {'Online' if worker_online else 'Offline'}\nScheduler: {loop}\n"
        f"Scan in progress: {'Yes' if data.get('scan_in_progress') else 'No — see each store below'}\n"
        f"Active stores: {data.get('active_shopify_stores', 0)}\nHeartbeat age: {heartbeat if heartbeat is not None else 'Unknown'}s")
    rows = sorted(data.get('store_runtime', []), key=lambda r: r['store_id'])
    stale = sum(observation_age(row) is None or observation_age(row) > 300 for row in rows)
    if stale:
        out.description += f'\n⚠️ {stale}/{len(rows)} stores lack a TCG observation within 5 minutes.'
        out.colour = 0xE6A23C
    for row in rows[:6]:
        phase = row.get('phase', 'UNKNOWN')
        if (row.get('overdue_seconds') or 0) > 30:
            phase += ' • OVERDUE'
        elif phase in ('SCANNING', 'LOAD_SETTINGS') and row.get('phase_age_seconds', 0) > 180:
            phase += ' • LONG RUNNING'
        value = f"{phase} • Last outcome: {row.get('outcome', 'Not yet')}\n"
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
        out.add_field(name=safe(f"#{row['store_id']} • {row.get('store', 'Loading store')}", 80), value=value[:760], inline=False)
    if not rows:
        out.add_field(name='Store workers', value='No per-store state recorded yet. Check scheduler heartbeat and Railway logs.', inline=False)
    if len(rows) > 6:
        out.add_field(name='More stores', value=f'{len(rows)-6} additional store workers are omitted from this view.', inline=False)
    out.add_field(name='Since this process started', value=
        f"HTTP 429 responses: {data.get('rate_limit_responses', 0)}\n"
        f"Rate-limited scan attempts: {data.get('rate_limited_scans', 0)}\n"
        f"Other failed scans: {data.get('stores_failed', 0)}\n"
        f"Accumulated requested backoff: {data.get('rate_limit_backoff_seconds', 0):.1f}s\n"
        'Backoff is a total across attempts, not the current wait.', inline=False)
    out.add_field(name='Latest stored scan results', value=
        f"Products seen: {data.get('products_seen', 0)} • Events: {data.get('events_created', 0)} • Flickers: {data.get('flickers_detected', 0)}\n"
        'Results may be from different times; compare each store’s observation time above.', inline=False)
    out.set_footer(text=f"Shopify {data.get('component_version', 'unknown')} • All times UTC • Waiting is not a scan failure")
    return out
