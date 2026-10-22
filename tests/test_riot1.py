import copy,json,unittest,os
from datetime import datetime,timezone,timedelta
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
from app import riot_public as r
from app.riot_news import change,observe,send_notice

def news(title='Riftbound drawing',body='Registration goes live on October 27 at 9:00 AM PT.'):
    return {'props':{'pageProps':{'page':{'locale':'en-us','url':r.FAQ,'blades':[
        {'type':'articleMasthead','title':title,'publishDate':'2026-10-21T16:00:00Z'},
        {'type':'articleRichText','richText':{'body':'<p>Official product details.</p>'}},
        {'type':'articleRichTextAccordion','groups':[{'label':'Schedule','content':{'body':body}}]},
        {'type':'relatedArticles','items':[{'title':'Another product','body':'$9999','action':{'type':'weblink','payload':{'url':r.NEWS+'other/'}}}]}]}}}}
def html(data):return '<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script>'
def product():return dict(id='810155273323',slug='riftbound-proving-grounds',title='Riftbound Proving Grounds',ip={'slug':'riftbound'},price={'amount':39.99,'currencyCode':'USD'},availability='inStock',isPreorder=False,requiresLogin=True,assets=[])
def merch(rows):
    data=json.dumps({'id':'product-listing-grid','initialProducts':rows})
    return '<script>self.__next_f.push('+json.dumps([1,'7:'+data+'\n'])+')</script>'

class NewsTests(unittest.TestCase):
    def test_accordion_extracted_no_stock(self):
        row=r.article(html(news()),r.FAQ)
        self.assertIn('October 27',row['schedule_text']);self.assertFalse(row['stock_verified'])
        self.assertEqual(row['kind'],'DRAWING_ANNOUNCEMENT')
    def test_related_change_ignored(self):
        a=news();b=copy.deepcopy(a);b['props']['pageProps']['page']['blades'][-1]['items'][0]['title']='changed recommendation'
        self.assertEqual(r.article(html(a),r.FAQ)['fingerprint'],r.article(html(b),r.FAQ)['fingerprint'])
    def test_schedule_change_detected(self):
        self.assertNotEqual(r.article(html(news()),r.FAQ)['fingerprint'],r.article(html(news(body='Registration goes live November 1')),r.FAQ)['fingerprint'])
    def test_wrong_identity_and_locale(self):
        for k,v in [('url',r.NEWS+'other/'),('locale','fr-fr')]:
            a=news();a['props']['pageProps']['page'][k]=v
            with self.assertRaises(ValueError):r.article(html(a),r.FAQ)
    def test_missing_schema(self):
        with self.assertRaises(ValueError):r.article('<html>Access denied</html>',r.FAQ)
    def test_index_links_only_official(self):
        a=news();items=a['props']['pageProps']['page']['blades'][-1]['items']
        items.append({'action':{'type':'weblink','payload':{'url':'https://evil.example/x'}}})
        self.assertEqual(r.article_links(html(a)),[r.NEWS+'other/'])
    def test_urls(self):
        for url in ('http://playriftbound.com/en-us/news/announcements/a/','https://playriftbound.com.evil.test/en-us/news/announcements/a/','https://user@playriftbound.com/en-us/news/announcements/a/',r.FAQ+'?token=x','https://merch.riotgames.com/en-us/cart/'):
            self.assertFalse(r.allowed_url(url))
    def test_baseline_unchanged_and_old(self):
        row=r.article(html(news()),r.FAQ);now=datetime(2026,10,22,tzinfo=timezone.utc)
        self.assertIsNone(change(None,row,False,now));self.assertIsNone(change(row['fingerprint'],row,True,now))
        self.assertEqual(change(None,row,True,now),'NEW_OFFICIAL_ANNOUNCEMENT')
        self.assertIsNone(change(None,row,True,now+timedelta(days=8)))
        self.assertEqual(change('old',row,True,now),'ANNOUNCEMENT_UPDATED')
    def test_future_and_missing_timestamp(self):
        row=r.article(html(news()),r.FAQ)
        self.assertIsNone(change(None,row,True,datetime(2026,10,20,tzinfo=timezone.utc)))
        row['published_at']=None;self.assertIsNone(change(None,row,True))

