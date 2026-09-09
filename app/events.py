from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# =========================================================
# LOTUS PRODUCT EVENTS
# PonDeX Trackers
# Bot Release 1.0.6 • Step 6K-2C
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

    # Pricing
    price: float | None = None
    old_price: float | None = None
    currency: str = "USD"

    # Historical pricing / deal intelligence
    price_window_days: int | None = None
    price_30d_low: float | None = None
    price_30d_average: float | None = None
    price_30d_high: float | None = None
    price_history_samples: int | None = None
    price_vs_average_pct: float | None = None
    price_vs_low_pct: float | None = None
    price_drop_pct: float | None = None
    deal_score: float | None = None
    deal_label: str | None = None
    deal_confidence: str | None = None

    # Inventory
    in_stock: bool = False
    availability_state: str = "UNKNOWN"
    availability_known: bool = False
    availability_confidence: str = "UNKNOWN"
    exact_inventory_quantity: int | None = None

    # Product / region data
    region: str = "US"
    language: str = "English"
    product_type: str = "Unknown"
    product_category: str = "UNKNOWN"
    product_family: str = "UNKNOWN"

    # Lifecycle / release intelligence
    lifecycle_state: str = "UNKNOWN"
    release_date: str | None = None
    old_release_date: str | None = None

    # Source
    source_type: str = "unknown"
    retailer_key: str | None = None
    external_product_id: str | None = None
    source_confidence: str = "UNKNOWN"
    image_url: str | None = None

    # Smart cart
    variant_id: str | None = None
    purchase_limit: int | None = None
    cart_base_url: str | None = None

    # Event time
    timestamp: datetime | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

        if self.product_category:
            self.product_category = self.product_category.upper()
        if self.product_family:
            self.product_family = self.product_family.upper()
        if self.currency:
            self.currency = self.currency.upper()
        if self.region:
            self.region = self.region.upper()
        if self.deal_confidence:
            self.deal_confidence = self.deal_confidence.upper()
        if self.availability_state:
            self.availability_state = self.availability_state.upper()
        if self.availability_confidence:
            self.availability_confidence = self.availability_confidence.upper()
        if self.lifecycle_state:
            self.lifecycle_state = self.lifecycle_state.upper()
        if self.source_confidence:
            self.source_confidence = self.source_confidence.upper()
