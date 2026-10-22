"""Validate and optionally activate public page/price monitoring on Railway."""
import argparse
import asyncio
import json

async def main(args):
    from app.major_retailers import (stage_major_retailer, ensure_major_pipeline_schema,
        validate_major_retailer, get_major_promotion_gate, promote_major_retailer,
        get_major_retailer_definition, build_major_retailer_adapter)
    from app.major_retailers.public_pages import PublicPageAdapter
    adapter=build_major_retailer_adapter(args.retailer)
    if args.retailer not in ('premium_bandai','riot_merch') and not isinstance(adapter,PublicPageAdapter):
        raise ValueError('Configure PUBLIC_RETAILER_WATCHLIST_FILE and redeploy first')
    if not args.activate:
        probe=await adapter.healthcheck()
        print(json.dumps(probe.to_dict(),default=str));return
    definition=get_major_retailer_definition(args.retailer)
    await ensure_major_pipeline_schema()
    staged=await stage_major_retailer(name=definition.display_name,domain=definition.domain,region='US')
    print(json.dumps({'stage':staged},default=str))
    for i in range(2):
        if i:await asyncio.sleep(5)
        result=await validate_major_retailer(args.retailer,limit=200)
        print(json.dumps({'validation_pass':i+1,'success':result.get('success'),
            'accepted':result.get('accepted'),'error':result.get('error'),
            'runtime':result.get('runtime')},default=str))
        if not result.get('success'):return
    gate=await get_major_promotion_gate(args.retailer)
    print(json.dumps({'gate':gate},default=str))
    if gate.get('ready'):
        result=await promote_major_retailer(args.retailer)
        print(json.dumps({'promotion':result,'capabilities':'PAGE_AND_PRICE_ONLY',
            'stock_verified':False,'alerts_sent_by_setup':0},default=str))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('retailer',choices=['premium_bandai','target','walmart','gamestop','best_buy','riot_merch'])
    parser.add_argument('--activate',action='store_true',help='Stage, baseline, validate twice, then promote only if ready')
    args=parser.parse_args()
    asyncio.run(main(args))
