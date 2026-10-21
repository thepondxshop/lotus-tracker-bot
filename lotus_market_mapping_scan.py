"""Match stored retailer products to Cardmarket preview rows; never activates mappings."""
import argparse
import asyncio
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from app.marketplaces import public_market as pm


def name_key(value):
    text=unicodedata.normalize('NFKC',str(value or '')).casefold().replace('é','e')
    # Preserve editions, language, counts, waves, collector numbers, and exclusives.
    text=re.sub(r'[^\w]+',' ',text).strip()
    return re.sub(r'\s+',' ',text)


def candidate(retailer,source):
    m={k:retailer.get(k) for k in pm.BIND}
    m.update(provider='cardmarket',marketplace='cardmarket',source_id=source['source_id'],
        source_name=source['source_name'],category_id=source['category_id'],variant='sealed',
        quantity=1,reviewed=False,packaging_verified=False,accept_provider_aggregate=False,
        release_date=None,release_date_source=None,release_date_verified=False,event_identity={})
    for key in ('variant_id','external_product_id'):
        if retailer.get(key) is not None and str(retailer[key]).strip():
            m['event_identity']={key:str(retailer[key])};break
    blockers=['PRODUCT_AND_LANGUAGE_REVIEW_REQUIRED','PROVIDER_AGGREGATE_ACCEPTANCE_REQUIRED','VERIFIED_RELEASE_DATE_REQUIRED']
    if not m['event_identity']:blockers.append('EVENT_VARIANT_IDENTITY_MISSING')
    identity='|'.join(str(m.get(k,'')) for k in pm.BIND)+':'+source['source_id']
    return {'candidate_id':hashlib.sha256(identity.encode()).hexdigest()[:20],
        'store_name':retailer.get('store_name'),'store_product_id':retailer.get('store_product_id'),
        'match_method':'EXACT_NORMALIZED_NAME_AND_PACKAGE','source_amount':source['amount'],
        'source_field':source['source_field'],'source_updated_at':source['source_updated_at'],
        'retailer_price':str(retailer.get('price')) if retailer.get('price') is not None else None,
        'stored_release_date_unverified':str(retailer.get('release_date')) if retailer.get('release_date') else None,
        'ready_to_import':False,'blockers':blockers,'mapping':m}


def build_report(retailers,sources):
    index=defaultdict(list)
    for s in sources:
        typ=pm.sealed_format(s.get('source_name'),s.get('category_id'))
        if not typ:continue
        index[(name_key(s['source_name']),typ)].append(s)
    counts=Counter();currencies=Counter();candidates=[];examples=defaultdict(list)
    seen=set()
    for r in retailers:
        currencies[str(r.get('currency'))+':'+str(r.get('region'))]+=1
        reason=None
        typ=str(r.get('product_type') or '').upper()
        if r.get('game')!='Pokemon':reason='OTHER_GAME'
        elif typ in {'SINGLE','SINGLE CARD','SINGLES','GRADED CARD','SLAB'}:reason='SINGLES_NEED_EXACT_CARD_VARIANT_AND_CONDITION'
        elif r.get('currency')!='EUR' or r.get('region') not in pm.EU:reason='CARDMARKET_CURRENCY_REGION_UNSUPPORTED'
        elif r.get('product_family') in (None,'','UNKNOWN'):reason='PRODUCT_FAMILY_UNKNOWN'
        elif not isinstance(r.get('product_url'),str) or not r['product_url'].startswith('https://'):reason='PRODUCT_URL_INVALID'
        else:
            hits=index.get((name_key(r.get('product_name')),typ),[])
            if len(hits)>1:reason='AMBIGUOUS_SOURCE_ID'
            elif not hits:reason='NO_EXACT_NAME_AND_PACKAGE'
            elif not hits[0].get('fresh'):reason='SOURCE_PRICE_STALE'
            else:
                c=candidate(r,hits[0])
                if c['candidate_id'] in seen:reason='DUPLICATE_RETAIL_ROW'
                else:seen.add(c['candidate_id']);candidates.append(c);reason='EXACT_CANDIDATE_REQUIRES_REVIEW'
        counts[reason]+=1
        if reason!='EXACT_CANDIDATE_REQUIRES_REVIEW' and len(examples[reason])<3:
            examples[reason].append({k:r.get(k) for k in ('product_name','product_type','store_name','currency','region')})
    return {'state':'CANDIDATES_PREPARED' if candidates else 'NO_EXACT_CANDIDATES',
        'retailer_rows_checked':len(retailers),'published_source_rows':len(sources),
        'candidate_count':len(candidates),'ready_to_import':0,'counts':dict(counts),
        'currency_regions':dict(currencies),'examples':dict(examples),'candidates':candidates,
        'alerts_sent':0,'database_modified':False,'live_mappings_modified':False}


async def database_rows():
    from app.database import engine
    from sqlalchemy import text
    if engine is None:raise ValueError('DATABASE_NOT_CONFIGURED')
    try:
        async with engine.connect() as connection:
            await connection.execute(text('SET TRANSACTION READ ONLY'))
            q=await connection.execute(text('''SELECT sp.id AS store_product_id,sp.url AS product_url,
                sp.currency,sp.price,sp.variant_id,sp.external_product_id,
                p.name AS product_name,p.product_type,p.game,p.product_family,p.release_date,
                s.name AS store_name,s.region
                FROM store_products sp JOIN products p ON p.id=sp.product_id
                JOIN stores s ON s.id=sp.store_id
                WHERE s.active=true AND p.game='Pokemon'
                ORDER BY sp.id LIMIT 50001'''))
            rows=[dict(r) for r in q.mappings()]
        return rows[:50000],len(rows)>50000
    finally:await engine.dispose()


async def run(args):
    rows,truncated=await database_rows()
    # Avoid two downloads when there are no eligible EUR sealed retailer rows.
    eligible=[r for r in rows if r.get('currency')=='EUR' and r.get('region') in pm.EU
        and str(r.get('product_type','')).upper() not in {'SINGLE','SINGLE CARD','SINGLES','GRADED CARD','SLAB'}]
    sources=[]
    if eligible:
        async with pm.session() as client:
            sources=pm.sealed_rows(await pm.fetch(client,pm.CATALOG),await pm.fetch(client,pm.GUIDE))
    result=build_report(rows,sources)
    result['database_limit_reached']=truncated
    result['coverage']='FIRST_50000_ACTIVE_POKEMON_STORE_PRODUCTS' if truncated else 'ALL_ACTIVE_STORED_POKEMON_PRODUCTS'
    destination=Path(args.output).resolve()
    if destination in {pm.mapping_path().resolve(),pm.cache_path().resolve()}:raise ValueError('OUTPUT_CANNOT_OVERWRITE_LIVE_REFERENCES')
    if destination.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_PATH')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation: never replaces an existing mapping/report, even in a race.
    with destination.open('x') as handle:json.dump(result,handle,indent=2,default=str)
    summary={k:v for k,v in result.items() if k not in {'examples','candidates'}}
    summary['report_file']=str(destination)
    print('LOTUS MAPPING SCAN | '+json.dumps(summary))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='market-mapping-candidates.json')
    args=parser.parse_args()
    try:asyncio.run(run(args))
    except Exception as exc:
        reason=str(exc) if type(exc)==ValueError and re.fullmatch('[A-Z0-9_]+',str(exc)) else type(exc).__name__
        print(json.dumps({'state':'SCAN_FAILED','reason':reason,'alerts_sent':0,'database_modified':False}));raise SystemExit(1)
