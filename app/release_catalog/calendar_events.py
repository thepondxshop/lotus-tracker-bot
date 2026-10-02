"""Explicit publisher-backed event sale dates; never mine registration dates."""
from datetime import date


def event_sale_dates(data):
    if not isinstance(data, dict) or data.get('availability_scope') != 'EVENT_EXCLUSIVE':
        return []
    # An event schedule alone does not establish that this product is sold there.
    if data.get('product_sale_confirmed') is not True: return []
    values = data.get('event_sale_dates')
    if not isinstance(values, list) or not 1 <= len(values) <= 50: return []
    try:
        dates = sorted({date.fromisoformat(v).isoformat() for v in values if isinstance(v, str)})
    except ValueError:
        return []
    if len([v for v in values if isinstance(v, str)]) != len(values): return []
    return dates
