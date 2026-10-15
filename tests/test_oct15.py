import unittest
from app.registered_games import registered_identity, registered_title
from app.config import GAME_DATA, GAME_ROLES
from app.mtg_products import mtg_product_details
from app.price_policy import classify, explanation
class October15Test(unittest.TestCase):
    def test_final_fantasy(self):
        for title in ('Final Fantasy TCG Opus Booster Box','FFTCG Opus Booster Box'):
            self.assertEqual(registered_identity({'title':title}),'Final Fantasy TCG')
        for title in ('Final Fantasy VII PlayStation Video Game','Final Fantasy Tifa Figure','Final Fantasy MTG Play Booster Box'):
            self.assertIsNone(registered_identity({'title':title}))
        self.assertFalse(registered_title('Magic: The Gathering Final Fantasy Commander Deck'))
    def test_cookie_run(self):
        for title in ('CookieRun Braverse Booster Box','Cookie Run TCG Starter Deck','CookieRun: Braverse English Booster Pack'):
            self.assertEqual(registered_identity({'title':title}),'CookieRun: Braverse')
        self.assertIsNone(registered_identity({'title':'Cookie Run Plush Figure'}))
    def test_menu_entries(self):
        names={x[0] for x in GAME_DATA}
        for game in ('Final Fantasy TCG','CookieRun: Braverse'):
            self.assertIn(game,names);self.assertIn(game,GAME_ROLES)
    def test_screenshot_packaging(self):
        cases=[('MTG Star Trek™ -Set of 2- Scene Boxes','Scene Box Set'),('MTG Star Trek™ -Set of 4- Commander Decks [Collector Edition]','Commander Deck Set')]
        for title,kind in cases:
            self.assertEqual(mtg_product_details(title,'Single Card',['Singles']),('SEALED',kind))
    def test_single_kept(self):
        self.assertEqual(mtg_product_details('MTG Sol Ring Single Card from Commander Deck','Single Card'),('SINGLE','Single Card'))
        self.assertEqual(mtg_product_details('MTG Sol Ring #123 Near Mint','Single Card'),('SINGLE','Single Card'))
    def test_historical_drop_is_not_reference(self):
        for old,new in [('9.99','8.99'),('119.99','83.98'),('1299.95','849.99')]:
            event={'event_type':'PRICE_DROP','price':new,'old_price':old,'currency':'USD','region':'US','in_stock':True,'product_family':'GLOBAL_STANDARD'}
            self.assertEqual(classify(event),'PRICE_DROP')
            self.assertIn('NO_REFERENCE_EVIDENCE',explanation(event)['deal_blockers'])
    def test_verified_reference_promotes(self):
        e={'event_type':'PRICE_DROP','price':'8.99','old_price':'9.99','currency':'USD','region':'US','in_stock':True,'product_family':'GLOBAL_STANDARD',
           'reference_evidence':{'scope':'EXACT_PRODUCT','confidence':'HIGH','kind':'MSRP','source':'test','currency':'USD','region':'US','family':'GLOBAL_STANDARD','amount':'9.99'}}
        self.assertEqual(classify(e),'DEAL');self.assertEqual(explanation(e)['deal_blockers'],[])
        e['in_stock']=None;self.assertIn('STOCK_NOT_CONFIRMED',explanation(e)['deal_blockers'])
if __name__=='__main__':unittest.main()
