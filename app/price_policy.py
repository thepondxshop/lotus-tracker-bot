from app.distributor_units import unit_valid
from app.case_identity import normalize_case_event, shipping_case_event
"""PRICE1: price increases are history-only; deals need exact reference evidence."""
from decimal import Decimal, InvalidOperation
import os
import re

PRICE_EVENTS = {'PRICE_DROP', 'PRICE_INCREASE', 'PRICE_ERROR', 'DEAL'}
US = {'US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA'}

def amount(value):
    if value is None or isinstance(value, bool): return None
    try:
        v=Decimal(str(value))
        return v if v.is_finite() and 0<v<Decimal("1e15") else None
    except (InvalidOperation, ValueError, TypeError): return None

SINGLE_TYPES = {'SINGLE', 'SINGLES', 'SINGLE CARD', 'GRADED CARD', 'SLAB'}
SEALED_TYPES = {'CASE', 'SEALED CASE', 'BOOSTER CASE', 'BOOSTER BOX', 'BOOSTER DISPLAY',
                'BOOSTER BUNDLE', 'BOOSTER PACK', 'SLEEVED BOOSTER PACK', 'DOUBLE PACK',
                'BLISTER', 'ELITE TRAINER BOX', 'ETB', 'COLLECTION BOX', 'TIN',
                'SCENE BOX', 'GIFT BUNDLE', 'PREMIUM COLLECTION', 'DECK', 'STARTER DECK', 'COMMANDER DECK', 'DECK SET', 'BUNDLE', 'SEALED'}

def market_age_status(event, ref, now=None):
    """Sold prices for sealed products start 30 calendar days after sourced release.

    Release metadata belongs to the exact, regional reference, not a date guessed
    from a listing title or the first time Lotus saw the product.
    """
    from datetime import datetime, date, timezone
    from zoneinfo import ZoneInfo
    typ = str(event.get('product_type', '')).strip().upper()
    if typ in SINGLE_TYPES: return 'ELIGIBLE'
    if typ not in SEALED_TYPES: return 'PRODUCT_FORMAT_UNVERIFIED'
    if ref.get('release_date_verified') is not True or not str(ref.get('release_date_source', '')).startswith('https://'):
        return 'RELEASE_DATE_UNVERIFIED'
    try:
        release = date.fromisoformat(ref['release_date'])
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None: return 'RELEASE_DATE_UNVERIFIED'
        elapsed = (current.astimezone(ZoneInfo('America/New_York')).date() - release).days
    except (ValueError, TypeError, KeyError): return 'RELEASE_DATE_UNVERIFIED'
    return 'ELIGIBLE' if elapsed >= 30 else 'BEFORE_MARKET_DAY_30'

def reference_window_status(event, ref, now=None):
    typ = str(event.get('product_type', '')).strip().upper()
    if typ in SINGLE_TYPES:
        return 'ELIGIBLE' if ref.get('kind') == 'MARKET_SOLD' else 'SINGLES_REQUIRE_MARKET'
    age = market_age_status(event, ref, now)
    if ref.get('kind') == 'MSRP':
        if age == 'BEFORE_MARKET_DAY_30': return 'ELIGIBLE'
        if age == 'ELIGIBLE': return 'MSRP_WINDOW_ENDED'
        return age
    return age

def case_destination(event, environ=None):
    """Override only the destination of already-eligible product events."""
    if not shipping_case_event(event): return None
    if event.get('event_type') == 'PRICE_INCREASE': return None
    env = os.environ if environ is None else environ
    raw = str(env.get('CHANNEL_CASE_SEALED_DEALS', '')).strip()
    return {'variable':'CHANNEL_CASE_SEALED_DEALS',
            'channel_id':int(raw) if re.fullmatch(r'[0-9]+',raw) and int(raw)>0 else None,
            'reason':'ALL_CASE_ALERTS', 'version':'CASE30'}