class MerchTests(unittest.TestCase):
    def test_observed_schema_price_not_stock(self):
        row=r.merch_rows(merch([product()]))[0]
        self.assertEqual(row['price'],'39.99');self.assertEqual(row['reported_availability'],'inStock');self.assertFalse(row['stock_verified'])
    def test_duplicate_and_wrong_currency(self):
        with self.assertRaises(ValueError):r.merch_rows(merch([product(),product()]))
        p=product();p['price']['currencyCode']='EUR'
        with self.assertRaises(ValueError):r.merch_rows(merch([p]))
    def test_invalid_prices(self):
        for value in ('NaN',True,0,-1,'Infinity',None):
            p=product();p['price']['amount']=value
            with self.assertRaises(ValueError):r.merch_rows(merch([p]))
    def test_empty_or_bad_schema_not_sold_out(self):
        for body in ('<html>blocked</html>',merch([])):
            with self.assertRaises(ValueError):r.merch_rows(body)
    def test_other_game_and_slug_rejected(self):
        p=product();p['ip']['slug']='valorant'
        with self.assertRaises(ValueError):r.merch_rows(merch([p]))
        p=product();p['slug']='../../cart'
        with self.assertRaises(ValueError):r.merch_rows(merch([p]))
    def test_split_flight_segments(self):
        data='7:'+json.dumps({'id':'product-listing-grid','initialProducts':[product()]})+'\n';n=len(data)//2
        body=''.join('<script>self.__next_f.push('+json.dumps([1,s])+')</script>' for s in (data[:n],data[n:]))
        self.assertEqual(len(r.merch_rows(body)),1)

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_to_login_blocked(self):
        class Response:
            status=302;headers={'Location':'https://xsso.riotgames.com/login'}
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        session=SimpleNamespace(get=lambda *a,**k:Response())
        with self.assertRaisesRegex(ValueError,'REDIRECT_BLOCKED'):await r.fetch(session,r.FAQ)
    async def test_xp_privacy_uses_invoking_member_only(self):
        from app.member_xp import MemberXP
        store=SimpleNamespace(privacy=AsyncMock());cog=MemberXP(None,store,True)
        i=SimpleNamespace(guild_id=10,user=SimpleNamespace(id=20),response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        await cog.xpprivacy.callback(cog,i,SimpleNamespace(value='out'))
        store.privacy.assert_awaited_once_with(10,20,False)
    async def test_delivery_label_no_mentions_or_cart(self):
        channel=SimpleNamespace(send=AsyncMock())
        await send_notice(channel,r.article(html(news()),r.FAQ),'NEW_OFFICIAL_ANNOUNCEMENT')
        args=channel.send.call_args.kwargs
        self.assertIn('not an in-stock',args['embed'].description)
        self.assertFalse(args['allowed_mentions'].everyone);self.assertNotIn('view',args)
    async def test_shadow_never_reserves_delivery(self):
        conn=SimpleNamespace(scalar=AsyncMock(return_value='old'),execute=AsyncMock(),commit=AsyncMock())
        event,key=await observe(conn,'SHADOW',r.article(html(news()),r.FAQ),True)
        self.assertEqual(event,'ANNOUNCEMENT_UPDATED');self.assertIsNone(key)
        self.assertNotIn('lotus_riot_news_delivery',str(conn.execute.call_args_list))
    async def test_live_reservation_conflict_suppresses(self):
        conn=SimpleNamespace(scalar=AsyncMock(side_effect=['old',None]),execute=AsyncMock(),commit=AsyncMock())
        event,key=await observe(conn,'LIVE',r.article(html(news()),r.FAQ),True)
        self.assertIsNone(event);conn.commit.assert_awaited_once()
    async def test_actual_adapter_keeps_unknown_stock(self):
        os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1:1/test')
        from app.major_retailers import build_major_retailer_adapter
        from app.major_retailers.pipeline import _candidate_events
        adapter=build_major_retailer_adapter('riot_merch')
        with patch('app.major_retailers.riot_merch.fetch',AsyncMock(return_value=merch([product()]))):items=await adapter.discover_products()
        item=items[0].to_normalized_dict(adapter.capabilities)
        self.assertFalse(item['platform_data']['availability_known']);self.assertIsNone(item['variant_id'])
        self.assertEqual(_candidate_events(old=None,item=item,baseline_seed=False,now=datetime.now(timezone.utc)),[{'event_type':'PAGE_LIVE'}])
        self.assertEqual(items[0].validate(adapter.capabilities),[])
    async def test_http_retry_after_no_retry(self):
        class Response:
            status=429;headers={'Retry-After':'7200'}
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        session=SimpleNamespace(get=lambda *a,**k:Response())
        with self.assertRaises(r.SourceError) as caught:await r.fetch(session,r.FAQ)
        self.assertEqual(caught.exception.wait,7200)
        from app.major_retailers.retry_policy import remaining
        now=datetime.now(timezone.utc)
        self.assertEqual(remaining(dict(last_error=str(caught.exception),last_scan_at=now,consecutive_failures=1),now),7200)

class PrivacyTests(unittest.TestCase):
    def test_opted_out_does_not_award(self):
        from app.member_xp import award_amount
        self.assertEqual(award_amount({'enabled':False},'hash',999,datetime.now(timezone.utc)),0)

if __name__=='__main__':unittest.main()
