"""Persisted failure cooldown; never grants access or promotes a retailer."""
import re
from datetime import datetime, timezone

def remaining(runtime, now=None):
    error = str(runtime.get('last_error') or '').upper()
    if not re.search(r'(?:HTTP[_ :]*|STATUS[_ :=]*)(403|429|503)\b|CHALLENGE', error):
        return 0
    try:
        streak = max(0, int(runtime.get('consecutive_failures') or 0))
        if not streak: return 0
        last = runtime.get('last_scan_at')
        if isinstance(last, str): last = datetime.fromisoformat(last.replace('Z', '+00:00'))
        if not isinstance(last, datetime): return 0
        if last.tzinfo is None: last = last.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        delay = min(3600, 900 * 2 ** min(streak - 1, 2))
        return max(0, min(delay, int(delay - (now-last).total_seconds())))
    except (TypeError, ValueError, OverflowError):
        return 0