def qualifying_references(event):
    from datetime import datetime, timezone
    r = event.get('reference_evidence')
    rows = r.get('references', [r]) if isinstance(r, dict) else []
    rows=[r for r in rows if isinstance(r,dict) and (r.get('kind')!='MSRP' or unit_valid(r,event.get('product_type')))]
    result = []
    # Conflicting sourced release dates cannot permit both windows at once.
    from datetime import date
    dates = set()
    if str(event.get('product_type', '')).strip().upper() in SEALED_TYPES:
        for row in rows:
            if not isinstance(row, dict): continue
            if (row.get('scope') != 'EXACT_PRODUCT' or row.get('confidence') != 'HIGH'
                    or row.get('currency') != event.get('currency')
                    or row.get('family') != event.get('product_family')
                    or str(row.get('region', '')).upper() not in {str(event.get('region', '')).upper(), 'GLOBAL'}
                    or row.get('release_date_verified') is not True
                    or not str(row.get('release_date_source', '')).startswith('https://')): continue
            try: dates.add(date.fromisoformat(row['release_date']))
            except (KeyError, TypeError, ValueError): continue
        if len(dates) > 1: return []
    for r in rows:
        if not isinstance(r, dict): continue
        if r.get('scope') != 'EXACT_PRODUCT' or r.get('confidence') != 'HIGH': continue
        if r.get('kind') not in {'MSRP', 'MARKET_SOLD'} or not r.get('source'): continue
        if reference_window_status(event, r) != 'ELIGIBLE': continue
        if r.get('currency') != event.get('currency'): continue
        family = event.get('product_family')
        if not family or family == 'UNKNOWN' or r.get('family') != family: continue
        region = str(event.get('region') or '').upper()
        rr = str(r.get('region') or '').upper()
        if rr != region and not (rr == 'GLOBAL' and family == 'GLOBAL_STANDARD'): continue
        if r.get('kind') == 'MARKET_SOLD':
            if market_age_status(event, r) != 'ELIGIBLE': continue
            try:
                count = r.get('sample_count')
                captured = datetime.fromisoformat(r['captured_at'])
                end = datetime.fromisoformat(r['expires_at'])
                if (r.get('reviewed') is not True or isinstance(count, bool) or not isinstance(count, int) or count < 5
                        or captured.tzinfo is None or end.tzinfo is None
                        or captured > datetime.now(timezone.utc) or not 0 < (end-captured).total_seconds() <= 7*86400): continue
            except (ValueError, KeyError, TypeError): continue
        if r.get('expires_at'):
            try:
                expires = datetime.fromisoformat(r['expires_at'])
                if expires.tzinfo is None or expires <= datetime.now(timezone.utc): continue
            except (ValueError, TypeError): continue
        if r.get('derivation') is not None:
            from app.case_msrp import calculated_case_amount
            try:
                if calculated_case_amount(r) != amount(r.get('amount')): continue
            except (ValueError, TypeError, ArithmeticError): continue
        if amount(r.get('amount')) is not None: result.append(r)
    return result

def reference(event):
    rows = qualifying_references(event)
    return amount(rows[0]['amount']) if rows else None

def alert_matches(event):
    if event.get('event_type') == 'PRICE_INCREASE' or event.get('in_stock') is not True: return []
    if event.get('event_type') not in {'DEAL', 'PRICE_DROP', 'PRICE_ERROR', 'RESTOCK', 'STOCK_AVAILABLE', 'DISCOVERED', 'PAGE_LIVE', 'PREORDER_LIVE'}: return []
    current = amount(event.get('price'))
    if current is None: return []
    return [r for r in qualifying_references(event) if (current < amount(r['amount']) if r['kind'] == 'MSRP' else current <= amount(r['amount']) * Decimal('0.90'))]

def deal_matches(event):
    current = amount(event.get('price'))
    return [r for r in alert_matches(event) if current <= amount(r['amount']) * Decimal('0.90')]

