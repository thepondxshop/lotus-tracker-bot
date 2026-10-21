import unittest
from app.case_identity import normalize_case_event,shipping_case_event
from app.tcg_identity import non_tcg_stationery
from app.price_policy import case_destination

class CaseRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_reported_titles_and_stale_evidence(self):
        for title in ['Hundreds Bandai One Piece Card Game Dice and Case Vol.1 TCG Japan Official',
                      'Takara Tomy Arts Pokemon Frenda Folder 5, 18-Pick Organizer Case',
                      'Acrylic Pokemon Booster Box Case', 'Mystery Pokemon Case']:
            event=dict(product_name=title,product_type='Case',event_type='PRICE_DROP',reference_evidence={'amount':'999'})
            fixed=normalize_case_event(event)
            self.assertFalse(shipping_case_event(event))
            self.assertIsNone(case_destination(fixed))
            self.assertNotIn('reference_evidence',fixed)
            self.assertIn('reference_evidence',event)
    def test_sealed_formats(self):
        for title in ['One Piece OP-17 Booster Box Case', 'Pokemon 10 Elite Trainer Box Case', 'MTG Commander Deck Case', 'Pokemon Booster Bundle Case']:
            self.assertTrue(shipping_case_event(dict(product_name=title,product_type='Case')))
    async def test_frenda_stops_in_actual_worker_before_enrichment(self):
        from unittest.mock import patch,Mock
        from app.worker import route_event_to_discord
        title='Takara Tomy Arts Pokemon Frenda Folder 5, 18-Pick Organizer Case'
        self.assertTrue(non_tcg_stationery(title))
        with patch('app.deal_references.enrich',side_effect=AssertionError('Must not enrich')):
            self.assertFalse(await route_event_to_discord(Mock(),dict(product_name=title,product_type='Case')))
    def test_real_tcgs_not_suppressed(self):
        self.assertFalse(non_tcg_stationery('Pokemon Elite Trainer Box'))
