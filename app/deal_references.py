"""Reviewed exact-product reference file. Never invent MSRP or wholesale markups."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

_CACHE = None
_BIND = ('product_url', 'game', 'product_family', 'currency', 'region', 'product_type', 'product_name')

def load(path=None):
    global _CACHE
    p = Path(path or os.getenv('LOTUS_DEAL_REFERENCES_FILE', '/app/app/deal-references.json'))
    if not p.exists():
        return []
    sig = (str(p), p.stat().st_mtime_ns, p.stat().st_size)
    if _CACHE and _CACHE[0] == sig:
        return _CACHE[1]
    if sig[2] > 2000000:
        raise ValueError('Reference file too large')
    rows = json.loads(p.read_text())
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('Expected at most 5000 exact-product references')
    for r in rows:
        if not isinstance(r, dict) or r.get('reviewed') is not True:
            raise ValueError('Every reference must be explicitly reviewed')
        if any(not isinstance(r.get(k), str) or not r[k].strip() or r[k] == 'UNKNOWN' for k in _BIND):
            raise ValueError('Missing product identity: ' + ', '.join(_BIND))
        if not r['product_url'].startswith('https://') or not str(r.get('source', '')).startswith('https://'):
            raise ValueError('Product and evidence source URLs required')
        if r.get('kind') not in {'MSRP', 'MARKET_SOLD'}:
            raise ValueError('Only MSRP or MARKET_SOLD evidence accepted')
        if r.get('scope') != 'EXACT_PRODUCT' or r.get('confidence') != 'HIGH':
            raise ValueError('Exact high-confidence evidence required')
        v = Decimal(str(r.get('amount')))
        if not v.is_finite() or v <= 0:
            raise ValueError('Positive reference amount required')
        end = datetime.fromisoformat(r['expires_at'])
        if end.tzinfo is None:
            raise ValueError('Timezone required')
        if r['kind'] == 'MARKET_SOLD':
            if not isinstance(r.get('sample_count'), int) or isinstance(r['sample_count'], bool) or r['sample_count'] < 5:
                raise ValueError('At least five sold samples required')
            captured = datetime.fromisoformat(r['captured_at'])
            if captured.tzinfo is None or not 0 < (end-captured).total_seconds() <= 7*86400:
                raise ValueError('Sold benchmark requires at most seven-day validity')
    _CACHE = (sig, rows)
    return rows

def matched(event, rows=None, now=None):
    now = now or datetime.now(timezone.utc)
    result = []
    for r in load() if rows is None else rows:
        if all(str(event.get(k, '')).strip() == r[k].strip() for k in _BIND):
            if datetime.fromisoformat(r['expires_at']) <= now:
                continue
            if r.get('captured_at') and datetime.fromisoformat(r['captured_at']) > now:
                continue
            result.append(dict(r, family=r['product_family']))
    return result

def enrich(event):
    event = dict(event)
    try:
        refs = matched(event)
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError) as e:
        print('LOTUS REFERENCE FILE INVALID | Error=' + type(e).__name__, flush=True)
        refs = []
    if refs:
        old = event.get('reference_evidence')
        if isinstance(old, dict):
            refs.extend(old.get('references', [old]))
        event['reference_evidence'] = {'references': refs}
    return event
