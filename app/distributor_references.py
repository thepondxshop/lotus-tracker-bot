"""Local evidence cache used by alert code; no network or database calls on dispatch."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import re
from app.distributor_catalog import norm, packaging

_ROWS=[]
_NAMES=defaultdict(list)
_SKUS=defaultdict(list)
_RETAIL={}
_CASES=[]
COUNTS=Counter()

def install(rows,retailers=None):
    global _ROWS,_NAMES,_SKUS,_RETAIL,_CASES
    _CASES=[r for r in rows if r.get('product_type')=='BOOSTER BOX' and isinstance(r.get('case_quantity'),int) and 1<r['case_quantity']<=1000]
    _ROWS=list(rows);_NAMES=defaultdict(list);_SKUS=defaultdict(list)
    for r in rows:
        _NAMES[r['name_key']].append(r);_SKUS[r['sku'].upper()].append(r)
    if retailers is not None:_RETAIL={r['product_url']:r for r in retailers}

def type_key(value):
    value=str(value or '').upper().strip()
    return {'BOOSTER DISPLAY':'BOOSTER BOX','BOOSTER CASE':'CASE','SEALED CASE':'CASE','ETB':'ELITE TRAINER BOX'}.get(value,value)

def game_matches(game,title):
    aliases={'MTG':'magic the gathering','Pokemon':'pokemon','Yu-Gi-Oh!':'yu gi oh',
             'Yu-Gi-Oh':'yu gi oh','Dragon Ball Super Fusion World':'dragon ball','Final Fantasy TCG':'final fantasy',
             'CookieRun: Braverse':'cookierun'}
    needle=norm(aliases.get(game,game));hay=norm(title)
    return bool(needle and needle!='unknown' and re.search(r'\b'+re.escape(needle)+r'\b',hay))

def matched(event,now=None):
    now=now or datetime.now(timezone.utc)
    if event.get('currency')!='USD' or str(event.get('region','')).upper() not in {'US','USA'} or event.get('product_family')!='GLOBAL_STANDARD':
        COUNTS['REGION_CURRENCY_OR_FAMILY_UNSUPPORTED']+=1;return []
    typ=type_key(event.get('product_type'));title=event.get('product_name','')
    if not packaging(title) or type_key(packaging(title))!=typ:
        COUNTS['RETAIL_PACKAGING_UNVERIFIED']+=1;return []
    candidates=list(_NAMES.get(norm(title),[]));method='EXACT_TITLE_AND_PACKAGING'
    derived = False
    if typ == 'CASE' and not candidates:
        for r in _CASES:
            # Remove only the explicit case wrapper and its evidenced box count.
            key=norm(title)
            key=re.sub(r'\bsealed\b|\bcase\b',' ',key)
            key=re.sub(r'\b'+str(r['case_quantity'])+r'\s*(?:boxes|booster boxes|ct)\b',' ',key)
            key=' '.join(key.split())
            if key==r['name_key']:
                candidates.append(dict(r,product_type='CASE',amount=str(Decimal(r['amount'])*r['case_quantity']),unit_amount=r['amount']))
                derived=True;method='EXACT_BOX_IDENTITY_AND_PUBLISHED_CASE_COUNT'
    retailer=_RETAIL.get(event.get('product_url'))
    # A SKU taken from another version of the stored product cannot be reused.
    if retailer and all(str(retailer.get(k,''))==str(event.get(k,'')) for k in ('product_name','product_type','game','product_family','currency','region')):
        sku=str(retailer.get('sku') or '').upper()
        if sku and _SKUS.get(sku):candidates=list(_SKUS[sku]);method='EXACT_DISTRIBUTOR_SKU_AND_PACKAGING';derived=False
    valid=[]
    for r in candidates:
        try:
            if not r['ready'] or datetime.fromisoformat(r['expires_at'])<=now:continue
            if type_key(r['product_type'])!=typ or not game_matches(event.get('game',''),r['name']):continue
            if datetime.fromisoformat(r['captured_at'])>now:continue
        except (KeyError,TypeError,ValueError):continue
        valid.append(r)
    if not valid:
        COUNTS['NO_EXACT_READY_REFERENCE']+=1;return []
    facts={(Decimal(r['amount']),r['release_date'],r['currency'],r['product_type']) for r in valid}
    if len(facts)!=1:
        COUNTS['DISTRIBUTOR_REFERENCE_CONFLICT']+=1;return []
    r=max(valid,key=lambda r:r['captured_at'])
    COUNTS['MATCHED']+=1
    result=dict(kind='MSRP',scope='EXACT_PRODUCT',confidence='HIGH',amount=r['amount'],
        source=r['source'],currency='USD',region=event['region'],family=event['product_family'],
        release_date=r['release_date'],release_date_source=r['source'],release_date_verified=True,
        captured_at=r['captured_at'],expires_at=r['expires_at'],match_method=method,
        source_sku=r['sku'],source_kind=r['source_kind'],product_url=event.get('product_url'))
    if derived:
        common=dict(reviewed=True,source=r['source'],captured_at=r['captured_at'],expires_at=r['expires_at'])
        result.update(product_type='CASE',game=event['game'],product_family=event['product_family'])
        result['derivation']={'method':'UNIT_MSRP_TIMES_CASE_QUANTITY',
            'unit_reference':dict(common,amount=r['unit_amount'],product_id=r['sku'],product_name=r['name'],unit_type='BOOSTER_BOX',game=event['game'],product_family=event['product_family'],currency='USD',region=event['region']),
            'case_contents':dict(common,case_product_url=event['product_url'],unit_product_id=r['sku'],quantity=r['case_quantity'])}
    return [result]

def status():
    now=datetime.now(timezone.utc)
    return {'records':len(_ROWS),'ready':sum(bool(r.get('ready')) and datetime.fromisoformat(r['expires_at'])>now for r in _ROWS),
        'retailer_records_loaded':len(_RETAIL),'runtime_match_counts':dict(COUNTS)}
