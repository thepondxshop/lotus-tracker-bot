from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# =========================================================
# LOTUS PRODUCT EVENTS
# PonDeX Trackers
# Version 1.0.0
#
# Historical Pricing
# MSRP Intelligence
# Scalper Protection
# Deal Score
# Smart Quick Cart
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


# =========================================================
# PRODUCT EVENT
# =========================================================

@dataclass
class ProductEvent:

    event_type: ProductEventType

    game: str

    product_name: str

    store_name: str

    product_url: str


    # =====================================================
    # CURRENT PRICING
    # =====================================================

    price: float | None = None

    old_price: float | None = None

    currency: str = "USD"


    # =====================================================
    # HISTORICAL PRICING
    #
    # Used for:
    #
    # - 30-day low
    # - 30-day average
    # - 30-day high
    # - price-drop calculations
    # - historical deal score
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
    # MSRP / REFERENCE PRICING
    #
    # msrp:
    # MSRP converted into the store's current native
    # currency when conversion is required.
    #
    # msrp_original:
    # Original verified reference amount.
    #
    # Example:
    #
    # Verified MSRP:
    # $59.99 USD
    #
    # Hobbiesville listing:
    # C$89.99 CAD
    #
    # Event stores:
    #
    # msrp = ~82.75
    # msrp_currency = CAD
    #
    # msrp_original = 59.99
    # msrp_original_currency = USD
    # =====================================================

    msrp: float | None = None

    msrp_currency: str | None = None

    msrp_source: str | None = None

    msrp_confidence: str | None = None

    msrp_original: float | None = None

    msrp_original_currency: str | None = None

    msrp_conversion_used: bool = False


    # =====================================================
    # MSRP COMPARISON
    # =====================================================

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


    # =====================================================
    # PRODUCT / REGION
    # =====================================================

    region: str = "US"

    language: str = "English"

    product_type: str = "Unknown"

    # SEALED / SINGLE / ACCESSORY / UNKNOWN

    product_category: str = "UNKNOWN"


    # =====================================================
    # SOURCE
    # =====================================================

    source_type: str = "unknown"

    retailer_key: str | None = None

    image_url: str | None = None


    # =====================================================
    # SMART QUICK CART
    # =====================================================

    variant_id: str | None = None

    purchase_limit: int | None = None

    cart_base_url: str | None = None


    # =====================================================
    # TIME
    # =====================================================

    timestamp: datetime | None = None


    # =====================================================
    # NORMALIZATION
    # =====================================================

    def __post_init__(
        self,
    ):

        # -------------------------------------------------
        # Timestamp
        # -------------------------------------------------

        if self.timestamp is None:

            self.timestamp = (
                datetime.utcnow()
            )


        # -------------------------------------------------
        # Product Category
        # -------------------------------------------------

        if self.product_category:

            self.product_category = (
                str(
                    self.product_category
                )
                .strip()
                .upper()
            )

        else:

            self.product_category = (
                "UNKNOWN"
            )


        # -------------------------------------------------
        # Store Currency
        # -------------------------------------------------

        if self.currency:

            self.currency = (
                str(
                    self.currency
                )
                .strip()
                .upper()
            )

        else:

            self.currency = (
                "USD"
            )


        # -------------------------------------------------
        # Region
        # -------------------------------------------------

        if self.region:

            self.region = (
                str(
                    self.region
                )
                .strip()
                .upper()
            )

        else:

            self.region = (
                "US"
            )


        # -------------------------------------------------
        # Converted MSRP Currency
        # -------------------------------------------------

        if self.msrp_currency:

            self.msrp_currency = (
                str(
                    self.msrp_currency
                )
                .strip()
                .upper()
            )


        # -------------------------------------------------
        # Original MSRP Currency
        # -------------------------------------------------

        if self.msrp_original_currency:

            self.msrp_original_currency = (
                str(
                    self.msrp_original_currency
                )
                .strip()
                .upper()
            )


        # -------------------------------------------------
        # MSRP Confidence
        # -------------------------------------------------

        if self.msrp_confidence:

            self.msrp_confidence = (
                str(
                    self.msrp_confidence
                )
                .strip()
                .upper()
            )


        # -------------------------------------------------
        # MSRP Price State
        # -------------------------------------------------

        if self.msrp_price_state:

            self.msrp_price_state = (
                str(
                    self.msrp_price_state
                )
                .strip()
                .upper()
            )


        # -------------------------------------------------
        # Deal Confidence
        # -------------------------------------------------

        if self.deal_confidence:

            self.deal_confidence = (
                str(
                    self.deal_confidence
                )
                .strip()
                .upper()
            )


        # -------------------------------------------------
        # Scalper Risk
        # -------------------------------------------------

        if self.scalper_risk:

            self.scalper_risk = (
                str(
                    self.scalper_risk
                )
                .strip()
                .upper()
            )


        # -------------------------------------------------
        # Source Type
        # -------------------------------------------------

        if self.source_type:

            self.source_type = (
                str(
                    self.source_type
                )
                .strip()
                .lower()
            )

        else:

            self.source_type = (
                "unknown"
            )


        # -------------------------------------------------
        # Boolean MSRP Conversion Flag
        # -------------------------------------------------

        self.msrp_conversion_used = bool(
            self.msrp_conversion_used
        )