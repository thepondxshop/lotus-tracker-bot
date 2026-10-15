"""Register the ten user-supplied URLs; no retailer requests or forced scans."""
import argparse
import asyncio
import json
URLS = tuple(f'https://www.pokemoncenter.com/product/10-10465-{n}' for n in range(166,176))
async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args=parser.parse_args()
    if not args.apply:
        print(json.dumps({'mode':'PREVIEW','urls':URLS,'writes':0})); return
    from app.pokemon_center_products import add_pokemon_product
    for url in URLS:
        product, created = await add_pokemon_product(url, region='US')
        print(json.dumps({'url':url,'created':created,'active':True,'stock_verified':False}), flush=True)
if __name__=='__main__': asyncio.run(main())
