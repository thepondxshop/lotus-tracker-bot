import unittest
from unittest.mock import AsyncMock, Mock, patch


class WorkerRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_accessory_channel_reaches_guild_resolution(self):
        from app import worker
        for region, expected in [('US', 1562959977377955860), ('JP', 1562960120152064010)]:
            event = dict(product_name='Pokemon Deck Case', product_type='Case',
                         game='Pokemon', region=region, event_type='RESTOCK')
            guild = Mock()
            guild.get_channel.return_value = None
            with patch('app.deal_references.enrich', side_effect=lambda e:e), \
                 patch.object(worker, 'validate_event_game', return_value=True), \
                 patch.object(worker, 'queue_tcg_discovery_review'), \
                 patch.object(worker, 'determine_alert_route', return_value='shopify'), \
                 patch.object(worker, 'should_suppress_duplicate', new=AsyncMock(return_value=False)), \
                 patch.object(worker, 'classify_price', return_value=None), \
                 patch.object(worker, 'get_primary_guild', return_value=guild), \
                 patch.dict('os.environ', {}, clear=True):
                self.assertFalse(await worker.route_event_to_discord(None, event))
            guild.get_channel.assert_called_once_with(expected)
