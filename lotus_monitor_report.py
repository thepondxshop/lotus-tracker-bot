"""Read exported Railway logs. No requests, settings changes or notifications."""
import argparse
from collections import Counter, defaultdict
import json
import math

TIMINGS=('QueueAgeSeconds','PreparationSeconds','DiscordSendSeconds','EnqueueToPostSeconds')

def report(lines):
    timings=defaultdict(list); stores={}; blockers=Counter(); ebay=Counter()
    cycles=0; malformed=0
    for line in lines:
        if 'LOTUS DELIVERY TIMING |' in line:
            for part in line.split('|'):
                key,sep,value=part.strip().partition('=')
                if sep and key in TIMINGS:
                    try:
                        n=float(value)
                        if math.isfinite(n) and n>=0:timings[key].append(n)
                    except ValueError:pass
        for marker,kind in [('SHOPIFY REQUEST EVIDENCE |','shopify'),('LOTUS EBAY MONITOR |','ebay')]:
            if marker not in line:continue
            try:
                row=json.JSONDecoder().raw_decode(line.split(marker,1)[1].lstrip())[0]
                if not isinstance(row,dict):raise ValueError()
            except (ValueError,TypeError):
                malformed+=1;continue
            if kind=='shopify':
                # Do not echo URLs, query parameters, credentials or raw log bodies.
                status=row.get('http_status')
                if status in (401,403,429):blockers[str(status)]+=1
                host=str(row.get('store',''))
                if not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in host):continue
                s=stores.setdefault(host,dict(requests=0,throttles=0,product_responses=0,products_returned=0))
                s['requests']+=1
                if status==429:s['throttles']+=1
                count=row.get('products_count')
                if status==200 and row.get('response_kind')=='PRODUCTS_JSON' and type(count) is int and count>=0:
                    s['product_responses']+=1;s['products_returned']+=count
            elif row.get('state')=='CYCLE_COMPLETE':
                cycles+=1
                for k in ('search_results','details_checked'):
                    if type(row.get(k)) is int and row[k]>=0:ebay[k]+=row[k]
            elif row.get('state') in ('API_PAUSED','CYCLE_FAILED','LEADER_CONNECTION_LOST'):
                blockers[row['state']]+=1
    percentiles={}
    for key,values in timings.items():
        values.sort()
        percentiles[key]=dict(samples=len(values),p50=values[math.ceil(len(values)*.5)-1],
                             p95=values[math.ceil(len(values)*.95)-1],maximum=values[-1])
    return dict(scope='SUPPLIED_LOG_WINDOW_ONLY',delivery_seconds=percentiles,
                shopify=stores,ebay=dict(cycles=cycles,**ebay),blockers=dict(blockers),
                malformed_records=malformed,alerts_sent=0,settings_changed=False,
                limitations=['No store-change timestamp: detection latency and fastest-bot claims are not measured.',
                             'Returned products/search results may repeat; counts are not unique coverage.',
                             'HTTP success does not verify TCG content, stock, full-catalog coverage or live delivery.'])

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('log_file',help='Exported Railway text log')
    args=parser.parse_args()
    with open(args.log_file,encoding='utf-8',errors='replace') as f:
        print(json.dumps(report(f),indent=2))