def deal_title(event):
    kinds = {r['kind'] for r in alert_matches(event)}
    suffix = ' · DEAL' if deal_matches(event) else ''
    if kinds == {'MSRP', 'MARKET_SOLD'}: return '🔥 BELOW MSRP & MARKET' + suffix
    return ('🔥 BELOW MARKET' if 'MARKET_SOLD' in kinds else '🔥 BELOW MSRP') + suffix


def classify(event):
    if event.get('event_type')=='PRICE_INCREASE': return 'HISTORY_ONLY'
    if event.get('old_currency') not in (None,event.get('currency')): return 'CURRENCY_CHANGED'
    if deal_matches(event): return 'DEAL'
    if alert_matches(event): return 'BELOW_MSRP'
    current,previous=amount(event.get('price')),amount(event.get('old_price'))
    if current is None or previous is None or current>=previous: return 'NO_VERIFIED_DECREASE'
    if event.get('old_currency') not in (None,event.get('currency')): return 'CURRENCY_CHANGED'
    # Quantize only for comparing noise, not for changing displayed prices.
    unit=Decimal('1') if event.get('currency') in {'JPY','KRW'} else Decimal('0.01')
    if current.quantize(unit)>=previous.quantize(unit): return 'ROUNDING_ONLY'
    return 'PRICE_DROP'

def destination(event, environ=None):
    event=normalize_case_event(event)
    env=os.environ if environ is None else environ
    result=classify(event)
    if result not in {'DEAL','BELOW_MSRP','PRICE_DROP'}: return {'classification':result,'variable':None,'channel_id':None}
    global_store=str(event.get('region') or '').upper() not in US
    if result in {'DEAL','BELOW_MSRP'}:
        # Explicit case metadata only; a booster box is not automatically a case.
        is_case=shipping_case_event(event)
        variable='CHANNEL_CASE_SEALED_DEALS' if is_case else ('CHANNEL_GLOBAL_DEALS' if global_store else 'CHANNEL_DEALS')
    else:
        variable='CHANNEL_GLOBAL_PRICE_DROPS' if global_store else 'CHANNEL_PRICE_DROPS'
    raw=str(env.get(variable,'')).strip()
    return {'classification':result,'variable':variable,'channel_id':int(raw) if re.fullmatch(r'[0-9]+',raw) and int(raw)>0 else None}



def explanation(event):
    result = classify(event)
    current, previous = amount(event.get('price')), amount(event.get('old_price'))
    reasons = []
    refs = qualifying_references(event)
    if result not in {'DEAL','BELOW_MSRP'}:
        if event.get('in_stock') is not True: reasons.append('STOCK_NOT_CONFIRMED')
        if not event.get('reference_evidence'): reasons.append('NO_REFERENCE_EVIDENCE')
        elif not refs: reasons.append('REFERENCE_INVALID_MISMATCHED_OR_EXPIRED')
        elif current and not any(current <= amount(r['amount'])*Decimal('0.90') for r in refs):
            reasons.append('LESS_THAN_TEN_PERCENT_BELOW_REFERENCE')
    return {'classification': result, 'historical_drop_percent': str((previous-current)*100/previous) if previous and current else None,
        'deal_blockers': reasons, 'reference_basis': [r['kind'] for r in refs] or 'NONE',
        'qualifying_bases': [r['kind'] for r in alert_matches(event)], 'is_deal': bool(deal_matches(event)),
        'reference_window_checks': [{'kind': row.get('kind'), 'status': reference_window_status(event, row)} for row in (
            event['reference_evidence'].get('references', [event['reference_evidence']])
            if isinstance(event.get('reference_evidence'), dict) else [])
            if isinstance(row, dict) and row.get('kind') in {'MSRP','MARKET_SOLD'}]}


def deal_dedupe_key(event):
    import hashlib
    import json
    fields = [str(event.get(k, '')) for k in ('source_type', 'game', 'store_name', 'product_url', 'price', 'currency')]
    return 'lotus:deal:dedupe:' + hashlib.sha256(json.dumps(fields).encode()).hexdigest()
