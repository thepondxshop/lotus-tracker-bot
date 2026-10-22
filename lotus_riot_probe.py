"""Read-only public Riot probe: no database, Discord, login or drawing entry."""
import asyncio,json
import aiohttp
from app.riot_public import FAQ,NEWS,CATALOG,fetch,article,article_links,merch_rows

async def main():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'LotusTracker/1.7.3 (+https://thepondx.com)'}) as session:
        report={'alerts_sent':0,'database_modified':False,'stock_verified':False}
        for label,url,parse in [('announcement',FAQ,lambda b:article(b,FAQ)),('news_index',NEWS,article_links),('storefront',CATALOG,merch_rows)]:
            try:
                data=parse(await fetch(session,url))
                report[label]={'state':'PARSED','result':data if label=='announcement' else {'count':len(data),'samples':data[:3]}}
            except Exception as exc:
                report[label]={'state':'FAILED','error_type':type(exc).__name__}
                break  # Stop on a failure; do not continue into a rate limit.
            await asyncio.sleep(1.5)
        print(json.dumps(report,indent=2))

if __name__=='__main__':asyncio.run(main())
