"""MARKET2: bounded eBay Browse preview; no scheduler, purchases or Discord sends."""
import asyncio
import json
import os
import time
import aiohttp
from app.marketplaces.foundation import normalize_listing

HOSTS = {'sandbox': 'https://api.sandbox.ebay.com', 'production': 'https://api.ebay.com'}


class AccessFailure(Exception):
    def __init__(self, state, phase, status=None, retry_after=None):
        self.result = {'state': state, 'phase': phase, 'http_status': status,
                       'retry_after': retry_after, 'retries': 0}
        super().__init__(state)


async def response_json(response, phase):
    if response.status != 200:
        state = 'RATE_LIMITED' if response.status == 429 else (
            'AUTH_OR_ACCESS_REQUIRED' if response.status in (401, 403) else 'HTTP_ERROR')
        raise AccessFailure(state, phase, response.status, response.headers.get('Retry-After'))
    body = bytearray()
    async for chunk in response.content.iter_chunked(8192):
        body.extend(chunk)
        if len(body) > 1048576:
            raise AccessFailure('RESPONSE_TOO_LARGE', phase, response.status)
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise AccessFailure('INVALID_JSON', phase, response.status) from None
    if not isinstance(data, dict):
        raise AccessFailure('INVALID_RESPONSE', phase, response.status)
    return data


def configuration(environment):
    if environment not in HOSTS:
        raise ValueError('Unsupported environment')
    prefix = 'EBAY_' + environment.upper()
    return {'environment': environment,
            'application_token_present': bool(os.getenv(prefix + '_APPLICATION_TOKEN', '').strip()),
            'client_id_present': bool(os.getenv(prefix + '_CLIENT_ID', '').strip()),
            'client_secret_present': bool(os.getenv(prefix + '_CLIENT_SECRET', '').strip()),
            'live_pipeline_enabled': False}


def normalize_search(data, environment):
    rows = data.get('itemSummaries', [])
    if 'errors' in data or not isinstance(rows, list) or ('itemSummaries' not in data and data.get('total') != 0):
        raise AccessFailure('INVALID_SEARCH_RESPONSE', 'SEARCH', 200)
    results, rejected, seen = [], 0, set()
    for row in rows[:5]:
        try:
            price = row.get('price') or {}
            normalized = normalize_listing({
                'marketplace': 'ebay', 'listing_id': row.get('itemId'), 'title': row.get('title'),
                'url': row.get('itemWebUrl'), 'price': price.get('value'), 'currency': price.get('currency'),
                'condition': row.get('condition'), 'source_region': (row.get('itemLocation') or {}).get('country'),
                'provenance': 'EBAY_BROWSE_' + environment.upper()})
            # Search results are candidates, not automatically classified TCG alerts.
            normalized.update(review_required=True, sandbox=(environment == 'sandbox'))
            if normalized['listing_id'] not in seen:
                results.append(normalized)
                seen.add(normalized['listing_id'])
        except (TypeError, AttributeError, ValueError):
            rejected += 1
    return {'accepted': len(results), 'rejected': rejected, 'candidates': results,
            'price_basis': 'ASKING', 'sold_prices_available': False}


class EbayPreview:
    def __init__(self, environment='sandbox'):
        if environment not in HOSTS:
            raise ValueError('Unsupported environment')
        self.environment = environment
        self.host = HOSTS[environment]
        self.prefix = 'EBAY_' + environment.upper()
        self._token = None
        self._expires = 0

    async def token(self, session):
        explicit = os.getenv(self.prefix + '_APPLICATION_TOKEN', '').strip()
        if explicit:
            return explicit
        if self._token and time.monotonic() < self._expires:
            return self._token
        client = os.getenv(self.prefix + '_CLIENT_ID', '').strip()
        secret = os.getenv(self.prefix + '_CLIENT_SECRET', '').strip()
        if not client or not secret:
            raise AccessFailure('MISSING_CREDENTIALS', 'AUTH')
        async with session.post(self.host + '/identity/v1/oauth2/token',
                auth=aiohttp.BasicAuth(client, secret),
                data={'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'},
                allow_redirects=False) as response:
            data = await response_json(response, 'AUTH')
        token = data.get('access_token')
        try:
            lifetime = float(data.get('expires_in', 0))
        except (ValueError, TypeError):
            lifetime = 0
        if not isinstance(token, str) or not token.strip() or not 0 < lifetime < float('inf'):
            raise AccessFailure('INVALID_TOKEN_RESPONSE', 'AUTH', 200)
        self._token = token
        self._expires = time.monotonic() + max(0, lifetime - 60)
        return token

    async def search(self, query):
        base = {'environment': self.environment, 'alerts_sent': 0, 'database_modified': False,
                'live_pipeline_enabled': False, 'production_access_verified': False}
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            return {**base, 'state': 'INVALID_QUERY', 'request_sent': False}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                    trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as session:
                token = await self.token(session)
                async with session.get(self.host + '/buy/browse/v1/item_summary/search',
                        headers={'Authorization': 'Bearer ' + token, 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'},
                        params={'q': query.strip(), 'limit': '5', 'sort': 'newlyListed',
                                'filter': 'buyingOptions:{FIXED_PRICE}'}, allow_redirects=False) as response:
                    data = await response_json(response, 'SEARCH')
                result = normalize_search(data, self.environment)
                return {**base, **result, 'state': 'SEARCH_RESPONSE_VALIDATED', 'http_status': 200,
                        'production_access_verified': self.environment == 'production'}
        except AccessFailure as error:
            return {**base, **error.result}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            return {**base, 'state': 'REQUEST_FAILED', 'error_type': type(error).__name__}
