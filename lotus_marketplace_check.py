"""MARKET1: configuration, local feed dry run, or one eBay SANDBOX request. No alerts."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from app.international_channels import configuration
from app.marketplaces.foundation import deduplicate_listings


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
    import aiohttp
    token = os.getenv('EBAY_SANDBOX_APPLICATION_TOKEN', '').strip()
    if not token:
        return {'state': 'MISSING_SANDBOX_TOKEN', 'request_sent': False}
    if not query.strip() or len(query) > 200:
        return {'state': 'INVALID_QUERY', 'request_sent': False}
    headers = {'Authorization': 'Bearer ' + token, 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20),
                                     trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as session:
        async with session.get('https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search',
                               params={'q': query, 'limit': '5'}, allow_redirects=False) as response:
            result = {'environment': 'SANDBOX', 'http_status': response.status,
                      'production_access_verified': False, 'alerts_sent': 0}
            if response.status == 429:
                result.update(state='RATE_LIMITED', retry_after=response.headers.get('Retry-After'), retries=0)
                return result
            if response.status != 200:
                result['state'] = 'AUTH_OR_ACCESS_REQUIRED' if response.status in (401, 403) else 'HTTP_ERROR'
                return result
            body = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                body.extend(chunk)
                if len(body) > 1048576:
                    return {**result, 'state': 'RESPONSE_TOO_LARGE'}
            try:
                normalized = normalize_ebay_search(json.loads(body))
            except (ValueError, UnicodeError):
                return {**result, 'state': 'INVALID_RESPONSE'}
            return {**result, **normalized, 'state': 'SANDBOX_RESPONSE_VALIDATED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--feed', type=Path, help='Normalize a local JSON array; no network or Discord')
    actions.add_argument('--ebay-sandbox-query', help='Make ONE sandbox search using a sandbox application token')
    args = parser.parse_args()
    emit('LOTUS MARKETPLACE READINESS', {'version': 'MARKET1', 'channels': configuration(),
         'sandbox_token_present': bool(os.getenv('EBAY_SANDBOX_APPLICATION_TOKEN', '').strip()),
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
        elif args.ebay_sandbox_query:
            emit('LOTUS EBAY SANDBOX', asyncio.run(sandbox_probe(args.ebay_sandbox_query)))
    except Exception as error:
        emit('LOTUS MARKETPLACE ERROR', {'type': type(error).__name__})
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
