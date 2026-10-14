"""Read stored Asian-retailer coverage; no retailer requests or database writes."""
import asyncio
import json
from sqlalchemy import select,func
from app.database import SessionLocal,engine
from app.models import Store,StoreProduct
from app.asia_coverage import summarize,host,TARGETS
from app.store_signing_status import signing_status

async def main():
    if SessionLocal is None: raise RuntimeError('Database not configured')
    records=[]
    try:
        async with SessionLocal() as session:
            stores=(await session.scalars(select(Store))).all()
            targets=[s for s in stores if host(s.domain) in TARGETS]
            ids=[s.id for s in targets]
            stats={}
            if ids:
                rows=(await session.execute(select(StoreProduct.store_id,func.count(StoreProduct.id),func.max(StoreProduct.last_seen_at)).where(StoreProduct.store_id.in_(ids)).group_by(StoreProduct.store_id))).all()
                stats={sid:(count,at) for sid,count,at in rows}
            for s in targets:
                count,at=stats.get(s.id,(0,None))
                platform=(s.platform or '').lower()
                records.append(dict(store_id=s.id,name=s.name,domain=s.domain,platform=s.platform,region=s.region,active=s.active,health=s.health_status,product_count=count,last_product_seen=at,signing=signing_status(host(s.domain))['state'] if platform=='shopify' else 'NOT_APPLICABLE'))
        for row in summarize(records):
            print('LOTUS ASIA COVERAGE | '+json.dumps(row,ensure_ascii=True))
        print('ASIA3 NOTE | Store registry only; separate major-retailer registries are not audited. Recent product records do not prove complete coverage, stock freshness, or Discord delivery. No retailer requests or writes performed.')
    finally:
        if engine is not None: await engine.dispose()

if __name__=='__main__':
    try: asyncio.run(main())
    except Exception as e: raise SystemExit('ASIA3 CHECK FAILED | '+type(e).__name__)
