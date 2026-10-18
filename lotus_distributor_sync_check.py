"""Persistent distributor evidence status and optional one-cycle refresh."""
import argparse,asyncio,json
from collections import Counter
from sqlalchemy import text
from app.distributor_sync import ensure,refresh,load_cache
from app.distributor_references import status,matched

async def run(apply):
    from app.database import engine
    if engine is None:raise SystemExit('DATABASE_URL is missing')
    await ensure(engine)
    # Use the same lock as the background task to avoid duplicate refreshes.
    from app.distributor_sync import LOCK
    if apply:
        async with engine.connect() as lock:
            acquired=True
            if engine.dialect.name=='postgresql':acquired=bool((await lock.execute(text('SELECT pg_try_advisory_lock(:k)'),{'k':LOCK})).scalar())
            if acquired:
                try:print('LOTUS DISTRIBUTOR REFRESH | '+json.dumps(await refresh(engine,force=True)))
                finally:
                    if engine.dialect.name=='postgresql':await lock.execute(text('SELECT pg_advisory_unlock(:k)'),{'k':LOCK})
            else:print('LOTUS DISTRIBUTOR REFRESH | OTHER_WORKER_ACTIVE')
    rows=await load_cache(engine)
    async with engine.connect() as c:
        states=[json.loads(r[0]) for r in (await c.execute(text('SELECT payload FROM lotus_distributor_sync_state'))).all()]
    from app.distributor_references import _RETAIL
    matches=Counter();examples=[]
    for e in _RETAIL.values():
        refs=matched(e)
        if refs:
            matches[refs[0]['source_kind']]+=1
            if len(examples)<5:examples.append({'product':e['product_name'],'source':refs[0]['source'],'match_method':refs[0]['match_method']})
    print('LOTUS DISTRIBUTOR COVERAGE | '+json.dumps({**status(),
        'by_source':dict(Counter(r['source_kind'] for r in rows)),
        'issues':dict(Counter(issue for r in rows for issue in r['issues'])),
        'retailer_matches':dict(matches),'match_examples':examples,
        'sources':[{k:v for k,v in s.items() if k not in {'queue','seen'}} for s in states],
        'alerts_sent':0,'note':'MSRP and release evidence only; no sold-market feed or stock verification.'}))
    await engine.dispose()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--refresh',action='store_true',help='Fetch one bounded cycle and persist observations')
    asyncio.run(run(p.parse_args().refresh))
