"""AUCTION1: offline opportunity evaluation; no fetching, bidding or publication."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN

def number(value):
    if value is None or isinstance(value,bool): return None
    try:
        v=Decimal(str(value))
        return v if v.is_finite() and v>=0 else None
    except (InvalidOperation,ValueError,TypeError): return None

def timestamp(value):
    try:
        at=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return at if at.tzinfo is not None else None
    except (ValueError,TypeError): return None

def evaluate(row, now=None):
    now=now or datetime.now(timezone.utc)
    def stop(reason): return {'eligible':False,'reason':reason,'alerts_sent':0,'live_pipeline_enabled':False}
    market=row.get('marketplace')
    if market not in {'ebay','mercari_us','buyee_jp'}: return stop('UNSUPPORTED_MARKET')
    ref=row.get('comparison') or {}
    price=number(row.get('minimum_next_bid') if row.get('auction') else row.get('price'))
    average=number(ref.get('amount'))
    at=timestamp(ref.get('as_of'))
    if (ref.get('verified') is not True or ref.get('exact_match') is not True
        or ref.get('basis')!='SOLD' or not ref.get('source')
        or not isinstance(ref.get('sample_count'),int) or isinstance(ref.get('sample_count'),bool)
        or ref['sample_count']<5 or at is None or average is None or average<=0
        or not 0 <= (now-at).total_seconds() <= 14*86400
        or ref.get('currency')!=row.get('currency')):
        return stop('INSUFFICIENT_COMPARISON')
    observed=timestamp(row.get('observed_at'))
    if observed is None or not 0<=(now-observed).total_seconds()<=60:
        return stop('STALE_LISTING')
    costs=row.get('purchase_costs') or {}
    fixed,rate=number(costs.get('fixed')),number(costs.get('tax_rate'))
    if costs.get('verified') is not True or costs.get('complete') is not True or fixed is None or rate is None or rate>1 or costs.get('currency')!=row.get('currency'):
        return stop('UNKNOWN_COSTS')
    mode=costs.get('mode')
    if mode not in {'SHIP_HOME','SEND_TO_VAULT','KEEP_VAULTED'}: return stop('UNKNOWN_PURCHASE_MODE')
    if mode!='SHIP_HOME' and costs.get('vault_eligibility_verified') is not True: return stop('UNVERIFIED_VAULT')
    if price is None or price<=0: return stop('INVALID_PRICE')
    remaining=None
    if row.get('auction'):
        if market not in {'ebay','buyee_jp'}: return stop('UNSUPPORTED_AUCTION')
        end=timestamp(row.get('ends_at'))
        remaining=(end-now).total_seconds() if end else -1
        if not 0<remaining<=600: return stop('OUTSIDE_FINAL_TEN_MINUTES')
    total=price*(1+rate)+fixed
    target=average*Decimal('0.90')
    if total>target: return stop('BELOW_TEN_PERCENT_SAVINGS')
    unit=Decimal('1') if row.get('currency') in {'JPY','KRW'} else Decimal('0.01')
    ceiling=((target-fixed)/(1+rate)).quantize(unit,rounding=ROUND_DOWN)
    variable=('CHANNEL_EBAY_AUCTIONS' if market=='ebay' else 'CHANNEL_BUYEE_AUCTIONS') if row.get('auction') else {'ebay':'CHANNEL_EBAY_INTELLIGENCE','mercari_us':'CHANNEL_MERCARI_INTELLIGENCE','buyee_jp':'CHANNEL_BUYEE_INTELLIGENCE'}[market]
    return {'eligible':True,'reason':'TEN_PERCENT_BELOW_SOLD_COMPARISON','destination_variable':variable,
            'minimum_tier':'Premium+' if market=='buyee_jp' else 'Premium',
            'comparison_amount':str(average),'current_total':str(total),
            'maximum_item_bid':str(ceiling) if row.get('auction') else None,
            'seconds_remaining':remaining,'purchase_mode':mode,
            'review_required':True,'alerts_sent':0,'live_pipeline_enabled':False}
