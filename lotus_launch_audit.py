"""Consolidate existing read-only launch checks; never enables stores or publishes."""
import argparse
from collections import Counter
import json
import subprocess
import sys
from pathlib import Path

def parse_records(lines):
    result=[]
    for line in lines:
        if ' | ' not in line:continue
        prefix,body=line.split(' | ',1)
        if prefix.strip() not in {'LOTUS LAUNCH CHECK','LOTUS READINESS LOCAL','LOTUS READINESS DATABASE'}:continue
        try:
            row=json.loads(body)
            if isinstance(row,dict):result.append((prefix.strip(),row))
        except ValueError:pass
    return result

def summarize(records):
    launch=next((r for name,r in records if name=='LOTUS LAUNCH CHECK'),{})
    tables={r.get('table'):r.get('rows',[]) for name,r in records if name=='LOTUS READINESS DATABASE'}
    active=[r for r in tables.get('stores',[]) if r.get('active')]
    shopify=[r for r in active if r.get('platform')=='shopify']
    targets=launch.get('ebay',{}).get('targets',[])
    blockers=Counter()
    for row in targets:
        for field in ('fixed_launch_blockers','auction_launch_blockers'):
            blockers.update(row.get(field,[]))
    markets={}
    for name,row in launch.get('markets',{}).items():
        if name not in {'ebay','mercari_us','buyee_jp','tcgplayer','cardmarket'}:continue
        markets[name]={key:row.get(key) for key in ('minimum_tier','implementation','remaining','live_delivery_verified')}
    retailers=[]
    for row in tables.get('major_retailer_runtime',[]):
        error=str(row.get('last_error') or '').upper()
        reason=('ACCESS_DENIED_403' if '403' in error else 'CHALLENGE' if 'CHALLENGE' in error else
                'RATE_LIMITED_429' if '429' in error else 'OTHER_ERROR' if error else 'NO_RECORDED_ERROR')
        retailers.append(dict(retailer=row.get('retailer_key'),mode=row.get('mode'),
            validation_passes=row.get('validation_passes'),baseline_ready=row.get('baseline_ready'),blocker=reason))
    return dict(scope='STORED_STATE_NOT_LIVE_PROBE',version=launch.get('version'),
        evidence_present=dict(launch=bool(launch),stores='stores' in tables,retailers='major_retailer_runtime' in tables),
        shopify=dict(active=len(shopify),health_counts=dict(Counter(r.get('health_status','UNKNOWN') for r in shopify)),
                     caution='Stored health does not prove current TCG freshness or complete catalog coverage.'),
        markets=markets,ebay=dict(mode=launch.get('ebay',{}).get('mode'),reviewed_targets=len(targets),blockers=dict(blockers)),
        major_retailers=retailers,community_xp=launch.get('community_xp',{}),
        actions=[
            'eBay: obtain a new valid benchmark; expand exact reviewed targets; then verify eligible shadow and live gates.',
            'Shopify: collect a representative log window; compare revisit/capacity wait with source throttling.',
            'Major retailers: resolve per-source access and validation; do not promote blocked stores.',
            'XP: enable required intents/settings, use /xpsetup, and verify /xpstatus and /rank.',
            'Riot: configure news channel/mode; preview drawing reminders before LIVE.',
            'Mercari/Buyee: automatic acquisition remains pending; configured channels are not listing feeds.'],
        alerts_sent=0,stores_enabled=False,live_delivery_verified=False)

def main():
    parser=argparse.ArgumentParser()
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--database',action='store_true',help='Run the two existing diagnostic commands')
    source.add_argument('--file',help='Combined exported launch/readiness text')
    args=parser.parse_args()
    failures=[]
    if args.file:
        lines=Path(args.file).read_text(encoding='utf-8',errors='replace').splitlines()
    else:
        lines=[]
        root=Path(__file__).resolve().parent
        for name in ('lotus_launch_check.py','lotus_readiness_check.py'):
            try:
                result=subprocess.run([sys.executable,str(root/name),'--database'],cwd=root,
                    capture_output=True,text=True,timeout=60,check=False)
                lines.extend(result.stdout.splitlines())
                if result.returncode:failures.append(dict(check=name,state='NONZERO_EXIT'))
            except subprocess.TimeoutExpired:failures.append(dict(check=name,state='TIMEOUT'))
            except OSError:failures.append(dict(check=name,state='EXECUTION_FAILED'))
    result=summarize(parse_records(lines));result['diagnostic_failures']=failures
    print(json.dumps(result,indent=2))
    return int(bool(failures) or not all(result['evidence_present'].values()))
if __name__=='__main__':raise SystemExit(main())
