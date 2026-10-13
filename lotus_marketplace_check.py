"""MARKET2: configuration, local feed dry run or bounded eBay preview. No alerts."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from app.international_channels import configuration
from app.marketplaces.foundation import deduplicate_listings
from app.marketplaces.ebay import EbayPreview, configuration as ebay_configuration


def emit(label, value):
    print(label + ' | ' + json.dumps(value), flush=True)


def normalize_ebay_search(data):
    if not isinstance(data, dict) or 'errors' in data:
        raise ValueError('Invalid eBay search response')
    rows = data.get('itemSummaries', [])
    if not isinstance(rows, list) or ('itemSummaries' not in data and data.get('total') != 0):
        raise ValueError('Missing eBay results')
    accepted, rejected = [], 0
    for row in rows:
        try:
            price = row.get('price') or {}
            accepted.extend(deduplicate_listings([{
                'marketplace': 'ebay', 'listing_id': row.get('itemId'), 'title': row.get('title'),
                'url': row.get('itemWebUrl'), 'price': price.get('value'), 'currency': price.get('currency'),
                'condition': row.get('condition'), 'source_region': (row.get('itemLocation') or {}).get('country'),
                'provenance': 'EBAY_BROWSE_SANDBOX'}]))
        except (ValueError, TypeError, AttributeError):
            rejected += 1
    return {'accepted': len(deduplicate_listings(accepted)), 'rejected': rejected,
            'price_basis': 'ASKING', 'sold_prices_available': False}


async def sandbox_probe(query):
    return await EbayPreview('sandbox').search(query)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--feed', type=Path, help='Normalize a local JSON array; no network or Discord')
    actions.add_argument('--ebay-sandbox-query', help='One sandbox search; token or client credentials')
    actions.add_argument('--ebay-production-query', help='One live Browse search using production credentials; no alerts')
    args = parser.parse_args()
    emit('LOTUS MARKETPLACE READINESS', {'version': 'MARKET2', 'channels': configuration(),
         'ebay_sandbox': ebay_configuration('sandbox'), 'ebay_production': ebay_configuration('production'),
         'live_pipelines_enabled': False, 'mercari_us': 'AUTHORIZED_SOURCE_NOT_INTEGRATED',
         'buyee_jp': 'AUTHORIZED_SOURCE_NOT_INTEGRATED', 'sold_market_prices': 'SOURCE_NOT_INTEGRATED'})
    try:
        if args.feed:
            if args.feed.stat().st_size > 1048576:
                raise ValueError('Feed too large')
            rows = json.loads(args.feed.read_text(encoding='utf-8'))
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError('Expected at most 1000 feed rows')
            normalized = deduplicate_listings(rows)
            emit('LOTUS MARKETPLACE FEED', {'input': len(rows), 'unique': len(normalized),
                  'duplicates': len(rows) - len(normalized), 'alerts_sent': 0, 'database_modified': False})
        elif args.ebay_production_query:
            emit('LOTUS EBAY PRODUCTION PREVIEW', asyncio.run(EbayPreview('production').search(args.ebay_production_query)))
        elif args.ebay_sandbox_query:
            emit('LOTUS EBAY SANDBOX', asyncio.run(sandbox_probe(args.ebay_sandbox_query)))
    except Exception as error:
        emit('LOTUS MARKETPLACE ERROR', {'type': type(error).__name__})
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
