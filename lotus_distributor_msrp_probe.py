"""One public-page request. No credentials, database writes or Discord alerts."""
import argparse
import json
import urllib.request
import urllib.error
from app.distributor_msrp import extract, validate_url
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def main():
    p=argparse.ArgumentParser();p.add_argument('url');args=p.parse_args()
    try:validate_url(args.url)
    except ValueError as e:p.error(str(e))
    result={'requests':1,'alerts_sent':0,'database_modified':False,'reference_file_modified':False}
    request=urllib.request.Request(args.url,headers={'User-Agent':'Lotus-Public-MSRP-Probe/1.3.4','Accept':'text/html'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=20) as response:
            result['http_status']=response.status
            data=response.read(2000001)
            if len(data)>2000000:result['state']='RESPONSE_TOO_LARGE'
            else:result.update(extract(args.url,data.decode('utf-8','replace')))
    except urllib.error.HTTPError as e:
        result.update(http_status=e.code,state='HTTP_REJECTED_OR_REDIRECT')
    except (urllib.error.URLError,TimeoutError,OSError):result.update(state='NETWORK_ERROR')
    print('LOTUS DISTRIBUTOR MSRP PROBE | '+json.dumps(result))
if __name__=='__main__':main()
