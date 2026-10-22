"""Read-only Riot configuration / persisted announcement delivery report."""
import argparse,asyncio,json,os

async def report(database=False):
    result=dict(news_mode=os.getenv('LOTUS_RIOT_NEWS_MODE','OFF').upper(),
        channel_configured=os.getenv('CHANNEL_RIOT_RIFTBOUND','').isdigit(),
        merch_capabilities='PUBLIC_PAGE_PRICE_ONLY',merch_coverage='FIRST_PUBLIC_CATEGORY_PAGE',
        stock_verified=False,live_delivery_verified=False,alerts_sent=0,database_modified=False)
    if database:
        from sqlalchemy import text
        from app.database import engine
        try:
            async with engine.connect() as conn:
                await conn.execute(text('SET TRANSACTION READ ONLY'))
                exists=await conn.scalar(text("SELECT to_regclass('lotus_riot_news')"))
                if exists:
                    rows=(await conn.execute(text('SELECT mode,count(*) AS observations,max(checked_at) AS last_checked FROM lotus_riot_news GROUP BY mode'))).mappings().all()
                    result['observations']=[dict(r) for r in rows]
                else:result['news_schema']='NOT_CREATED'
                if await conn.scalar(text("SELECT to_regclass('lotus_riot_news_delivery')")):
                    rows=(await conn.execute(text('SELECT state,count(*) AS count FROM lotus_riot_news_delivery GROUP BY state'))).mappings().all()
                    result['delivery_counts']={r['state']:r['count'] for r in rows}
        except Exception as exc:result['database_error_type']=type(exc).__name__
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',action='store_true');args=parser.parse_args()
    print(json.dumps(asyncio.run(report(args.database)),indent=2,default=str))
