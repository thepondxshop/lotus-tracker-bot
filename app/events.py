from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# =========================================================
# LOTUS PRODUCT EVENTS
# PonDeX Trackers
# Version 0.7.6
# =========================================================


class ProductEventType(
    str,
    Enum,
):

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

    price: float | None = None

    currency: str = "USD"

    in_stock: bool = False

    region: str = "US"

    language: str = "English"

    product_type: str = "Unknown"

    # =====================================================
    # SOURCE ROUTING
    #
    # shopify
    # major_retailer
    # pokemon_center
    # queue
    # simulation
    # =====================================================

    source_type: str = "unknown"

    retailer_key: str | None = None

    # =====================================================
    # PRODUCT IMAGE
    # =====================================================

    image_url: str | None = None

    timestamp: datetime | None = None


    def __post_init__(
        self,
    ):

        if self.timestamp is None:

            self.timestamp = (
                datetime.utcnow()
            )