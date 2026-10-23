from app.distributor_units import unit_valid
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
    rows=[dict(r,name_key=norm(r['name'])) for r in rows]
    for r in rows:
        if not unit_valid(r):
            r['ready']=False
            r['issues']=list(dict.fromkeys(list(r.get('issues',[]))+['PRICE_UNIT_UNVERIFIED']))
        if packaging(r['name']) is None:
            r['ready']=False
            r['issues']=list(dict.fromkeys(list(r.get('issues',[]))+['PACKAGING_UNVERIFIED']))
    _CASES=[r for r in rows if r.get('ready') and r.get('product_type')=='BOOSTER BOX' and isinstance(r.get('case_quantity'),int) and 1<r['case_quantity']<=1000]
    _ROWS=list(rows);_NAMES=defaultdict(list);_SKUS=defaultdict(list)
    for r in rows:
        _NAMES[r['name_key']].append(r);_SKUS[r['sku'].upper()].append(r)
    if retailers is not None:_RETAIL={r['product_url']:r for r in retailers}

def type_key(value):
    value=' '.join(re.sub(r'[_-]+',' ',str(value or '')).upper().split())
    return {'BOOSTER DISPLAY':'BOOSTER BOX','BOOSTER CASE':'CASE','SEALED CASE':'CASE','ETB':'ELITE TRAINER BOX','PREMIUM COLLECTION':'COLLECTION BOX','BOOSTER DISPLAY BOX':'BOOSTER BOX','COLLECTOR BOOSTER BOX':'BOOSTER BOX','PLAY BOOSTER BOX':'BOOSTER BOX','DRAFT BOOSTER BOX':'BOOSTER BOX','SET BOOSTER BOX':'BOOSTER BOX'}.get(value,value)

def game_matches(game,title):
    aliases={'MTG':'magic the gathering','Pokemon':'pokemon','Yu-Gi-Oh!':'yu gi oh',
             'Yu-Gi-Oh':'yu gi oh','Dragon Ball Super Fusion World':'dragon ball','Final Fantasy TCG':'final fantasy',
             'CookieRun: Braverse':'cookierun', 'World of Tanks TCG':'world of tanks',
             'Vibes TCG':'vibes', 'Shadowverse Evolve':'shadowverse evolve'}
    needle=norm(aliases.get(game,game));hay=norm(title)
    return bool(needle and needle!='unknown' and re.search(r'\b'+re.escape(needle)+r'\b',hay))

def matched(event,now=None):
    now=now or datetime.now(timezone.utc)
    if event.get('currency')!='USD' or str(event.get('region','')).upper() not in {'US','USA'} or event.get('product_family')!='GLOBAL_STANDARD':
        COUNTS['REGION_CURRENCY_OR_FAMILY_UNSUPPORTED']+=1;return []
    typ=type_key(event.get('product_type'));title=event.get('product_name','')
    # Retailers often label sleeved packs generically; the exact title retains the sleeve distinction.
    if typ=='BOOSTER PACK' and packaging(title)=='SLEEVED BOOSTER PACK':typ='SLEEVED BOOSTER PACK'
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
            if not unit_valid(r,typ):continue
            if not r['ready'] or datetime.fromisoformat(r['expires_at'])<=now:continue
            # Revalidate persisted rows under current packaging rules.
            if packaging(r['name']) is None:continue
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
    if r.get('unit_evidence') is not None:result['unit_evidence']=dict(r['unit_evidence'])
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



def validated_rows():
    """Snapshot of the same validated records used for matching, for diagnostics."""
    from copy import deepcopy
    rows=deepcopy(_ROWS)
    now=datetime.now(timezone.utc)
    for row in rows:
        try:
            valid_time=datetime.fromisoformat(row['captured_at'])<=now<datetime.fromisoformat(row['expires_at'])
        except (KeyError,TypeError,ValueError):valid_time=False
        if not valid_time:
            row['ready']=False
            row['issues']=list(dict.fromkeys(row.get('issues',[])+['REFERENCE_EXPIRED_OR_INVALID_TIME']))
    return rows
