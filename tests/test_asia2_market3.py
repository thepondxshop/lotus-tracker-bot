import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from app.marketplaces.review import review_rows
from app.retailers.category_pagination import next_category_page, rotating_selection, _CURSORS
from app.store_currency_fallback import currency_for_store
from app.retailers import prestashop_adapter as ps

class ChangesTest(unittest.TestCase):
    def test_next_page(self):
        u='https://example.com/en/pokemon'
        self.assertEqual(next_category_page('<a rel="next" href="?page=2">Next</a>',u),u+'?page=2')
        for href in ['https://other.com/en/pokemon?page=2','?page=1','?page=3','?page=2&sort=price','/other?page=2']:
            self.assertIsNone(next_category_page('<a rel="next" href="'+href+'">Next</a>',u))
        self.assertIsNone(next_category_page('<a rel="next" href="?page=21">Next</a>',u+'?page=20'))

    def test_discovery_fetches_second_page(self):
        adapter=ps.PrestaShopAdapter(domain='example.com')
        adapter.request_delay=0
        seen=[]
        async def get(session,url):
            seen.append(url)
            if '?page=2' in url:
                return '<a href="/en/123-second-pokemon.html">Product</a>',url
            return '<a rel="next" href="?page=2">Next</a>',url
        adapter._get=get
        with patch.object(ps,'HTML_DISCOVERY_PATHS',['/en/pokemon']):
            result=asyncio.run(adapter._discover_html(None))
        self.assertIn('https://example.com/en/pokemon?page=2',seen)
        self.assertIn('https://example.com/en/123-second-pokemon.html',result)
        self.assertNotIn('https://example.com/en/123-second-pokemon.html?page=2',seen)
        self.assertLessEqual(len(seen),3)

    def test_rotation(self):
        _CURSORS.clear()
        self.assertEqual(rotating_selection('meccha-japan.com',['a','b','c'],2),['a','b'])
        self.assertEqual(rotating_selection('meccha-japan.com',['a','b','c'],2),['c','a'])
        self.assertEqual(rotating_selection('other.com',['a','b','c'],2),['a','b'])

    def test_currency(self):
        with patch.dict(os.environ,SHOPIFY_CURRENCY_FALLBACKS='{"cardkingdom.co.kr":"USD"}'):
            self.assertEqual(currency_for_store('www.cardkingdom.co.kr','KRW'),'USD')
            self.assertEqual(currency_for_store('other.com','JPY'),'JPY')
        for value in ['invalid','[]','{"cardkingdom.co.kr":123}','{"cardkingdom.co.kr":"bad"}']:
            with patch.dict(os.environ,SHOPIFY_CURRENCY_FALLBACKS=value):
                self.assertEqual(currency_for_store('cardkingdom.co.kr','KRW'),'KRW')

    def test_marketplace_review(self):
        now=datetime(2026,10,13,12,tzinfo=timezone.utc)
        base=dict(marketplace='buyee_jp',title='Test fixture',price='1000',currency='JPY',observed_at='2026-10-13T11:59:00Z')
        rows=[dict(base,url='https://buyee.jp/item/mercari/m123?x=1'),dict(base,url='https://buyee.jp/mercari/item/m123',observed_at='2026-10-13T11:58:00Z'),dict(base,url='https://buyee.jp/item/yahoo/auction/m123',cost_components={})]
        result=review_rows(rows,now)
        self.assertEqual(result['accepted'],2)
        self.assertFalse(result['live_pipeline_enabled'])
        self.assertEqual(result['alerts_sent'],0)
        self.assertEqual(result['review_candidates'][0]['observed_at'],'2026-10-13T11:59:00+00:00')
        self.assertFalse(result['review_candidates'][1]['landed_cost']['complete'])
        for row in result['review_candidates']:
            self.assertFalse(row['automatic_alert_eligible'])
            self.assertEqual(row['stock_state'],'UNKNOWN')
        bad=[dict(base,url='https://evil.com/item/mercari/m123'),dict(base,url='https://user@buyee.jp/item/mercari/m123'),dict(base,url='https://buyee.jp/item/mercari/m123',observed_at='2026-10-13T12:01:00Z'),dict(base,url='https://buyee.jp/item/mercari/m123',observed_at='2026-10-13T11:59:00')]
        self.assertEqual(len(review_rows(bad,now)['rejected']),4)
        stale=review_rows([dict(base,url='https://buyee.jp/item/mercari/m123',observed_at='2026-10-13T10:00:00Z')],now)
        self.assertTrue(stale['review_candidates'][0]['stale'])
        us=review_rows([dict(base,marketplace='mercari_us',url='https://www.mercari.com/us/item/m123/',currency='USD')],now)
        self.assertEqual(us['review_candidates'][0]['minimum_tier'],'Premium')

if __name__=='__main__': unittest.main()
