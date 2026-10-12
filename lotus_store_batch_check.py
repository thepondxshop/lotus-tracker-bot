"""Read-only STORES1 preflight. No DB writes, messages, retries or full scans."""
import argparse, asyncio, json
from pathlib import Path
import aiohttp

async def probe(row):
    if row['platform'] != 'shopify':
        return {'domain':row['domain'], 'result':'USE_SILENT_ADAPTER_VALIDATION', 'platform':row['platform']}
    url=f"https://{row['domain']}/collections/{row['collection']}/products.json?limit=2&page=1"
    result={'domain':row['domain'],'signed':False,'url':url,'products_json':False}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),cookie_jar=aiohttp.DummyCookieJar(),trust_env=False) as session:
            async with session.get(url,allow_redirects=False,headers={'User-Agent':'LotusTracker/STORES1 (public retailer preflight)','Accept':'application/json'}) as response:
                result['http']=response.status
                result['retry_after']=response.headers.get('Retry-After')
                body=bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    body.extend(chunk)
                    if len(body)>1048576:break
                if response.status==200 and len(body)<=1048576:
                    try:
                        data=json.loads(body)
                        products=data.get('products') if isinstance(data,dict) else None
                        result['products_json']=isinstance(products,list)
                        if result['products_json']:result['sample_count']=len(products)
                    except (ValueError,UnicodeError):pass
    except Exception as error:
        result['error_type']=type(error).__name__
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',metavar='DOMAIN',help='One unsigned GET to a listed Shopify collection; no retries')
    args=parser.parse_args()
    rows=json.loads(Path(__file__).with_name('lotus_store_batch.json').read_text())
    if args.probe:
        domain=args.probe.lower().removeprefix('www.')
        row=next((r for r in rows if r['domain'].removeprefix('www.')==domain),None)
        if not row:parser.error('Domain is not in this reviewed batch.')
        print('LOTUS STORE PREFLIGHT | '+json.dumps(asyncio.run(probe(row))))
    else:
        for row in rows:
            print(json.dumps(row))
        print('Configuration only. Stores have NOT been added or enabled. Flipside is already monitored; do not duplicate it.')
if __name__=='__main__':main()
