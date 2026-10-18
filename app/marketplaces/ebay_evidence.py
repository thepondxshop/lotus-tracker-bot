"""EBAY-LIVE2: reviewed, item-only sold evidence. No network or seller identities."""
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from app.marketplaces.opportunity import number, timestamp

POLICY = 'EBAY-LIVE2-ITEM-ONLY-AGG1-REVIEW1-LOT1'

def identity_key(target):
    fields={k:target[k] for k in ('gtin','condition_id','aspects','quantity','currency')}
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()

def evidence_record(row, target, now=None):
    now = now or datetime.now(timezone.utc)
    expected = {'gtin':target['gtin'], 'condition_id':target['condition_id'],
                'language':target['aspects']['Language'], 'configuration':target['aspects']['Configuration'],
                'quantity':'1', 'currency':'USD'}
    for field, value in expected.items():
        if str(row.get(field, '')).strip().casefold() != str(value).casefold():
            raise ValueError('IDENTITY_MISMATCH_'+field.upper())
    if str(row.get('exact_match','')).lower() != 'true':
        raise ValueError('EXACT_PRODUCT_REVIEW_REQUIRED')
    if row.get('price_kind') not in {'SOLD_FIXED','SOLD_AUCTION','SOLD_BEST_OFFER_ACTUAL'}:
        raise ValueError('ACTUAL_SOLD_PRICE_REQUIRED')
    if row.get('source_kind') not in {'EBAY_PRODUCT_RESEARCH','EBAY_SOLD_LISTING'}:
        raise ValueError('SOURCE_REQUIRED')
    if row['price_kind'] == 'SOLD_BEST_OFFER_ACTUAL' and row['source_kind'] != 'EBAY_PRODUCT_RESEARCH':
        raise ValueError('BEST_OFFER_REQUIRES_ACTUAL_PRODUCT_RESEARCH_PRICE')
    sold = timestamp(row.get('sold_at'))
    amount = number(row.get('item_price'))
    if not sold or not 0 <= (now-sold).total_seconds() <= 14*86400:
        raise ValueError('SALE_OUTSIDE_LAST_14_DAYS')
    if amount is None or amount <= 0 or amount != amount.quantize(Decimal('.01')):
        raise ValueError('INVALID_ITEM_PRICE')
    listing = str(row.get('listing_id','')).strip()
    if not re.fullmatch(r'\d{9,15}',listing):
        raise ValueError('LISTING_ID_REQUIRED')
    # One observation per listing. "20 sold" is not 20 independently verified prices.
    digest = hashlib.sha256(('ebay:'+listing).encode()).hexdigest()
    return {'identity_key':identity_key(target), 'record_key':digest, 'sold_at':sold.isoformat(), 'item_price':str(amount),
            'source_kind':row['source_kind'], 'price_kind':row['price_kind'], 'reviewed':True}

def comparison(target, now=None):
    now = now or datetime.now(timezone.utc)
    if 'aggregate_snapshot' in target:
        from app.marketplaces.ebay_snapshot import snapshot_comparison
        return snapshot_comparison(target['aggregate_snapshot'], identity_key(target), now)
    rows = target.get('sold_records', [])
    if not isinstance(rows,list) or len(rows)>500:
        return {'ready':False,'reason':'INVALID_SOLD_RECORDS','sample_count':0}
    valid={}
    for row in rows:
        if not isinstance(row,dict): continue
        key=row.get('record_key',''); at=timestamp(row.get('sold_at')); amount=number(row.get('item_price'))
        if (row.get('identity_key') != identity_key(target) or not re.fullmatch(r'[0-9a-f]{64}',str(key)) or row.get('reviewed') is not True
                or row.get('source_kind') not in {'EBAY_PRODUCT_RESEARCH','EBAY_SOLD_LISTING'}
                or row.get('price_kind') not in {'SOLD_FIXED','SOLD_AUCTION','SOLD_BEST_OFFER_ACTUAL'}
                or (row.get('price_kind')=='SOLD_BEST_OFFER_ACTUAL' and row.get('source_kind')!='EBAY_PRODUCT_RESEARCH')
                or not at or not 0 <= (now-at).total_seconds() <= 14*86400 or amount is None or amount<=0):
            continue
        if key in valid and valid[key] != amount:
            return {'ready':False,'reason':'CONFLICTING_SOLD_RECORDS','sample_count':0}
        valid[key]=amount
    count=len(valid)
    if count<5: return {'ready':False,'reason':'INSUFFICIENT_SOLD_RECORDS','sample_count':count}
    mean=sum(valid.values())/count
    return {'ready':True,'reason':'REVIEWED_ITEM_ONLY_COMPARISON','sample_count':count,
            'amount':str(mean),'threshold':str((mean*Decimal('.90')).quantize(Decimal('.01'),rounding=ROUND_DOWN)),
            'minimum':str(min(valid.values())),'maximum':str(max(valid.values())), 'basis':'ITEM_ONLY'}

def evaluate_item_only(price, target, auction, now=None):
    ref=comparison(target,now)
    if not ref['ready']: return {'eligible':False,'reason':ref['reason']}
    value=number(price)
    if value is None or value<=0: return {'eligible':False,'reason':'INVALID_PRICE'}
    mean=Decimal(ref['amount'])
    if value > mean*Decimal('.90'): return {'eligible':False,'reason':'BELOW_TEN_PERCENT_SAVINGS'}
    return {'eligible':True,'reason':'TEN_PERCENT_BELOW_SOLD_ITEM_PRICE',
            'destination_variable':'CHANNEL_EBAY_AUCTIONS' if auction else 'CHANNEL_EBAY_INTELLIGENCE',
            'comparison_amount':ref['amount'],'comparison_samples':ref['sample_count'],
            'comparison_label':ref.get('display_label',f"{ref['sample_count']} listing observations, last 14 days"),
            'comparison_basis':'ITEM_ONLY','discount_percent':str((mean-value)/mean*100),
            'maximum_item_bid':ref['threshold'] if auction else None}

def config_hash(targets):
    return hashlib.sha256((POLICY+json.dumps(targets,sort_keys=True,separators=(',',':'))).encode()).hexdigest()
