"""Read-only listing-alert readiness. Does not authorize or send alerts."""
import asyncio
import json
import os
from app.marketplaces.ebay_live_policy import load_targets
from app.marketplaces.ebay_listing_alerts import fingerprint
from app.marketplaces import ebay_shadow

async def main():
    from app.marketplaces.ebay_live_store import Store
    rows=load_targets(os.getenv('EBAY_TARGETS_FILE','ebay-targets.json'))
    key=fingerprint(rows)
    store=Store()
    try:
        await store.start()
        reports=[{'target':t['id'],'listing_shadow_ready':await ebay_shadow.ready(store,key,t['id'],False)} for t in rows]
        print(json.dumps({'scope':'LISTING_ALERTS_ONLY','mode':os.getenv('EBAY_LISTING_MODE','OFF'),
            'worker_mode':os.getenv('EBAY_MONITOR_MODE','OFF'),'listing_config_hash':key,
            'approved_config_matches':os.getenv('EBAY_LISTING_APPROVED_SHA256','')==key,
            'channel_configured':os.getenv('CHANNEL_EBAY_MARKETPLACE','0').isdigit() and int(os.getenv('CHANNEL_EBAY_MARKETPLACE','0'))>0,
            'identity_retention_ready':await store.ready(),'targets':reports,
            'alerts_sent':0,'live_delivery_verified':False},indent=2))
    finally:
        await store.close()

if __name__=='__main__':asyncio.run(main())
