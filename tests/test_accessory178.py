import unittest
from datetime import datetime, timezone, timedelta
from app.accessory_routes import normalize_accessory_event, accessory_destination, accessory_event
from app.case_identity import shipping_case_event
from app.member_xp import award_amount

class Regression178Tests(unittest.TestCase):
    def test_reported_starter_display(self):
        for title in ('Gundam Card Game ST14 Starter Deck Box Heavy Dominion', 'Gundam ST-14 Starter Deck Display Heavy Dominion'):
            original = dict(product_name=title, product_type='Accessory', product_category='ACCESSORY', reference_evidence={'stale':True}, region='AU')
            result = normalize_accessory_event(original)
            self.assertEqual(result['product_type'], 'Starter Deck Display')
            self.assertEqual(result['product_category'], 'SEALED')
            self.assertIsNone(accessory_destination(result))
            self.assertFalse(shipping_case_event(result))
            self.assertNotIn('reference_evidence',result)
            self.assertIn('reference_evidence',original)
    def test_storage_stays_accessory(self):
        for title in ('Gundam ST14 Deck Box', 'Empty Gundam ST14 Starter Deck Box', 'Acrylic holder for Gundam ST14 Starter Deck Box'):
            self.assertTrue(accessory_event(dict(product_name=title,product_type='Accessory')))
    def test_no_daily_cap(self):
        now=datetime.now(timezone.utc)
        row=dict(enabled=True,last_message_id=1,last_awarded_at=now-timedelta(seconds=60),last_content_hash='old',daily_xp=1000000,day=now.date())
        self.assertIn(award_amount(row,'different',2,now),range(10,21))
        row['last_awarded_at']=now-timedelta(seconds=59)
        self.assertEqual(award_amount(row,'different',2,now),0)

if __name__=='__main__':unittest.main()
