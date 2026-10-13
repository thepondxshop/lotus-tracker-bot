"""Focused regressions for DEL1, SQ2, CAL5, READY1 and MARKET1."""
import asyncio
import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


calendar = load('all5_calendar', ROOT / 'app/release_catalog/calendar_identity.py')
square = load('all5_square', ROOT / 'app/retailers/square_weebly_adapter.py')
delivery = load('all5_delivery', ROOT / 'app/dispatch_observability.py')
readiness = load('all5_readiness', ROOT / 'lotus_readiness_check.py')
market_check = load('all5_market_check', ROOT / 'lotus_marketplace_check.py')
from app.marketplaces.foundation import amount, normalize_listing, deduplicate_listings, landed_cost, COST_COMPONENTS


def row(id, **kw):
    result = dict(id=id, guild_id=1, game='Azuki TCG', title='Azuki TCG Fractured Domains Booster Box',
                  product_format='BOX', language='English', region='US', set_code='AZK02',
                  period={'start': '2026-11-20', 'end': '2026-11-20', 'precision': 'DAY'},
                  image_url=None, image_kind='PLACEHOLDER', source_url=f'https://source.example/{id}',
                  announceable=True, notes=[])
    result.update(kw)
    return result


def test_calendar_merges_duplicates_even_with_other_language_and_date():
    entries = [row(1), row(2, title='Azuki TCG Fractured Domains Booster Pack Display', image_url='https://source.example/box.png', image_kind='PUBLISHER'),
               row(3, language='Japanese', region='JP'), row(4, period={'start': '2026-12-01'})]
    before = copy.deepcopy(entries)
    merged = calendar.consolidate(entries)
    assert len(merged) == 3
    illustrated = next(r for r in merged if r.get('calendar_members'))
    assert {m['id'] for m in illustrated['calendar_members']} == {1, 2}
    assert illustrated['image_url'].endswith('box.png')
    assert len(illustrated['calendar_source_urls']) == 2
    assert entries == before


@pytest.mark.parametrize('changes', [dict(language='UNKNOWN'), dict(region='UNKNOWN'), dict(reported_packs_per_box=None)])
def test_ambiguous_unknown_cannot_bridge_editions(changes):
    if 'language' in changes:
        entries = [row(1), row(2, language='Japanese'), row(3, **changes)]
    elif 'region' in changes:
        entries = [row(1), row(2, region='JP'), row(3, **changes)]
    else:
        entries = [row(1, reported_packs_per_box=24), row(2, reported_packs_per_box=12), row(3, **changes)]
    assert len(calendar.consolidate(entries)) == 3


def test_case_stays_separate_and_display_box_alias_merges():
    result = calendar.consolidate([row(1), row(2, title='Azuki TCG Fractured Domains Booster Display Box'), row(3, product_format='CASE')])
    assert len(result) == 2
    assert any(r['product_format'] == 'CASE' for r in result)


def test_relic_artwork_and_rumor_do_not_promote_confirmation():
    title = 'Azuki TCG Fractured Domains Relic Hunter Box'
    result = calendar.consolidate([row(1, title=title, announceable=False, image_url='https://source.example/box.png', image_kind='PUBLISHER'), row(2, title=title)])
    assert len(result) == 1 and result[0]['id'] == 2 and result[0]['announceable']
    assert result[0]['image_url']


@pytest.mark.parametrize('identifier', ['12345', 'TRIMM6PWZ6ZWZ5V54DWNWV56'])
def test_square_legacy_and_modern_urls(identifier):
    url = 'https://www.talonsong.net/product/riftbound/' + identifier + '?ref=store'
    assert square.is_product_url(url)
    assert square.parse_product_id_from_url(url) == identifier


@pytest.mark.parametrize('path', ['/shop/riftbound', '/product/riftbound/123abc', '/product/riftbound/short', '/product/riftbound/'])
def test_square_rejects_non_product_paths(path):
    assert not square.is_product_url('https://example.com' + path)
    assert square.parse_product_id_from_url('https://example.com' + path) is None


def test_square_og_only_page_is_discovery_not_stock():
    url = 'https://www.talonsong.net/product/riftbound-radiance-booster-box-pre-order-/TRIMM6PWZ6ZWZ5V54DWNWV56'
    html = '''<html><head><meta property="og:title" content="Riftbound: Radiance Booster Box (Pre Order) | TalonSong Gaming LLC"><meta property="og:url" content="%s"><meta property="og:image" content="https://example.com/box.png"></head><body></body></html>''' % url
    adapter = square.SquareWeeblyAdapter(domain='www.talonsong.net', store_name='TalonSong')
    product = adapter.normalize_product({'url': url, 'html': html})
    assert product.external_id == 'TRIMM6PWZ6ZWZ5V54DWNWV56'
    assert product.game == 'Riftbound'
    assert product.price is None
    assert product.platform_data['availability_known'] is False
    assert product.product_state == 'PAGE_LIVE'


def test_optional_fx_deadline_and_cancellation():
    async def run():
        assert await delivery.optional_conversion(asyncio.sleep(.1, result=5), timeout=.001) is None
        assert await delivery.optional_conversion(asyncio.sleep(0, result=5)) == 5
        async def cancelled():
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await delivery.optional_conversion(cancelled())
    asyncio.run(run())


