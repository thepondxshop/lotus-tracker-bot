"""Read-only EBAY-NOTIFY1 configuration/challenge check. No eBay API calls."""
import argparse
import asyncio
import hmac
import json
import secrets
import aiohttp
from app.marketplaces.ebay_notifications import Settings, PATH, HEALTH_PATH

async def remote(settings):
    code = secrets.token_hex(16)
    origin = settings.endpoint[:-len(PATH)]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),trust_env=False) as session:
        async with session.get(origin + HEALTH_PATH, allow_redirects=False) as response:
            if response.status != 200:
                return {'state':'REMOTE_NOT_READY','http_status':response.status}
        async with session.get(settings.endpoint, params={'challenge_code':code},allow_redirects=False) as response:
            status=response.status
            data=await response.json() if status==200 else {}
        verified=hmac.compare_digest(str(data.get('challengeResponse','')),settings.challenge(code))
        return {'state':'CHALLENGE_VERIFIED' if verified else 'CHALLENGE_FAILED',
                'http_status':status,'challenge_verified':verified,
                'signed_post_verified':False,'note':'Use eBay Send Test Notification to verify signed POST delivery.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote',action='store_true')
    args=parser.parse_args()
    try:
        settings=Settings.from_env()
        result={'version':'EBAY-NOTIFY1','configured':True,'mode':settings.mode,
                'endpoint':settings.endpoint,'live_alerts_enabled':False}
        if args.remote:result.update(asyncio.run(remote(settings)))
        print('LOTUS EBAY NOTIFICATIONS CHECK | '+json.dumps(result))
        return 0 if not args.remote or result.get('challenge_verified') else 1
    except Exception as error:
        print('LOTUS EBAY NOTIFICATIONS CHECK | '+json.dumps({'configured':False,'error_type':type(error).__name__}))
        return 1
if __name__=='__main__':raise SystemExit(main())
