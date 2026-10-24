import contextlib
import io
import json
import unittest
from unittest.mock import AsyncMock, patch
from app.marketplaces import ebay_listing_alerts as alerts

class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_has_location_without_sensitive_message(self):
        with patch.object(alerts,'_handle',new_callable=AsyncMock,side_effect=TypeError('secret-token seller-name https://private.example')),contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(TypeError):await alerts.handle()
        text=output.getvalue()
        self.assertNotIn('secret-token',text);self.assertNotIn('seller-name',text);self.assertNotIn('private.example',text)
        value=json.loads(text.split(' | ',1)[1])
        self.assertEqual(value['error_type'],'TypeError');self.assertTrue(value['frames'])
        self.assertEqual(set(value['frames'][0]),{'file','function','line'})

    async def test_success_preserves_result(self):
        with patch.object(alerts,'_handle',new_callable=AsyncMock,return_value='LISTING_SHADOW_ELIGIBLE') as handler,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(await alerts.handle('example'),'LISTING_SHADOW_ELIGIBLE')
            handler.assert_awaited_once_with('example')
        self.assertEqual(output.getvalue(),'')
