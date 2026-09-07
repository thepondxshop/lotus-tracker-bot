"""
Lotus Tracker Bot / PonDeX Trackers
Major Retailer Foundation
Step 6K-1A

This module defines the normalized contract for dedicated major-retailer
integrations (Target, Walmart, Best Buy, GameStop, Costco, Sam's Club,
Amazon, etc.). It deliberately does not contain retailer-specific scraping
or API logic.

Safety invariants:
- UNKNOWN availability stays UNKNOWN.
- Online and local-store availability are separate capabilities.
- Exact inventory is never inferred from a boolean stock signal.
- Price-only sources cannot emit stock/restock/sold-out events.
- No checkout, cart mutation, login guessing, CAPTCHA bypass, or queue bypass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse

VERSION = "1.0.0"

VALID_AVAILABILITY_STATES = {
    "IN_STOCK",
    "OUT_OF_STOCK",
    "PREORDER",
    "BACKORDER",
    "COMING_SOON",
    "UNKNOWN",
}

VALID_LIFECYCLE_STATES = {
    "NORMAL",
    "PREORDER",
    "COMING_SOON",
    "PAGE_LIVE",
    "UNKNOWN",
}

VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}


def _clean(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number, 4)


def _upper(value: Any, default: str) -> str:
    return _clean(value, default).upper().replace("-", "_").replace(" ", "_")


def _valid_http_url(value: Any) -> bool:
    raw = _clean(value)
    if not raw:
        return False
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@dataclass(frozen=True)
class MajorRetailerCapabilityProfile:
    """Capabilities verified for a specific retailer adapter/source."""

    discovery: bool = False
    price: bool = False
    page_live: bool = False
    preorder: bool = False
    online_availability: bool = False
    local_store_availability: bool = False
    exact_inventory: bool = False
    purchase_limit: bool = False
    affiliate_links: bool = False

    def availability_capability(self) -> str:
        if self.online_availability:
            return "FULL_AVAILABILITY"
        if self.price:
            return "DISCOVERY_PRICE_ONLY"
        return "DISCOVERY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["availability_capability"] = self.availability_capability()
        return data


@dataclass(frozen=True)
class MajorRetailerDefinition:
    key: str
    display_name: str
    domain: str
    region: str = "US"
    enabled: bool = False
    affiliate_provider: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MajorRetailerProbe:
    retailer_key: str
    success: bool
    source_name: str
    confidence: str = "UNKNOWN"
    http_status: int | None = None
    message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MajorRetailerProduct:
    """Normalized major-retailer product before Lotus persistence/events."""

    retailer_key: str
    external_product_id: str
    title: str
    game: str
    url: str

    price: float | None = None
    currency: str = "USD"

    availability_state: str = "UNKNOWN"
    availability_known: bool = False
    availability_confidence: str = "UNKNOWN"

    lifecycle_state: str = "UNKNOWN"
    lifecycle_confidence: str = "UNKNOWN"

    product_type: str = "TCG Product"
    product_category: str = "UNKNOWN"
    product_family: str = "GLOBAL_STANDARD"

    image_url: str | None = None
    sku: str | None = None
    upc: str | None = None
    offer_id: str | None = None
    purchase_limit: int | None = None

    exact_inventory_quantity: int | None = None
    local_store_id: str | None = None
    local_store_availability_state: str = "UNKNOWN"

    source_name: str = "major_retailer"
    source_confidence: str = "UNKNOWN"
    affiliate_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self, capabilities: MajorRetailerCapabilityProfile) -> list[str]:
        errors: list[str] = []

        if not _clean(self.retailer_key):
            errors.append("MISSING_RETAILER_KEY")
        if not _clean(self.external_product_id):
            errors.append("MISSING_EXTERNAL_PRODUCT_ID")
        if not _clean(self.title):
            errors.append("MISSING_TITLE")
        if not _clean(self.game):
            errors.append("MISSING_GAME")
        if not _valid_http_url(self.url):
            errors.append("INVALID_URL")

        availability_state = _upper(self.availability_state, "UNKNOWN")
        if availability_state not in VALID_AVAILABILITY_STATES:
            errors.append("INVALID_AVAILABILITY_STATE")

        lifecycle_state = _upper(self.lifecycle_state, "UNKNOWN")
        if lifecycle_state not in VALID_LIFECYCLE_STATES:
            errors.append("INVALID_LIFECYCLE_STATE")

        availability_confidence = _upper(self.availability_confidence, "UNKNOWN")
        if availability_confidence not in VALID_CONFIDENCE:
            errors.append("INVALID_AVAILABILITY_CONFIDENCE")

        source_confidence = _upper(self.source_confidence, "UNKNOWN")
        if source_confidence not in VALID_CONFIDENCE:
            errors.append("INVALID_SOURCE_CONFIDENCE")

        # Critical stock-safety rules.
        if self.availability_known and not capabilities.online_availability:
            errors.append("STOCK_SIGNAL_WITHOUT_VERIFIED_CAPABILITY")
        if availability_state in {"IN_STOCK", "OUT_OF_STOCK", "BACKORDER"} and not self.availability_known:
            errors.append("KNOWN_STOCK_STATE_MARKED_UNKNOWN")
        if availability_state == "UNKNOWN" and self.availability_known:
            errors.append("UNKNOWN_STATE_MARKED_KNOWN")

        if self.exact_inventory_quantity is not None:
            if not capabilities.exact_inventory:
                errors.append("EXACT_INVENTORY_WITHOUT_VERIFIED_CAPABILITY")
            try:
                if int(self.exact_inventory_quantity) < 0:
                    errors.append("NEGATIVE_EXACT_INVENTORY")
            except (TypeError, ValueError):
                errors.append("INVALID_EXACT_INVENTORY")

        if self.local_store_id and not capabilities.local_store_availability:
            errors.append("LOCAL_STORE_DATA_WITHOUT_VERIFIED_CAPABILITY")

        if self.purchase_limit is not None:
            try:
                if int(self.purchase_limit) <= 0:
                    errors.append("INVALID_PURCHASE_LIMIT")
            except (TypeError, ValueError):
                errors.append("INVALID_PURCHASE_LIMIT")

        return errors

    def to_normalized_dict(
        self,
        capabilities: MajorRetailerCapabilityProfile,
        *,
        region: str = "US",
    ) -> dict[str, Any]:
        """Convert into Lotus's existing normalized product/event contract."""

        errors = self.validate(capabilities)
        if errors:
            raise ValueError(";".join(errors))

        availability_state = _upper(self.availability_state, "UNKNOWN")
        lifecycle_state = _upper(self.lifecycle_state, "UNKNOWN")

        # Capability gating is repeated here intentionally. A retailer adapter
        # cannot force stock semantics simply by setting a field.
        availability_known = bool(self.availability_known and capabilities.online_availability)
        if not availability_known:
            availability_state = "UNKNOWN"

        available = availability_state in {"IN_STOCK", "PREORDER"}

        if lifecycle_state == "PREORDER" or availability_state == "PREORDER":
            product_state = "PREORDER"
        elif lifecycle_state == "COMING_SOON":
            product_state = "COMING_SOON"
        elif availability_state == "IN_STOCK":
            product_state = "STOCK_AVAILABLE"
        elif availability_state == "OUT_OF_STOCK":
            product_state = "SOLD_OUT"
        elif availability_state == "BACKORDER":
            product_state = "BACKORDER"
        else:
            product_state = "PAGE_LIVE"

        platform_data = {
            "availability_capability": capabilities.availability_capability(),
            "availability_known": availability_known,
            "availability_state": availability_state,
            "availability_confidence": _upper(self.availability_confidence, "UNKNOWN"),
            "lifecycle_state": lifecycle_state,
            "lifecycle_confidence": _upper(self.lifecycle_confidence, "UNKNOWN"),
            "source_confidence": _upper(self.source_confidence, "UNKNOWN"),
            "source_name": _clean(self.source_name, "major_retailer"),
            "major_retailer_key": _clean(self.retailer_key).lower(),
            "upc": _clean(self.upc) or None,
            "affiliate_url": _clean(self.affiliate_url) or None,
            "exact_inventory_quantity": (
                int(self.exact_inventory_quantity)
                if self.exact_inventory_quantity is not None and capabilities.exact_inventory
                else None
            ),
            "local_store_id": _clean(self.local_store_id) or None,
            "local_store_availability_state": (
                _upper(self.local_store_availability_state, "UNKNOWN")
                if capabilities.local_store_availability
                else "UNKNOWN"
            ),
            "major_retailer_capabilities": capabilities.to_dict(),
        }
        platform_data.update(dict(self.extra or {}))

        return {
            "external_id": _clean(self.external_product_id),
            "external_product_id": _clean(self.external_product_id),
            "title": _clean(self.title),
            "game": _clean(self.game),
            "url": _clean(self.affiliate_url) or _clean(self.url),
            "price": _price(self.price) if capabilities.price else None,
            "currency": _upper(self.currency, "USD"),
            "available": available if availability_known else False,
            "product_type": _clean(self.product_type, "TCG Product"),
            "product_category": _upper(self.product_category, "UNKNOWN"),
            "product_family": _upper(self.product_family, "GLOBAL_STANDARD"),
            "product_state": product_state,
            "image_url": _clean(self.image_url) or None,
            "vendor": None,
            "tags": None,
            "sku": _clean(self.sku) or None,
            "offer_id": _clean(self.offer_id) or None,
            "variant_id": None,
            "purchase_limit": (
                int(self.purchase_limit)
                if self.purchase_limit is not None and capabilities.purchase_limit
                else None
            ),
            "cart_base_url": None,
            "region": _upper(region, "US"),
            "source_type": "major_retailer",
            "retailer_key": _clean(self.retailer_key).lower(),
            "platform_data": platform_data,
        }


