"""Collect shop names from a public LGS Drops price page, without activating stores."""
import argparse
import json
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import urlopen, Request

class Shops(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows={}
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='div' and 'pp-r' in a.get('class','').split() and a.get('data-rstore') and a.get('data-rkey'):
            key=a['data-rkey']
            import re
            if not re.fullmatch(r'[a-z0-9-]+',key):return
            self.rows[a['data-rstore']]=dict(name=a['data-rstore'],
                discovery_url='https://lgsdrops.com/deal/'+key,
                retailer_domain=None,active=False,stock_verified=False,
                state='DIRECT_STORE_URL_AND_CAPABILITY_REVIEW_REQUIRED')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--page',default='https://lgsdrops.com/price/30th-ditto')
    p.add_argument('--output',default='lgs-store-candidates.json')
    args=p.parse_args();url=urlsplit(args.page)
    if url.scheme!='https' or url.netloc!='lgsdrops.com' or not url.path.startswith('/price/') or url.query or url.fragment:
        p.error('Use an HTTPS lgsdrops.com/price/ product page without query parameters.')
    with urlopen(Request(args.page,headers={'User-Agent':'LotusStoreDiscovery/1.0'}),timeout=25) as response:
        if urlsplit(response.url).netloc!='lgsdrops.com':raise ValueError('Unexpected redirect')
        raw=response.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('Page too large')
    parser=Shops();parser.feed(raw.decode('utf-8'))
    result=dict(source=args.page,candidates=list(parser.rows.values()),stores_activated=0,alerts_sent=0)
    from pathlib import Path
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(candidates=len(parser.rows),output=args.output,stores_activated=0,alerts_sent=0)))

if __name__=='__main__':main()
