import json,unittest
from datetime import datetime,timezone,timedelta
from app.distributor_catalog import parse,SEEDS
from app.distributor_units import unit_valid
from app.distributor_references import install,matched,status
from app.price_policy import classify,qualifying_references

class UnitTests(unittest.TestCase):
    def tearDown(self):install([],[])
    def product(self,label=None):
        return dict(sku='BJP2873817',name='ONE PIECE TCG STARTER DECK ST-37',link='pc_product_detail.asp?key=test',release_date_display=(datetime.now(timezone.utc)+timedelta(days=20)).strftime('%m/%d/%Y'),uomPrice=[{'isDefault':True,'SRetailPrice':101.94,'UomName':label,'description':'Each'}],searchfields={'c':{'label':'Configurations','value':'6 decks / 8 displays'}})
    def parse(self,p):return parse(SEEDS['gts'],'var productResults = '+json.dumps({'products':[p]}))[0][0]
    def event(self):return dict(product_name='One Piece TCG Starter Deck ST-37',product_type='Starter Deck',product_family='GLOBAL_STANDARD',game='One Piece',region='US',currency='USD',product_url='https://example.com/st37',event_type='DEAL',price='27.99',in_stock=True)
    def ref(self):
        now=datetime.now(timezone.utc)
        return dict(kind='MSRP',scope='EXACT_PRODUCT',confidence='HIGH',source='https://gtsdistribution.com/pc_product_detail.asp?key=test',amount='101.94',currency='USD',family='GLOBAL_STANDARD',region='US',release_date=(now+timedelta(days=20)).date().isoformat(),release_date_source='https://gtsdistribution.com/pc_product_detail.asp?key=test',release_date_verified=True,expires_at=(now+timedelta(days=2)).isoformat())
    def test_reported_default_each_price_blocked(self):
        r=self.parse(self.product());self.assertFalse(r['ready']);self.assertIn('PRICE_UNIT_UNVERIFIED',r['issues'])
    def test_display_case_each_not_single_deck(self):
        for label in ('Each','Display','Case','sealed case','6 Starter Decks',''):
            self.assertFalse(self.parse(self.product(label))['ready'],label)
    def test_explicit_unit_only_when_matches(self):
        r=self.parse(self.product('single starter deck'));self.assertTrue(r['ready']);self.assertTrue(unit_valid(r))
        self.assertFalse(unit_valid(r,'Case'));r['amount']='11.99';self.assertFalse(unit_valid(r))
    def test_stored_old_record_invalidated(self):
        r=self.parse(self.product());r.update(ready=True,issues=[]);r.pop('unit_evidence')
        e=self.event();install([r],[dict(e,sku=r['sku'])]);self.assertEqual(matched(e),[]);self.assertEqual(status()['ready'],0)
    def test_queued_old_reference_cannot_alert(self):
        e=self.event();e['reference_evidence']=self.ref()
        self.assertEqual(qualifying_references(e),[]);self.assertNotIn(classify(e),{'DEAL','BELOW_MSRP'})
        e.update(event_type='PRICE_DROP',old_price='28.99');self.assertEqual(classify(e),'PRICE_DROP')
    def test_conflicting_default_units_blocked(self):
        p=self.product('single starter deck');p['uomPrice'].append(dict(p['uomPrice'][0],UomName='sealed case'))
        self.assertFalse(self.parse(p)['ready'])
    def test_proof_preserved_in_matched_reference(self):
        r=self.parse(self.product('single starter deck'));e=self.event();install([r],[dict(e,sku=r['sku'])]);refs=matched(e)
        self.assertEqual(len(refs),1);self.assertTrue(unit_valid(refs[0],e['product_type']))
    def test_other_sources_not_disabled(self):
        r=self.ref();r['source']='https://www.phdgames.com/2026/10/18/example/'
        e=self.event();e['reference_evidence']=r;self.assertEqual(len(qualifying_references(e)),1)