class MajorRetailerAdapter(ABC):
    """Base interface implemented by retailer-specific adapters."""

    retailer_key: str = ""
    version: str = VERSION

    def __init__(self, definition: MajorRetailerDefinition):
        self.definition = definition
        self.diagnostics: dict[str, Any] = {}

    @property
    @abstractmethod
    def capabilities(self) -> MajorRetailerCapabilityProfile:
        raise NotImplementedError

    async def healthcheck(self) -> MajorRetailerProbe:
        return MajorRetailerProbe(
            retailer_key=self.retailer_key,
            success=True,
            source_name=self.__class__.__name__,
            confidence="UNKNOWN",
            message="NO_RETAILER_SPECIFIC_HEALTHCHECK",
        )

    @abstractmethod
    async def discover_products(self, *, limit: int = 50) -> list[MajorRetailerProduct]:
        raise NotImplementedError

    async def refresh_products(
        self,
        product_ids: Iterable[str],
    ) -> list[MajorRetailerProduct]:
        # Retailer adapters may override this with a faster known-product path.
        wanted = {_clean(value) for value in product_ids if _clean(value)}
        if not wanted:
            return []
        discovered = await self.discover_products(limit=max(len(wanted), 50))
        return [p for p in discovered if _clean(p.external_product_id) in wanted]

    def get_diagnostics(self) -> dict[str, Any]:
        return dict(self.diagnostics)
