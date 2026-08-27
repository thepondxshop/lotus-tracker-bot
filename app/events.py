from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# =========================================================
# LOTUS PRODUCT EVENTS
# PonDeX Trackers
# Version 1.0.2
#
# Product Family Support
# Pricing Intelligence
# MSRP Intelligence
# Scalper Protection
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

    # =====================================================
    # CORE EVENT
    # =====================================================

    event_type: ProductEventType

    game: str

    product_name: str

    store_name: str

    product_url: str


    # =====================================================
    # CURRENT PRICE
    # =====================================================

    price: float | None = None

    old_price: float | None = None

    currency: str = "USD"


    # =====================================================
    # STOCK
    # =====================================================

    in_stock: bool = False


    # =====================================================
    # REGION / LANGUAGE
    # =====================================================

    region: str = "US"

    language: str = "English"


    # =====================================================
    # PRODUCT IDENTITY
    #
    # product_type examples:
    #
    # Booster Box
    # Booster Bundle
    # Elite Trainer Box
    # Starter Deck
    #
    # product_category:
    #
    # SEALED
    # SINGLE
    # ACCESSORY
    # UNKNOWN
    #
    # product_family:
    #
    # GLOBAL_STANDARD
    # JP
    # KR
    # CN
    # UNKNOWN
    # =====================================================

    product_type: str = "Unknown"

    product_category: str = "UNKNOWN"

    product_family: str = "UNKNOWN"


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


    # =====================================================
    # SMART QUICK CART
    # =====================================================

    variant_id: str | None = None

    purchase_limit: int | None = None

    cart_base_url: str | None = None


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
    # MSRP INTELLIGENCE
    # =====================================================

    msrp: float | None = None

    msrp_currency: str | None = None

    msrp_source: str | None = None

    msrp_confidence: str | None = None


    # -----------------------------------------------------
    # Original MSRP before conversion.
    #
    # Example:
    #
    # MSRP:
    # $119.99 USD
    #
    # Shopify store:
    # CAD
    #
    # msrp_original:
    # 119.99
    #
    # msrp_original_currency:
    # USD
    #
    # msrp:
    # converted CAD reference
    # -----------------------------------------------------

    msrp_original: float | None = None

    msrp_original_currency: str | None = None

    msrp_conversion_used: bool = False


    # =====================================================
    # MSRP COMPARISON
    # =====================================================

    price_vs_msrp_pct: float | None = None

    markup_amount: float | None = None

    msrp_price_state: str | None = None


    # =====================================================
    # SCALPER PROTECTION
    # =====================================================

    scalper_risk: str | None = None


    # =====================================================
    # COMBINED DEAL INTELLIGENCE
    # =====================================================

    deal_score: float | None = None

    deal_label: str | None = None

    deal_confidence: str | None = None


    # =====================================================
    # TIME
    # =====================================================

    timestamp: datetime | None = None


    # =====================================================
    # POST INIT
    # =====================================================

    def __post_init__(
        self,
    ):

        if self.timestamp is None:

            self.timestamp = (
                datetime.utcnow()
            )


        # =================================================
        # NORMALIZE PRODUCT CATEGORY
        # =================================================

        self.product_category = (
            str(
                self.product_category
                or "UNKNOWN"
            )
            .strip()
            .upper()
        )


        if self.product_category not in {

            "SEALED",
            "SINGLE",
            "ACCESSORY",
            "UNKNOWN",

        }:

            self.product_category = (
                "UNKNOWN"
            )


        # =================================================
        # NORMALIZE PRODUCT FAMILY
        # =================================================

        self.product_family = (
            str(
                self.product_family
                or "UNKNOWN"
            )
            .strip()
            .upper()
            .replace(
                "-",
                "_",
            )
            .replace(
                " ",
                "_",
            )
        )


        family_aliases = {

            "GLOBAL":
                "GLOBAL_STANDARD",

            "STANDARD":
                "GLOBAL_STANDARD",

            "ENGLISH":
                "GLOBAL_STANDARD",

            "INTERNATIONAL":
                "GLOBAL_STANDARD",

            "JAPAN":
                "JP",

            "JAPANESE":
                "JP",

            "JPN":
                "JP",

            "KOREA":
                "KR",

            "KOREAN":
                "KR",

            "KOR":
                "KR",

            "CHINA":
                "CN",

            "CHINESE":
                "CN",

            "SIMPLIFIED_CHINESE":
                "CN",
        }


        self.product_family = (
            family_aliases.get(

                self.product_family,

                self.product_family,
            )
        )


        if self.product_family not in {

            "GLOBAL_STANDARD",
            "JP",
            "KR",
            "CN",
            "UNKNOWN",

        }:

            self.product_family = (
                "UNKNOWN"
            )


        # =================================================
        # NORMALIZE CURRENCIES
        # =================================================

        self.currency = (
            str(
                self.currency
                or "USD"
            )
            .strip()
            .upper()
        )


        if self.msrp_currency:

            self.msrp_currency = (
                str(
                    self.msrp_currency
                )
                .strip()
                .upper()
            )


        if self.msrp_original_currency:

            self.msrp_original_currency = (
                str(
                    self.msrp_original_currency
                )
                .strip()
                .upper()
            )


        # =================================================
        # NORMALIZE SOURCE
        # =================================================

        self.source_type = (
            str(
                self.source_type
                or "unknown"
            )
            .strip()
            .lower()
        )