"""Read the public US card catalog without modifying settings or sending alerts."""
import asyncio
import json
from collections import Counter
import aiohttp
from app.pbandai_public import fetch_catalog

async def main():
    result={'alerts_sent':0,'database_modified':False,'stock_verified':False}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=False) as session:
            data=await fetch_catalog(session)
        result.update(state='PRODUCT_SCHEMA_PARSED',total_count=data['total_count'],
            parsed=len(data['products']),rejected=data['rejected'],pages=data['pages'],
            sale_status_counts=dict(Counter(r['sale_status'] for r in data['products'])),
            lottery_products=sum(r['lottery'] for r in data['products']),
            samples=data['products'][:3],coverage='US_CARD_CATEGORY')
    except Exception as error:
        result.update(state='SOURCE_UNAVAILABLE',error_type=type(error).__name__,
            reason=str(error) if isinstance(error,ValueError) else 'REQUEST_FAILED')
    print('LOTUS PREMIUM BANDAI PROBE | '+json.dumps(result))

if __name__=='__main__':asyncio.run(main())
