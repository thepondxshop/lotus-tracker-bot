"""Reviewed visible-row snapshot; no network, inferred individual sales, or seller data."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN
from app.marketplaces.opportunity import number, timestamp

# User confirmed LAST_7_DAYS. Exact UI range is cropped: use a conservative
# earliest-date bound, not an invented exact sale timestamp for each unit.
SNAPSHOT_151 = {
 'schema':'PRODUCT_RESEARCH_AGGREGATE1', 'snapshot_id':'pokemon151-visible-20261015',
 'source_kind':'EBAY_PRODUCT_RESEARCH', 'source_scope':'VISIBLE_ROWS_ONLY',
 'evidence_file':'Screenshot 2026-10-15 223956.png', 'period_label':'LAST_7_DAYS',
 'captured_at':'2026-10-15T22:40:05-04:00',
 'window_start_bound':'2026-10-08T00:00:00-04:00',
 'window_end_bound':'2026-10-15T22:40:05-04:00',
 'window_precision':'CONSERVATIVE_BOUND_USER_CONFIRMED_LAST_7_DAYS',
 'currency':'USD', 'cost_basis':'ITEM_ONLY',
 'rows':[
  {'row_key':'visible-01','units':19,'item_sales':'2185.63'},
  {'row_key':'visible-02','units':28,'item_sales':'3400.00'},
  {'row_key':'visible-03','units':9,'item_sales':'1220.00'},
  {'row_key':'visible-04','units':4,'item_sales':'437.80'},
  {'row_key':'visible-05','units':4,'item_sales':'465.66'},
  {'row_key':'visible-06','units':2,'item_sales':'289.32'},
  {'row_key':'visible-08','units':2,'item_sales':'300.00'},
  {'row_key':'visible-09','units':2,'item_sales':'216.00'},
  {'row_key':'visible-10','units':3,'item_sales':'299.97'},
 ],
 'excluded_rows':[{'row_key':'visible-07','reason':'TWO_BUNDLE_LOT','units':2,'item_sales':'679.98'}],
 'reviewed':True, 'exact_match':True,
}

def snapshot_comparison(snapshot, target_identity, now=None):
    now=now or datetime.now(timezone.utc)
    def fail(reason):return {'ready':False,'reason':reason,'sample_count':0}
    if (not isinstance(snapshot,dict) or snapshot.get('schema')!='PRODUCT_RESEARCH_AGGREGATE1'
            or snapshot.get('identity_key')!=target_identity or snapshot.get('reviewed') is not True
            or snapshot.get('exact_match') is not True or snapshot.get('source_kind')!='EBAY_PRODUCT_RESEARCH'
            or snapshot.get('source_scope')!='VISIBLE_ROWS_ONLY' or snapshot.get('currency')!='USD'
            or snapshot.get('cost_basis')!='ITEM_ONLY' or snapshot.get('period_label')!='LAST_7_DAYS'):
        return fail('INVALID_AGGREGATE_EVIDENCE')
    start=timestamp(snapshot.get('window_start_bound'));end=timestamp(snapshot.get('window_end_bound'));captured=timestamp(snapshot.get('captured_at'))
    if not start or not end or not captured or not start<end<=captured<=now or end-start>timedelta(days=8):
        return fail('INVALID_AGGREGATE_WINDOW')
    # No individual dates available: expire the whole snapshot conservatively.
    expires=min(start+timedelta(days=14),captured+timedelta(days=7))
    if now>=expires:return fail('AGGREGATE_SNAPSHOT_EXPIRED')
    rows=snapshot.get('rows');seen=set();units=0;total=Decimal('0')
    if not isinstance(rows,list) or not 5<=len(rows)<=500:return fail('INSUFFICIENT_AGGREGATE_ROWS')
    for row in rows:
        if not isinstance(row,dict):return fail('INVALID_AGGREGATE_ROW')
        key=row.get('row_key');n=row.get('units');amount=number(row.get('item_sales'))
        if not isinstance(key,str) or not key or key in seen:return fail('DUPLICATE_OR_INVALID_AGGREGATE_ROW')
        if not isinstance(n,int) or isinstance(n,bool) or n<=0 or amount is None or amount<=0 or amount!=amount.quantize(Decimal('.01')):
            return fail('INVALID_AGGREGATE_ROW')
        seen.add(key);units+=n;total+=amount
    mean=total/units
    return {'ready':True,'reason':'REVIEWED_AGGREGATE_SNAPSHOT','basis':'ITEM_ONLY',
            'sample_count':units,'sample_unit':'UNITS_SOLD','listing_rows':len(rows),
            'item_sales_total':str(total),'amount':str(mean),
            'threshold':str((mean*Decimal('.90')).quantize(Decimal('.01'),rounding=ROUND_DOWN)),
            'expires_at':expires.isoformat(),'captured_at':captured.isoformat(),
            'source_scope':'VISIBLE_ROWS_ONLY','period_label':'LAST_7_DAYS',
            'display_label':f'{units} units across {len(rows)} reviewed rows; seven-day snapshot, visible results only'}

def apply_151_snapshot(target):
    from app.marketplaces.ebay_evidence import identity_key
    if (target.get('id')!='pokemon-151-bundle-en' or target.get('gtin')!='820650853210'
        or target.get('aspects')!={'Language':'English','Configuration':'Box'}
        or target.get('condition_id')!='1000' or target.get('quantity')!=1 or target.get('currency')!='USD'):
        raise ValueError('Snapshot only matches the reviewed English 151 six-pack bundle')
    snapshot=deepcopy(SNAPSHOT_151);snapshot['identity_key']=identity_key(target)
    target['aggregate_snapshot']=snapshot
    target['sold_records']=[]  # Existing target is backed up by the setup tool.
    target['comparison_mode']='ITEM_ONLY'
    return target
