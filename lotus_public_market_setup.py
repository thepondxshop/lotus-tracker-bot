"""Read-only previews, reviewed exact mapping import, and reference refresh. No alerts."""
import argparse
import asyncio
import json
import re
from pathlib import Path
from app.marketplaces import public_market as pm

async def run(a):
    if a.import_mappings:
        incoming=json.loads(Path(a.import_mappings).read_text())
        if not isinstance(incoming,list):raise ValueError('Expected a list of exact mappings')
        for m in incoming:pm.validate(m)
        existing=pm.mappings()
        # Upsert exact destination + provider/variant, preserving unrelated entries.
        key=lambda m:tuple(m.get(k) for k in pm.BIND+('provider','source_id','variant','marketplace'))
        merged={key(m):m for m in existing}
        merged.update({key(m):m for m in incoming})
        if len(merged)>100:raise ValueError('AT_MOST_100_MAPPINGS')
        pm.atomic_write(pm.mapping_path(),list(merged.values()))
        print(json.dumps({'mappings_saved':len(merged),'alerts_sent':0}));return
    if a.refresh:print(json.dumps(await pm.refresh(),indent=2));return
    if a.card or a.sealed_search is not None:
        async with pm.session() as client:
            rows=pm.card_rows(await pm.fetch(client,pm.card_url(a.card)),a.card) if a.card else pm.sealed_rows(await pm.fetch(client,pm.CATALOG),await pm.fetch(client,pm.GUIDE))
        if a.sealed_search is not None:rows=[r for r in rows if a.sealed_search.casefold() in r['source_name'].casefold()]
        print(json.dumps({'preview_only':True,'matches':len(rows),'rows':rows[:50],'alerts_sent':0},indent=2));return
    ms=pm.mappings()
    print(json.dumps({'mappings':len(ms),'mapping_path':str(pm.mapping_path()),'automatic_refresh_hours':6,
        'maximum_source_age_hours':72,'supported_game':'Pokemon','stock_verified':False,
        'state':'MAPPINGS_CONFIGURED' if ms else 'EXACT_MAPPINGS_REQUIRED','alerts_sent':0},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--card');g.add_argument('--sealed-search');g.add_argument('--refresh',action='store_true');g.add_argument('--import-mappings')
    a=p.parse_args()
    try:asyncio.run(run(a))
    except Exception as e:
        print(json.dumps({'state':'FAILED','error':str(e) if type(e)==ValueError and re.fullmatch('[A-Z0-9_]+',str(e)) else type(e).__name__,'alerts_sent':0}));raise SystemExit(1)