def test_dispatch_timeout_phase_and_primary_confirmation(capsys):
    async def dispatch():
        delivery.mark_phase('MEMBER_ELIGIBILITY')
        message = SimpleNamespace(id=123, created_at=datetime(2026, 10, 12, 12, 30, tzinfo=timezone.utc))
        delivery.primary_confirmed(message, {'store_name': 'Example'})
        delivery.mark_phase('DELIVERY_PERSISTENCE')
        await asyncio.sleep(.1)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(delivery.traced_dispatch(dispatch(), {}, timeout=.005))
    output = capsys.readouterr().out
    assert 'PRIMARY_CONFIRMED' in output and 'DELIVERY_PERSISTENCE' in output
    assert '08:30:00 AM EDT' in output and '"automatic_replay": false' in output
    assert delivery._state.get() is None


def test_dispatch_success_no_timeout(capsys):
    assert asyncio.run(delivery.traced_dispatch(asyncio.sleep(0, result=True), {}, timeout=1)) is True
    assert 'TIMEOUT' not in capsys.readouterr().out


def listing(**kw):
    result = dict(marketplace='ebay', listing_id='abc', title='Horo Beat box', url='https://www.ebay.com/itm/abc', price='12.34', currency='USD', language='Japanese')
    result.update(kw)
    return result


def test_market_dedup_and_tiers_do_not_infer_stock_or_sales():
    rows = deduplicate_listings([listing(), listing(), listing(listing_id='def', language='Chinese'), listing(marketplace='buyee_jp')])
    assert len(rows) == 3
    assert rows[-1]['minimum_tier'] == 'Premium+'
    assert all(r['stock_state'] == 'UNKNOWN' and r['price_basis'] == 'ASKING' for r in rows)


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', True, None, 'bad'])
def test_bad_prices(value):
    assert amount(value) is None
    with pytest.raises(ValueError):
        normalize_listing(listing(price=value))


def test_landed_cost_does_not_treat_missing_fees_as_zero_or_mix_currency():
    data = {key: {'amount': '0', 'currency': 'USD'} for key in COST_COMPONENTS}
    data['item']['amount'] = '12.34'
    assert landed_cost(data, 'USD')['estimated_total'] == '12.34'
    del data['duty']
    data['international_shipping']['currency'] = 'JPY'
    result = landed_cost(data, 'USD')
    assert result['estimated_total'] is None
    assert set(result['missing']) == {'duty', 'international_shipping'}


def test_ebay_response_shape():
    assert market_check.normalize_ebay_search({'total': 0})['accepted'] == 0
    with pytest.raises(ValueError):
        market_check.normalize_ebay_search({})
    result = market_check.normalize_ebay_search({'itemSummaries': [None, {'itemId': '1', 'title': 'Box', 'price': {'value': '5', 'currency': 'USD'}, 'itemWebUrl': 'https://www.ebay.com/itm/1'}]})
    assert result['accepted'] == 1 and result['rejected'] == 1
    assert not result['sold_prices_available']


def test_readiness_never_executes_pipeline_code(tmp_path, monkeypatch):
    path = tmp_path / 'app/major_retailers'
    path.mkdir(parents=True)
    (path / 'pipeline.py').write_text("raise RuntimeError('must not import')\nPRODUCTION_BLOCKS = {'target':'OFFICIAL_SOURCE_REQUIRED'}\nVALIDATION_PASSES_REQUIRED = 2\n")
    monkeypatch.setenv('BESTBUY_API_KEY', 'must-not-print-this')
    result = readiness.local_report(tmp_path)
    assert result['bestbuy_api_key_present']
    assert 'must-not-print-this' not in json.dumps(result)
    assert result['production_blocks']['target'] == 'OFFICIAL_SOURCE_REQUIRED'


def test_ebay_missing_token_never_requests(monkeypatch):
    monkeypatch.delenv('EBAY_SANDBOX_APPLICATION_TOKEN', raising=False)
    result = asyncio.run(market_check.sandbox_probe('Horo Beat'))
    assert result == {'state': 'MISSING_SANDBOX_TOKEN', 'request_sent': False}


def test_ebay_429_one_sandbox_request_no_retry(monkeypatch):
    import aiohttp
    calls = []
    class Response:
        status = 429
        headers = {'Retry-After': '60'}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Session:
        def __init__(self, **kwargs):
            assert kwargs['headers']['Authorization'] == 'Bearer sandbox-secret'
            assert kwargs['trust_env'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()
    monkeypatch.setenv('EBAY_SANDBOX_APPLICATION_TOKEN', 'sandbox-secret')
    monkeypatch.setattr(aiohttp, 'ClientSession', Session)
    result = asyncio.run(market_check.sandbox_probe('Horo Beat'))
    assert len(calls) == 1 and calls[0][0].startswith('https://api.sandbox.ebay.com/')
    assert calls[0][1]['allow_redirects'] is False
    assert result['retries'] == 0 and result['retry_after'] == '60'
    assert result['alerts_sent'] == 0 and not result['production_access_verified']
    assert 'sandbox-secret' not in json.dumps(result)
