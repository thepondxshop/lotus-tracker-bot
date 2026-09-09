from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# =========================================================
# LOTUS PRODUCT EVENTS
# PonDeX Trackers
# Bot Release 1.0.6 • Step 6K-2C1A
#
# Compatibility hotfix:
# Restores the historical-pricing / MSRP / scalper fields used
# by the Shopify monitor while preserving the extended major-
# retailer event fields introduced in Step 6K-2C.
# =========================================================


class ProductEventType(str, Enum):
    DISCOVERED = "DISCOVERED"
    PAGE_LIVE = "PAGE_LIVE"
    COMING_SOON = "COMING_SOON"
    PREORDER_LIVE = "PREORDER_LIVE"

    STOCK_AVAILABLE = "STOCK_AVAILABLE"
    RESTOCK = "RESTOCK"
    SOLD_OUT = "SOLD_OUT"

    PRICE_DROP = "PRICE_DROP"
    PRICE_INCREASE = "PRICE_INCREASE"
    PRICE_ERROR = "PRICE_ERROR"

    INVENTORY_FLICKER = "INVENTORY_FLICKER"
    RELEASE_DATE_CHANGED = "RELEASE_DATE_CHANGED"

    QUEUE_DETECTED = "QUEUE_DETECTED"
    QUEUE_ACTIVE = "QUEUE_ACTIVE"
    QUEUE_CLEARED = "QUEUE_CLEARED"


@dataclass
class ProductEvent:
    event_type: ProductEventType
    game: str
    product_name: str
    store_name: str
    product_url: str

    # =====================================================
    # PRICING
    # =====================================================
    price: float | None = None
    old_price: float | None = None
    currency: str = "USD"

    # =====================================================
    # HISTORICAL PRICE INTELLIGENCE
    # =====================================================
    price_window_days: int | None = None
    price_30d_low: float | None = None
    price_30d_average: float | None = None
    price_30d_high: float | None = None
    price_history_samples: int | None = None
    price_vs_average_pct: float | None = None
    price_vs_low_pct: float | None = None
    price_drop_pct: float | None = None
    historical_deal_score: float | None = None

    # =====================================================
    # MSRP / SCALPER PROTECTION
    # =====================================================
    msrp: float | None = None
    msrp_currency: str | None = None
    msrp_source: str | None = None
    msrp_confidence: str | None = None

    # Legacy/current Shopify conversion fields
    msrp_original: float | None = None
    msrp_original_currency: str | None = None
    msrp_conversion_used: bool = False

    # Reference-aware fields used by later pricing builds
    msrp_region: str | None = None
    pricing_reference_id: int | None = None
    msrp_compare_amount: float | None = None
    msrp_compare_currency: str | None = None

    price_vs_msrp_pct: float | None = None
    markup_amount: float | None = None
    msrp_price_state: str | None = None
    scalper_risk: str | None = None

    # =====================================================
    # FINAL DEAL SCORE
    # =====================================================
    deal_score: float | None = None
    deal_label: str | None = None
    deal_confidence: str | None = None

    # =====================================================
    # INVENTORY
    # =====================================================
    in_stock: bool = False
    availability_state: str = "UNKNOWN"
    availability_known: bool = False
    availability_confidence: str = "UNKNOWN"
    exact_inventory_quantity: int | None = None

    # =====================================================
    # PRODUCT / REGION
    # =====================================================
    region: str = "US"
    language: str = "English"
    product_type: str = "Unknown"
    product_category: str = "UNKNOWN"
    product_family: str = "UNKNOWN"

    # =====================================================
    # LIFECYCLE / RELEASE
    # =====================================================
    lifecycle_state: str = "UNKNOWN"
    release_date: str | None = None
    old_release_date: str | None = None

    # =====================================================
    # SOURCE
    # =====================================================
    source_type: str = "unknown"
    retailer_key: str | None = None
    external_product_id: str | None = None
    source_confidence: str = "UNKNOWN"
    image_url: str | None = None

    # =====================================================
    # SMART CART
    # =====================================================
    variant_id: str | None = None
    purchase_limit: int | None = None
    cart_base_url: str | None = None

    # =====================================================
    # TIME
    # =====================================================
    timestamp: datetime | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

        if self.product_category:
            self.product_category = str(self.product_category).upper()
        if self.product_family:
            self.product_family = str(self.product_family).upper()
        if self.currency:
            self.currency = str(self.currency).upper()
        if self.region:
            self.region = str(self.region).upper()

        if self.msrp_currency:
            self.msrp_currency = str(self.msrp_currency).upper()
        if self.msrp_original_currency:
            self.msrp_original_currency = str(self.msrp_original_currency).upper()
        if self.msrp_compare_currency:
            self.msrp_compare_currency = str(self.msrp_compare_currency).upper()
        if self.msrp_region:
            self.msrp_region = str(self.msrp_region).upper()
        if self.msrp_confidence:
            self.msrp_confidence = str(self.msrp_confidence).upper()

        if self.deal_confidence:
            self.deal_confidence = str(self.deal_confidence).upper()
        if self.scalper_risk:
            self.scalper_risk = str(self.scalper_risk).upper()

        if self.availability_state:
            self.availability_state = str(self.availability_state).upper()
        if self.availability_confidence:
            self.availability_confidence = str(self.availability_confidence).upper()
        if self.lifecycle_state:
            self.lifecycle_state = str(self.lifecycle_state).upper()
        if self.source_confidence:
            self.source_confidence = str(self.source_confidence).upper()
