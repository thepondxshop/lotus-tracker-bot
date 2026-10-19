"""Bounded price-source preview. Does not publish alerts or change reference files."""
import argparse, asyncio, json
from pathlib import Path
from app.marketplaces.price_sources import tcgplayer_prices,cardmarket_prices,tcgplayer_preview,cardmarket_preview

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('market',choices=['tcgplayer','cardmarket'])
    p.add_argument('--ids',required=True,help='Comma-separated source product IDs; SKU IDs with --sku')
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--file',type=Path,help='Native provider JSON already downloaded')
    source.add_argument('--remote',action='store_true',help='TCGplayer only: requires existing approved API access')
    source.add_argument('--download-url',help='Cardmarket only: exact official JSON download link')
    p.add_argument('--foil',action='store_true');p.add_argument('--sku',action='store_true')
    a=p.parse_args();wanted=a.ids.split(',')
    try:
        if (a.foil and a.market!='cardmarket') or (a.sku and a.market!='tcgplayer'):raise ValueError('INVALID_SOURCE_OPTION')
        if a.file:
            if a.file.stat().st_size>40_000_000:raise ValueError('FILE_TOO_LARGE')
            data=json.loads(a.file.read_text())
            rows=tcgplayer_prices(data,wanted,a.sku) if a.market=='tcgplayer' else cardmarket_prices(data,wanted,a.foil)
        elif a.remote and a.market=='tcgplayer':rows=asyncio.run(tcgplayer_preview(wanted,a.sku))
        elif a.download_url and a.market=='cardmarket':rows=asyncio.run(cardmarket_preview(a.download_url,wanted,a.foil))
        else:raise ValueError('INVALID_SOURCE_OPTION')
        print(json.dumps({'state':'PRICE_PREVIEW_ONLY','rows':rows,'alerts_sent':0,
            'references_modified':False,'note':'Provider averages are not verified sold samples. No regional, language, condition or currency blending.'},indent=2))
        return 0
    except Exception as e:
        # Sanitized errors: never print HTTP bodies, credentials or tracebacks.
        print(json.dumps({'state':'PREVIEW_FAILED','error_type':type(e).__name__,
            'reason':str(e) if isinstance(e,ValueError) and str(e).isupper() else 'CHECK_INPUT_OR_SOURCE_ACCESS','alerts_sent':0}))
        return 1
if __name__=='__main__':raise SystemExit(main())
