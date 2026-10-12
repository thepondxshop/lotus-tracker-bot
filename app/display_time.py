"""NY1: New York display only. Persisted timestamps remain UTC."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo('America/New_York')


def new_york_time(value=None, *, missing='Not yet'):
    if value is None:
        return missing
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(at, datetime):
            return missing
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return at.astimezone(NEW_YORK).strftime('%b %d, %Y %I:%M:%S %p %Z')
    except (TypeError, ValueError, OverflowError):
        return missing


def new_york_now():
    return new_york_time(datetime.now(timezone.utc))
