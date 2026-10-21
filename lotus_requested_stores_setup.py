"""Register the requested stores through Lotus's existing Shopify onboarding."""
import argparse
import asyncio
import json

STORES = (
    {'name': 'Loose Packs', 'domain': 'loosepacks.com', 'region': 'US'},
    {'name': 'Stomping Grounds TCG', 'domain': 'stompinggroundstcg.com', 'region': 'US'},
)

async def activate():
    from app.shopify_monitor import add_shopify_store
    from app.database import engine
    try:
        for entry in STORES:
            store, created = await add_shopify_store(**entry)
            print(json.dumps({'store_id': store.id, 'name': store.name, 'domain': store.domain,
                              'created': created, 'active': store.active,
                              'scan_verified': False, 'alerts_sent_by_setup': 0}))
    finally:
        await engine.dispose()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true', help='Add/update and enable these two Shopify stores')
    args = parser.parse_args()
    if args.activate:
        asyncio.run(activate())
    else:
        print(json.dumps({'stores': STORES, 'database_modified': False, 'next_step': 'Run with --activate'}))

if __name__ == '__main__':
    main()
