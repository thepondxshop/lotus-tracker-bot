"""Bounded public distributor refresh. Separate from store scanning and alert delivery."""
import asyncio
import contextlib
import json
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
import aiohttp
from sqlalchemy import text
from app.distributor_catalog import parse,SEEDS
from app.distributor_msrp import validate_url
from app.distributor_references import install

LOCK=741031415
SCHEMA=(
 'CREATE TABLE IF NOT EXISTS lotus_distributor_evidence (record_key TEXT PRIMARY KEY, payload TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS lotus_distributor_sync_state (source TEXT PRIMARY KEY, payload TEXT NOT NULL)',
)
async def ensure(engine):
    async with engine.begin() as c:
        for sql in SCHEMA:await c.execute(text(sql))

async def state(engine,key):
    async with engine.connect() as c:
        value=(await c.execute(text('SELECT payload FROM lotus_distributor_sync_state WHERE source=:s'),{'s':key})).scalar()
        return json.loads(value) if value else {}

async def save(engine,key,rows,info):
    async with engine.begin() as c:
        for r in rows:
            rk=r['source_kind']+':'+r['sku']
            await c.execute(text('INSERT INTO lotus_distributor_evidence(record_key,payload) VALUES (:k,:p) ON CONFLICT(record_key) DO UPDATE SET payload=excluded.payload'),{'k':rk,'p':json.dumps(r)})
        await c.execute(text('INSERT INTO lotus_distributor_sync_state(source,payload) VALUES (:s,:p) ON CONFLICT(source) DO UPDATE SET payload=excluded.payload'),{'s':key,'p':json.dumps(info)})

async def load_cache(engine):
    async with engine.connect() as c:
        rows=[json.loads(x[0]) for x in (await c.execute(text('SELECT payload FROM lotus_distributor_evidence'))).all()]
        # Bounded recent retailer identities; no stock changes and no event writes.
        try:
            q=await c.execute(text('''SELECT sp.url AS product_url, sp.sku, sp.currency,
                p.name AS product_name,p.game,p.product_type,p.product_family,s.region
                FROM store_products sp JOIN products p ON p.id=sp.product_id
                JOIN stores s ON s.id=sp.store_id
                WHERE sp.currency='USD' AND p.product_family='GLOBAL_STANDARD'
                ORDER BY sp.last_seen_at DESC LIMIT 50000'''))
            retailers=[dict(r) for r in q.mappings()]
        except Exception as exc:
            print('LOTUS DISTRIBUTOR CACHE | '+json.dumps({'state':'RETAILER_SKU_LOAD_UNAVAILABLE','error':type(exc).__name__}),flush=True)
            # Unit tests/bootstrap may not yet have retailer tables. Match by exact name still works.
            retailers=[]
    install(rows,retailers);return rows

async def fetch(session,url):
    validate_url(url)
    try:
        async with session.get(url,allow_redirects=False) as r:
            if r.status!=200:return None,'HTTP_'+str(r.status)
            body=bytearray()
            async for chunk in r.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body)>2500000:return None,'RESPONSE_TOO_LARGE'
            return body.decode('utf-8','replace'),'OK'
    except (aiohttp.ClientError,TimeoutError) as e:
        return None,type(e).__name__

async def refresh(engine,force=False,fetcher=fetch):
    summaries=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),cookie_jar=aiohttp.DummyCookieJar(),trust_env=False,
            headers={'User-Agent':'Lotus-Public-Distributor/1.4.0','Accept':'text/html'}) as session:
        for key,seed in SEEDS.items():
            previous=await state(engine,key);now=datetime.now(timezone.utc)
            if not force and previous.get('next_attempt') and datetime.fromisoformat(previous['next_attempt'])>now:continue
            rows=[];requests=0;error=None;links=previous.get('queue',[]);page=int(previous.get('page',1));seen=previous.get('seen',[])
            # ACD/GTS advance catalog pages between cycles; PHD rotates discovered article URLs.
            url=seed if page==1 or key=='phd' else seed+('&' if '?' in seed else '?')+urlencode({'page':page})
            try:
                requests+=1;html,error=await fetcher(session,url)
                if html:
                    found,discovered=parse(url,html);rows.extend(found)
                    if key=='phd':
                        new=[u for u in discovered if u not in seen]
                        links=list(dict.fromkeys(new+links))[:1000]
                        seen=list(dict.fromkeys(discovered+seen))[:2000]
                        batch=links[:8];links=links[8:]
                        for position,detail in enumerate(batch):
                            await asyncio.sleep(2)
                            requests+=1;body,outcome=await fetcher(session,detail)
                            if not body:
                                links.append(detail);error=outcome
                                if outcome in {'HTTP_429','HTTP_403'}:
                                    links.extend(batch[position+1:]);break
                                continue
                            try:
                                products,_=parse(detail,body);rows.extend(products)
                            except (ValueError,KeyError,TypeError):error='PARSE_ERROR'
                            links.append(detail)
                    elif key=='acd':page=1  # Public page-two payload not verified; report limited coverage.
                    elif found:page=page+1 if page<50 else 1
                    else:page=1
                    if not rows and error=='OK':error='NO_SUPPORTED_PRODUCTS'
            except (aiohttp.ClientError,TimeoutError,ValueError,KeyError,TypeError) as e:error=type(e).__name__
            # At most one catalog page/source and eight PHD articles per hourly cycle.
            info={'source':key,'checked_at':now.isoformat(),'next_attempt':(now+timedelta(hours=1)).isoformat(),
                  'state':error or 'OK','requests':requests,'observations':len(rows),'ready':sum(r['ready'] for r in rows),
                  'page':page,'queue':links,'seen':seen,
                  'coverage':('FIRST_CATALOG_PAGE_ONLY' if key=='acd' else 'ROTATING_PARTIAL_CATALOG')}
            await save(engine,key,rows,info);summaries.append({k:v for k,v in info.items() if k not in {'queue','seen'}})
    await load_cache(engine);return summaries

async def run(bot):
    from app.database import engine
    if engine is None:return
    while not bot.is_closed():
        try:
            await ensure(engine);await load_cache(engine)
            # Hold a dedicated PostgreSQL advisory lock for this refresh, not a store-scanning lock.
            async with engine.connect() as lock:
                acquired=True
                if engine.dialect.name=='postgresql':
                    acquired=bool((await lock.execute(text('SELECT pg_try_advisory_lock(:k)'),{'k':LOCK})).scalar())
                if acquired:
                    try:
                        for result in await refresh(engine):print('LOTUS DISTRIBUTOR SYNC | '+json.dumps(result),flush=True)
                    finally:
                        if engine.dialect.name=='postgresql':await lock.execute(text('SELECT pg_advisory_unlock(:k)'),{'k':LOCK})
                else:await load_cache(engine)
        except Exception as e:print('LOTUS DISTRIBUTOR SYNC | '+json.dumps({'state':'ERROR','error':type(e).__name__}),flush=True)
        await asyncio.sleep(300)

def start(bot):
    if os.getenv('LOTUS_DISTRIBUTOR_SYNC_ENABLED','true').lower() not in {'true','1','yes'}:return
    task=getattr(bot,'distributor_sync_task',None)
    if not task or task.done():bot.distributor_sync_task=asyncio.create_task(run(bot))

async def stop(bot):
    task=getattr(bot,'distributor_sync_task',None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):await task
