"""Preview listings; optionally record an explicit exact-product identity review."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import aiohttp
from app.marketplaces.ebay_live import Browse
from app.marketplaces.ebay_live_store import Store
from app.marketplaces.ebay_live_policy import load_targets, gtin_status, assess
from app.marketplaces.ebay_listing_review import fingerprint
from app.marketplaces.ebay_evidence import identity_key
from lotus_ebay_setup import save

async def run(args):
    path = Path(os.getenv('EBAY_TARGETS_FILE', '/app/app/ebay-targets.json'))
    rows = load_targets(path)
    target = next(t for t in rows if t['id'] == args.target)
    before = path.read_bytes()
    store = Store()
    await store.start()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            api = Browse(store, session)
            if args.item:
                ids = [args.item if args.item.startswith('v1|') else 'v1|' + args.item + '|0']
            else:
                data = await api.get('item_summary/search', {'gtin': target['gtin'], 'limit': '5',
                    'filter': 'itemLocationCountry:US'}, target)
                ids = [r['itemId'] for r in data.get('itemSummaries', [])][:5]
            for iid in ids:
                item = await api.get('item/' + quote(iid, safe=''), {'fieldgroups': 'PRODUCT'}, target)
                if item.get('itemId') != iid:
                    raise ValueError('Returned item identity differs')
                aspects = {a.get('name'): a.get('value') for a in item.get('localizedAspects', [])
                    if isinstance(a, dict) and a.get('name') in {'Language','Configuration','Set','Game','Number of Packs','Number of Cards','UPC','EAN'}}
                print(json.dumps({'item_id': iid, 'url': item.get('itemWebUrl'), 'title': item.get('title'),
                    'condition': item.get('condition'), 'aspects': aspects,
                    'price': item.get('price'), 'minimum_next_bid': item.get('minimumPriceToBid'),
                    'buying_options': item.get('buyingOptions'), 'lot_size': item.get('lotSize'),
                    'identity': gtin_status(item,target), 'assessment': assess(item,target).get('reason','ELIGIBLE')}, indent=2))
                if args.confirm_reviewed:
                    if gtin_status(item,target)['reason'] != 'GTIN_MISSING':
                        raise ValueError('Review only applies to missing identifiers, never mismatches')
                    print('Confirm against the product page: one sealed English Pokemon 151 Booster Bundle containing six packs; no lots, breaks, loose packs, empty boxes or other languages.')
                    if target['id'] != 'pokemon-151-bundle-en':
                        raise ValueError('Interactive review currently supports the 151 pilot only')
                    if input('Type REVIEWED EXACT PRODUCT to save: ').strip() != 'REVIEWED EXACT PRODUCT':
                        print('No changes saved'); return
                    now = datetime.now(timezone.utc)
                    review = {'item_id': iid, 'reviewed': True, 'identity_key': identity_key(target),
                        'fingerprint': fingerprint(item), 'reviewed_at': now.isoformat(),
                        'expires_at': (now+timedelta(days=7)).isoformat()}
                    reviews = [r for r in target.get('reviewed_listings', []) if r.get('item_id') != iid]
                    target['reviewed_listings'] = (reviews + [review])[-50:]
                    if path.read_bytes() != before:
                        raise ValueError('Target file changed during review; no changes saved')
                    save(path, rows)
                    print('Review saved. No alert sent. Other checks remain active; fresh SHADOW eligibility is required. Persist the updated target file before redeployment.')
    finally:
        await store.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--target', default='pokemon-151-bundle-en')
    p.add_argument('--item')
    p.add_argument('--confirm-reviewed', action='store_true')
    args = p.parse_args()
    if args.confirm_reviewed and not args.item:
        p.error('--confirm-reviewed requires one --item')
    asyncio.run(run(args))
