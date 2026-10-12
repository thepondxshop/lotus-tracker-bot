import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app import operations_status as ops
from app.retailers import plaza_support as plaza


def test_status_and_health_append_without_mass_mentions(monkeypatch):
    monkeypatch.setenv('CHANNEL_BOT_STATUS','123')
    monkeypatch.setenv('CHANNEL_MONITOR_HEALTH','124')
    async def check():
        message=SimpleNamespace(edit=AsyncMock())
        channel=SimpleNamespace(send=AsyncMock(return_value=message))
        publisher=ops.Publisher(SimpleNamespace(get_channel=lambda _:channel))
        for kind in ('status','health'):
            assert await publisher.publish(kind,'first')
            assert await publisher.publish(kind,'second')
        assert channel.send.await_count==4
        message.edit.assert_not_awaited()
        assert channel.send.call_args.kwargs['allowed_mentions'].everyone is False
    asyncio.run(check())


def test_recent_errors_exclude_stale_and_secret_headers():
    now=datetime.now(timezone.utc)
    rows=[{'store':'Recent','store_id':1,'last_rate_limit':{'at':now.isoformat(),'purpose':'GENERAL_HEAD','headers':{'secret':'never print'}}},
          {'store':'Old','last_rate_limit':{'at':(now-timedelta(hours=1)).isoformat(),'purpose':'OLD'}}]
    text=ops.recent_throttles({'store_runtime':rows},now)
    assert 'Recent' in text and 'GENERAL\\_HEAD' in text
    assert 'Old' not in text and 'never print' not in text


def markup(price='1234', availability='https://schema.org/PreOrder'):
    return f'''<div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Holo Beat HB-SD01 Start Deck</h1>
    <meta itemprop="image" content="https://example.org/image.jpg">
    <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
    <meta itemprop="url" content="https://www.plazajapan.com/4904810069614/">
    <meta itemprop="price" content="{price}"><meta itemprop="priceCurrency" content="JPY">
    <meta itemprop="availability" content="{availability}"></div></div>'''

URL='https://www.plazajapan.com/4904810069614/'

def test_microdata_identity_and_no_invented_stock():
    data=plaza.schema(markup(),URL)
    assert data['offers']['priceCurrency']=='JPY'
    assert data['offers']['availability'].endswith('PreOrder')
    assert plaza.schema(markup(),'https://www.plazajapan.com/4904810069621/') is None
    assert plaza.schema(markup()+markup(),URL) is None
    assert plaza.schema(markup('nan'),URL) is None
    assert plaza.schema(markup(availability=''),URL)['offers']['availability']==''


def test_category_excludes_sidebar_and_foreign_next():
    html=f'''<ul class="productGrid" data-product-type="new"><a href="/1111111111111/">train</a></ul>
    <ul class="productGrid productGrid--maxCol3"><a href="{URL}">deck</a></ul>
    <link rel="next" href="https://evil.example/other/?page=2">'''
    assert plaza.category_links(html,'https://www.plazajapan.com/toys/trading-cards/other/')==([URL],None)


def test_plaza_normalization_uses_offer_and_game_identity():
    from app.retailers.bigcommerce_adapter import BigCommerceAdapter, product_schema
    adapter=BigCommerceAdapter(domain='www.plazajapan.com',region='JP',store_name='Plaza Japan')
    html=markup()
    p=adapter.normalize_product({'url':URL,'html':html,'schema':product_schema(html,URL)})
    assert p.game=='Horo Beat' and p.product_family=='JP'
    assert p.product_category=='SEALED' and p.product_type=='Starter Deck'
    assert p.price==1234 and p.currency=='JPY'
    assert p.platform_data['structured_data']=='HTML_MICRODATA_PRODUCT'
    assert p.platform_data['availability_source']=='HTML_MICRODATA_OFFER_AVAILABILITY'


def test_plaza_language_is_not_assumed_from_ui_or_region():
    from app.retailers.bigcommerce_adapter import BigCommerceAdapter, product_schema
    adapter=BigCommerceAdapter(domain='www.plazajapan.com',region='JP',store_name='Plaza Japan')
    html=markup().replace('Holo Beat HB-SD01 Start Deck','Pokemon Booster Box')
    p=adapter.normalize_product({'url':URL,'html':html,'schema':product_schema(html,URL)})
    assert p.product_family=='UNKNOWN'


def test_plaza_discovery_rotates_and_caps_requests():
    async def check():
        plaza._STATE.clear()
        html='<ul class="productGrid">'+''.join(f'<a href="/{4904810069600+i}/">product</a>' for i in range(20))+'</ul>'
        adapter=SimpleNamespace(domain='www.plazajapan.com',max_product_pages=80,diagnostics={},_get=AsyncMock(return_value=html))
        first=await plaza.discover(adapter,None)
        assert len(first)==12
        for _ in range(len(plaza.CATEGORIES)-1):await plaza.discover(adapter,None)
        second=await plaza.discover(adapter,None)
        assert len(second)==8 and not set(first)&set(second)
    asyncio.run(check())
