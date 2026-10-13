import asyncio
import json
import os
import unittest
from unittest.mock import patch
from app.marketplaces.ebay import EbayPreview, normalize_search, configuration


class Response:
    def __init__(self, data, status=200, headers=None):
        self.data = data
        self.status = status
        self.headers = headers or {}
        self.content = self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def iter_chunked(self, size):
        yield self.data if isinstance(self.data, bytes) else json.dumps(self.data).encode()


class Session:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)
    def post(self, url, **kwargs): return self.request('POST', url, **kwargs)
    def get(self, url, **kwargs): return self.request('GET', url, **kwargs)


class Tests(unittest.TestCase):
    def run_search(self, responses, env=None, environment='sandbox', query='Horo Beat'):
        session = Session(responses)
        with patch.dict(os.environ, env or {}, clear=True), patch('app.marketplaces.ebay.aiohttp.ClientSession', return_value=session):
            result = asyncio.run(EbayPreview(environment).search(query))
        return result, session.calls

    def test_missing_credentials_no_requests(self):
        result, calls = self.run_search([])
        self.assertEqual(result['state'], 'MISSING_CREDENTIALS')
        self.assertEqual(calls, [])

    def test_invalid_query_no_requests(self):
        result, calls = self.run_search([], query=' ')
        self.assertEqual(result['state'], 'INVALID_QUERY')
        self.assertEqual(calls, [])

    def test_oauth_and_search_no_secret_output(self):
        result, calls = self.run_search([Response({'access_token': 'SECRET-TOKEN', 'expires_in': 7200}), Response({'total': 0})],
            {'EBAY_SANDBOX_CLIENT_ID': 'CLIENT-ID', 'EBAY_SANDBOX_CLIENT_SECRET': 'SECRET-PASSWORD'})
        self.assertEqual([c[0] for c in calls], ['POST', 'GET'])
        self.assertTrue(all(c[1].startswith('https://api.sandbox.ebay.com/') for c in calls))
        self.assertTrue(all(c[2]['allow_redirects'] is False for c in calls))
        self.assertEqual(calls[0][2]['data']['grant_type'], 'client_credentials')
        self.assertEqual(calls[1][2]['headers']['Authorization'], 'Bearer SECRET-TOKEN')
        self.assertEqual(calls[1][2]['params']['limit'], '5')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertFalse(result['production_access_verified'])
        self.assertEqual(result['accepted'], 0)

    def test_environment_isolation(self):
        result, calls = self.run_search([], {'EBAY_SANDBOX_APPLICATION_TOKEN': 'sandbox-token'}, environment='production')
        self.assertEqual(result['state'], 'MISSING_CREDENTIALS')
        self.assertFalse(calls)

    def test_production_is_explicit_and_still_no_alerts(self):
        result, calls = self.run_search([Response({'total': 0})], {'EBAY_PRODUCTION_APPLICATION_TOKEN': 'prod-token'}, environment='production')
        self.assertTrue(result['production_access_verified'])
        self.assertEqual(result['alerts_sent'], 0)
        self.assertFalse(result['live_pipeline_enabled'])
        self.assertTrue(calls[0][1].startswith('https://api.ebay.com/'))

    def test_search_429_no_retry(self):
        result, calls = self.run_search([Response({}, 429, {'Retry-After': '60'})], {'EBAY_SANDBOX_APPLICATION_TOKEN': 'token'})
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['state'], 'RATE_LIMITED')
        self.assertEqual(result['retry_after'], '60')

    def test_auth_denied_never_searches(self):
        result, calls = self.run_search([Response({}, 403)], {'EBAY_SANDBOX_CLIENT_ID': 'a', 'EBAY_SANDBOX_CLIENT_SECRET': 'b'})
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['phase'], 'AUTH')
        self.assertEqual(result['state'], 'AUTH_OR_ACCESS_REQUIRED')

    def test_redirect_not_followed(self):
        result, calls = self.run_search([Response({}, 302)], {'EBAY_SANDBOX_APPLICATION_TOKEN': 'token'})
        self.assertEqual(result['state'], 'HTTP_ERROR')
        self.assertEqual(len(calls), 1)

    def test_bad_or_oversized_json(self):
        for body, expected in [(b'<html>', 'INVALID_JSON'), (b'x' * 1048577, 'RESPONSE_TOO_LARGE'), ([], 'INVALID_RESPONSE')]:
            result, calls = self.run_search([Response(body)], {'EBAY_SANDBOX_APPLICATION_TOKEN': 'token'})
            self.assertEqual(result['state'], expected)

    def test_invalid_token_response(self):
        result, calls = self.run_search([Response({'access_token': 'secret', 'expires_in': 'NaN'})], {'EBAY_SANDBOX_CLIENT_ID': 'a', 'EBAY_SANDBOX_CLIENT_SECRET': 'b'})
        self.assertEqual(result['state'], 'INVALID_TOKEN_RESPONSE')
        self.assertEqual(len(calls), 1)

    def test_cache_reuses_token_until_expiry(self):
        async def run():
            client = EbayPreview()
            session = Session([Response({'access_token': 'one', 'expires_in': 7200}), Response({'access_token': 'two', 'expires_in': 7200})])
            with patch.dict(os.environ, {'EBAY_SANDBOX_CLIENT_ID': 'a', 'EBAY_SANDBOX_CLIENT_SECRET': 'b'}, clear=True):
                self.assertEqual(await client.token(session), 'one')
                self.assertEqual(await client.token(session), 'one')
                self.assertEqual(len(session.calls), 1)
                client._expires = 0
                self.assertEqual(await client.token(session), 'two')
        asyncio.run(run())

    def test_config_never_exposes_secrets(self):
        with patch.dict(os.environ, {'EBAY_SANDBOX_CLIENT_SECRET': 'TOPSECRET'}, clear=True):
            self.assertNotIn('TOPSECRET', json.dumps(configuration('sandbox')))

    def test_candidates_dedup_and_unknown_game_stock(self):
        row = {'itemId': 'v1|123|0', 'title': 'Horo Beat Japanese booster box', 'itemWebUrl': 'https://www.ebay.com/itm/123', 'price': {'value': '25', 'currency': 'USD'}}
        result = normalize_search({'itemSummaries': [row, row, None]}, 'sandbox')
        self.assertEqual(result['accepted'], 1)
        self.assertEqual(result['rejected'], 1)
        item = result['candidates'][0]
        self.assertTrue(item['review_required'])
        self.assertTrue(item['sandbox'])
        self.assertEqual(item['stock_state'], 'UNKNOWN')
        self.assertEqual(item['game'], 'UNKNOWN')
        self.assertFalse(result['sold_prices_available'])


if __name__ == '__main__': unittest.main()
