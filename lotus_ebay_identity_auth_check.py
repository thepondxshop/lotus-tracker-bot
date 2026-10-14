"""Test OAuth on the identity service; never output credentials or token data."""
import asyncio
import json
import os
import aiohttp
from app.marketplaces.ebay import EbayPreview, AccessFailure

async def main():
    result={'service_to_run_on':'lotus-bot-identity',
            'client_id_present':bool(os.getenv('EBAY_PRODUCTION_CLIENT_ID','').strip()),
            'client_secret_present':bool(os.getenv('EBAY_PRODUCTION_CLIENT_SECRET','').strip()),
            'application_token_override_present':bool(os.getenv('EBAY_PRODUCTION_APPLICATION_TOKEN','').strip()),
            'key_lookup_tested':False}
    client=EbayPreview('production')
    # Test client credentials explicitly, not an optional stale token override.
    os.environ.pop('EBAY_PRODUCTION_APPLICATION_TOKEN',None)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),trust_env=False) as session:
            await client.token(session)
        result.update(state='IDENTITY_OAUTH_OK',http_status=200)
    except AccessFailure as error:
        result.update(error.result)
    except Exception as error:
        result.update(state='REQUEST_FAILED',error_type=type(error).__name__)
    print('LOTUS EBAY IDENTITY AUTH CHECK | '+json.dumps(result))
if __name__=='__main__':asyncio.run(main())
