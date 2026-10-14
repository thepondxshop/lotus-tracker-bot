"""PRICE1: price increases are history-only; deals need exact reference evidence."""
from decimal import Decimal, InvalidOperation
import os
import re

PRICE_EVENTS = {'PRICE_DROP', 'PRICE_INCREASE', 'PRICE_ERROR'}
US = {'US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA'}

def amount(value):
    if value is None or isinstance(value, bool): return None
    try:
        v=Decimal(str(value))
        return v if v.is_finite() and 0<v<Decimal("1e15") else None
    except (InvalidOperation, ValueError, TypeError): return None

def reference(event):
    r=event.get('reference_evidence')
    if not isinstance(r,dict): return None
    if r.get('scope')!='EXACT_PRODUCT' or r.get('confidence')!='HIGH': return None
    if r.get('kind')!='MSRP' or not r.get('source'): return None
    if r.get('currency')!=event.get('currency'): return None
    family=event.get('product_family')
    if not family or family=='UNKNOWN' or r.get('family')!=family: return None
    region=str(event.get('region') or '').upper()
    ref_region=str(r.get('region') or '').upper()
    if ref_region!=region and not (ref_region=='GLOBAL' and family=='GLOBAL_STANDARD'): return None
    return amount(r.get('amount'))

def classify(event):
    if event.get('event_type')=='PRICE_INCREASE': return 'HISTORY_ONLY'
    current,previous=amount(event.get('price')),amount(event.get('old_price'))
    if current is None or previous is None or current>=previous: return 'NO_VERIFIED_DECREASE'
    if event.get('old_currency') not in (None,event.get('currency')): return 'CURRENCY_CHANGED'
    # Quantize only for comparing noise, not for changing displayed prices.
    unit=Decimal('1') if event.get('currency') in {'JPY','KRW'} else Decimal('0.01')
    if current.quantize(unit)>=previous.quantize(unit): return 'ROUNDING_ONLY'
    ref=reference(event)
    if event.get('in_stock') is True and ref is not None and current<=ref*Decimal('0.90'):
        return 'DEAL'
    return 'PRICE_DROP'

def destination(event, environ=None):
    env=os.environ if environ is None else environ
    result=classify(event)
    if result not in {'DEAL','PRICE_DROP'}: return {'classification':result,'variable':None,'channel_id':None}
    global_store=str(event.get('region') or '').upper() not in US
    if result=='DEAL':
        # Explicit case metadata only; a booster box is not automatically a case.
        is_case=str(event.get('product_type') or '').upper() in {'CASE','SEALED CASE','BOOSTER CASE'}
        variable='CHANNEL_CASE_SEALED_DEALS' if is_case else ('CHANNEL_GLOBAL_DEALS' if global_store else 'CHANNEL_DEALS')
    else:
        variable='CHANNEL_GLOBAL_PRICE_DROPS' if global_store else 'CHANNEL_PRICE_DROPS'
    raw=str(env.get(variable,'')).strip()
    return {'classification':result,'variable':variable,'channel_id':int(raw) if re.fullmatch(r'[0-9]+',raw) and int(raw)>0 else None}
