"""
Target major-retailer adapter placeholder.
Step 6K-2C • Bot release 1.0.6

Target's prior Redsky validation path is RETIRED. Railway received HTTP 403
CAPTCHA responses, so Lotus must not retry it, rotate identities, or attempt a
CAPTCHA bypass. The adapter remains registered only so diagnostics clearly
report why Target is parked while an approved official feed/partner source is
pending.
"""

from __future__ import annotations

from .base import (
    MajorRetailerAdapter,
    MajorRetailerCapabilityProfile,
    MajorRetailerProbe,
    MajorRetailerProduct,
)
from .registry import major_retailer_adapter

VERSION = "1.0.6"
STEP = "6K-2C"


@major_retailer_adapter("target")
class TargetMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "target"
    version = VERSION

    def __init__(self, definition):
        super().__init__(definition)
        self.diagnostics = {
            "integration_state": "PARKED",
            "redsky_state": "RETIRED_CAPTCHA_PROTECTED",
            "network_requests": 0,
            "required_source": "APPROVED_OFFICIAL_FEED_OR_PARTNER_SOURCE",
            "last_error": "TARGET_OFFICIAL_SOURCE_REQUIRED",
        }

    @property
    def capabilities(self) -> MajorRetailerCapabilityProfile:
        # Nothing is claimed while the approved official source is unavailable.
        return MajorRetailerCapabilityProfile(
            discovery=False,
            price=False,
            page_live=False,
            preorder=False,
            online_availability=False,
            local_store_availability=False,
            exact_inventory=False,
            purchase_limit=False,
            affiliate_links=False,
            release_date=False,
        )

    async def healthcheck(self) -> MajorRetailerProbe:
        return MajorRetailerProbe(
            retailer_key=self.retailer_key,
            success=False,
            source_name="TargetOfficialSourcePending",
            confidence="HIGH",
            message="TARGET_OFFICIAL_SOURCE_REQUIRED_REDSKY_RETIRED_CAPTCHA_PROTECTED",
            diagnostics=self.get_diagnostics(),
        )

    async def discover_products(self, *, limit: int = 50) -> list[MajorRetailerProduct]:
        # Intentionally zero network requests. This prevents accidental Redsky
        # retries while Target remains parked.
        self.diagnostics["network_requests"] = 0
        self.diagnostics["last_error"] = "TARGET_OFFICIAL_SOURCE_REQUIRED"
        return []
