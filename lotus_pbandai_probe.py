"""One read-only request to the supplied US Premium Bandai search URL.
No monitor, browser launch, alerts, database writes or automatic retries.
"""
import asyncio
import json
import aiohttp
URL = 'https://p-bandai.com/api/search?keyword=&_f_series=03-002&_f_productStatuses=Waiting,On,End&_f_categories=04-011&offset=0&limit=20&sortType=NewArrival&includeAggs=true'
async def main():
    result={'requests':1,'alerts_sent':0,'database_modified':False,'product_schema_verified':False}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=False) as session:
            async with session.get(URL,headers={'X-G1-Area-Code':'us','User-Agent':'LotusTrackerProbe/1.0 (+https://thepondx.com)'},allow_redirects=False) as response:
                result.update(http_status=response.status,retry_after=response.headers.get('Retry-After'))
                if response.status != 200:
                    result['state']='HTTP_NOT_OK'
                else:
                    body=bytearray()
                    async for chunk in response.content.iter_chunked(8192):
                        body.extend(chunk)
                        if len(body)>2097152: raise ValueError('Oversized response')
                    data=json.loads(body)
                    products=data.get('productResults') if isinstance(data,dict) else None
                    if not isinstance(products,dict):
                        result['state']='PRODUCT_RESULTS_MISSING'
                    else:
                        count=products.get('totalCount')
                        valid=isinstance(count,int) and not isinstance(count,bool) and count>=0
                        result.update(state='TOTAL_COUNT_PARSED' if valid else 'INVALID_TOTAL_COUNT',
                                      total_count=count if valid else None,
                                      result_keys=sorted(products)[:30],
                                      list_lengths={k:len(v) for k,v in products.items() if isinstance(v,list)})
    except Exception as error:
        result.update(state='REQUEST_OR_JSON_FAILED',error_type=type(error).__name__)
    print('LOTUS PREMIUM BANDAI PROBE | '+json.dumps(result),flush=True)
if __name__=='__main__':asyncio.run(main())
