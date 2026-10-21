"""Read exported logs; report observed delivery timing, not detection latency."""
import argparse
import json
import math

FIELDS=('QueueAgeSeconds','PreparationSeconds','DiscordSendSeconds','EnqueueToPostSeconds')

def summarize(lines):
    samples={k:[] for k in FIELDS}
    for line in lines:
        if 'LOTUS DELIVERY TIMING |' not in line:continue
        for part in line.split('|'):
            key,sep,value=part.strip().partition('=')
            if sep and key in samples:
                try:
                    number=float(value)
                    if math.isfinite(number) and number>=0:samples[key].append(number)
                except ValueError:pass
    result={}
    for key,values in samples.items():
        if not values:continue
        values.sort()
        result[key]={'samples':len(values),'p50':values[math.ceil(len(values)*.5)-1],
                     'p95':values[math.ceil(len(values)*.95)-1],'maximum':values[-1]}
    return {'timings_seconds':result,'state':'OBSERVED' if result else 'NO_DELIVERY_TIMING_RECORDS',
            'note':'Queue-to-post timing only. Does not measure store change-to-detection latency.',
            'alerts_sent':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('log_file');a=p.parse_args()
    with open(a.log_file,encoding='utf-8',errors='replace') as f:print(json.dumps(summarize(f),indent=2))
