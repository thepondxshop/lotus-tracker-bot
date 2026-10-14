import unittest
from unittest.mock import AsyncMock, MagicMock
from app.marketplaces.ebay import AccessFailure
from app.marketplaces.ebay_notifications import PublicKeys, VerificationUnavailable

class DiagnosticTest(unittest.IsolatedAsyncioTestCase):
    async def test_auth_failure_retains_phase(self):
        keys=PublicKeys();keys.session=MagicMock()
        keys.auth.token=AsyncMock(side_effect=AccessFailure('AUTH_OR_ACCESS_REQUIRED','AUTH',401))
        with self.assertRaises(VerificationUnavailable) as cm:await keys.get('test-key')
        self.assertEqual((cm.exception.phase,cm.exception.status),('AUTH',401))
    async def test_key_failure_retains_phase(self):
        keys=PublicKeys();keys.session=MagicMock();keys.auth.token=AsyncMock(return_value='secret-test')
        response=MagicMock();response.status=403
        keys.session.get.return_value.__aenter__=AsyncMock(return_value=response)
        keys.session.get.return_value.__aexit__=AsyncMock(return_value=False)
        with self.assertRaises(VerificationUnavailable) as cm:await keys.get('test-key')
        self.assertEqual((cm.exception.phase,cm.exception.status),('PUBLIC_KEY',403))
        self.assertNotIn('secret-test',str(cm.exception))
    async def test_cooldown_no_network(self):
        keys=PublicKeys()
        with self.assertRaises(VerificationUnavailable) as cm:await keys.get('test-key')
        self.assertEqual(cm.exception.phase,'LOCAL')
if __name__=='__main__':unittest.main()
