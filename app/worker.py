import asyncio
import hashlib

from urllib.parse import (
    urlparse,
)

import discord

from app.affiliate import (
    AFFILIATE_DISCLOSURE,
    build_affiliate_url,
)

from app.config import (
    ALERT_ACCESS,
    CHANNEL_MAP,
    GAME_ROLES,
)

from app.currency_service import (
    convert_currency,
    format_currency,
)

from app.event_service import (
    pop_next_event,
    save_alert_delivery,
)

from app.family_preference_service import (
    get_family_preferences_for_users,
)

from app.preference_service import (
    get_product_preferences,
)

from app.helpers import (
    safe_int,
)

from app.product_family import (
    normalize_product_family,
)

from app.redis_client import (
    check_redis,
    get_redis,
    init_redis,
)

from app.smart_cart import (
    build_smart_cart_from_event,
    smart_cart_debug_summary,
)

from app.shopify_variant_validator import (
    validate_event_variant,
    variant_validation_summary,
)


# =========================================================
# LOTUS EVENT WORKER
# PonDeX Trackers
# Version 1.0.4
#
# Source Routing
# Strict Member Audience Filtering
# Game Preferences
# Category Preferences
# Product Family Preferences
# Images
# Native Currency
# USD Conversion
# MSRP Intelligence
# Deal Intelligence
# Scalper Protection
# Smart Cart v1
# Live Shopify Variant Validation
# Discord Link Buttons
# Purchase Limit Protection
# Live Inventory Quantity Guard
# Conservative Unknown-Quantity Cart Safety
# Affiliate Links
# =========================================================


# =========================================================
# EVENT TITLES
# =========================================================

EVENT_TITLES = {

    "DISCOVERED":
        "📡 PRODUCT DISCOVERED",

    "PAGE_LIVE":
        "🔵 PRODUCT PAGE LIVE",

    "COMING_SOON":
        "🟡 COMING SOON",

    "PREORDER_LIVE":
        "🟣 PREORDER LIVE",

    "STOCK_AVAILABLE":
        "🟢 IN STOCK",

    "RESTOCK":
        "🚨 RESTOCK",

    "SOLD_OUT":
        "🔴 SOLD OUT",

    "PRICE_DROP":
        "🔥 PRICE DROP",

    "PRICE_INCREASE":
        "📈 PRICE INCREASE",

    "PRICE_ERROR":
        "⚠️ POSSIBLE PRICE ERROR",

    "INVENTORY_FLICKER":
        "⚡ INVENTORY FLICKER",

    "RELEASE_DATE_CHANGED":
        "📅 RELEASE DATE CHANGED",

    "QUEUE_DETECTED":
        "🚨 POKÉMON CENTER QUEUE DETECTED",

    "QUEUE_ACTIVE":
        "🚨 POKÉMON CENTER QUEUE LIVE",

    "QUEUE_CLEARED":
        "✅ POKÉMON CENTER QUEUE CLEARED",
}


# =========================================================
# PRODUCT FAMILY LABELS
# =========================================================

PRODUCT_FAMILY_LABELS = {

    "GLOBAL_STANDARD":
        "🌎 English / Global",

    "JP":
        "🇯🇵 Japanese",

    "KR":
        "🇰🇷 Korean",

    "CN":
        "🇨🇳 Simplified Chinese",

    "UNKNOWN":
        "❓ Unknown",
}


# =========================================================
# PRODUCT CATEGORY LABELS
# =========================================================

PRODUCT_CATEGORY_LABELS = {

    "SEALED":
        "📦 Sealed",

    "SINGLE":
        "🃏 Single",

    "ACCESSORY":
        "🎒 Accessory",

    "UNKNOWN":
        "❓ Unknown",
}


# =========================================================
# ROUTING
# =========================================================

def determine_alert_route(
    event,
):

    event_type = (
        event.get(
            "event_type"
        )
        or ""
    )

    source_type = (
        event.get(
            "source_type"
        )
        or ""
    ).lower()


    # =====================================================
    # POKEMON CENTER QUEUE
    # =====================================================

    if event_type in {

        "QUEUE_DETECTED",
        "QUEUE_ACTIVE",
        "QUEUE_CLEARED",

    }:

        return (
            "pokemon_queue"
        )


    if not source_type:

        return None


    # =====================================================
    # SHOPIFY
    # =====================================================

    if source_type == "shopify":

        if event_type in {

            "DISCOVERED",
            "PAGE_LIVE",
            "COMING_SOON",

        }:

            return (
                "page_live"
            )


        if (
            event_type
            == "PREORDER_LIVE"
        ):

            return (
                "preorder"
            )


        if (
            event_type
            == "INVENTORY_FLICKER"
        ):

            return (
                "inventory_flicker"
            )


        if event_type in {

            "PRICE_DROP",
            "PRICE_INCREASE",
            "PRICE_ERROR",

        }:

            return (
                "deal"
            )


        if event_type in {

            "STOCK_AVAILABLE",
            "RESTOCK",
            "SOLD_OUT",

        }:

            return (
                "shopify"
            )


        return (
            "shopify"
        )


    # =====================================================
    # POKEMON CENTER PRODUCTS
    # =====================================================

    if (
        source_type
        == "pokemon_center"
    ):

        if (
            event_type
            == "PREORDER_LIVE"
        ):

            return (
                "preorder"
            )


        if event_type in {

            "DISCOVERED",
            "PAGE_LIVE",
            "COMING_SOON",

        }:

            return (
                "release_radar"
            )


        if event_type in {

            "PRICE_DROP",
            "PRICE_INCREASE",
            "PRICE_ERROR",

        }:

            return (
                "deal"
            )


        return (
            "major_retailer"
        )


    # =====================================================
    # MAJOR RETAILERS
    # =====================================================

    if (
        source_type
        == "major_retailer"
    ):

        if (
            event_type
            == "PREORDER_LIVE"
        ):

            return (
                "preorder"
            )


        if event_type in {

            "PRICE_DROP",
            "PRICE_INCREASE",
            "PRICE_ERROR",

        }:

            return (
                "deal"
            )


        if (
            event_type
            == "INVENTORY_FLICKER"
        ):

            return (
                "inventory_flicker"
            )


        return (
            "major_retailer"
        )


    # =====================================================
    # SIMULATION
    # =====================================================

    if (
        source_type
        == "simulation"
    ):

        if event_type in {

            "DISCOVERED",
            "PAGE_LIVE",
            "COMING_SOON",

        }:

            return (
                "page_live"
            )


        if (
            event_type
            == "PREORDER_LIVE"
        ):

            return (
                "preorder"
            )


        if event_type in {

            "PRICE_DROP",
            "PRICE_INCREASE",
            "PRICE_ERROR",

        }:

            return (
                "deal"
            )


        if (
            event_type
            == "INVENTORY_FLICKER"
        ):

            return (
                "inventory_flicker"
            )


        return (
            "major_retailer"
        )


    return None


# =========================================================
# DEDUPE
# =========================================================

REALTIME_EVENTS = {

    "RESTOCK",
    "SOLD_OUT",
    "INVENTORY_FLICKER",
    "QUEUE_DETECTED",
    "QUEUE_ACTIVE",
    "QUEUE_CLEARED",
}


async def should_suppress_duplicate(
    event,
):

    if (
        event.get(
            "event_type"
        )
        in REALTIME_EVENTS
    ):

        return False


    redis_client = (
        get_redis()
    )


    if redis_client is None:

        return False


    identity = "|".join(
        [
            str(
                event.get(
                    "event_type",
                    ""
                )
            ),

            str(
                event.get(
                    "source_type",
                    ""
                )
            ),

            str(
                event.get(
                    "game",
                    ""
                )
            ),

            str(
                event.get(
                    "store_name",
                    ""
                )
            ),

            str(
                event.get(
                    "product_url",
                    ""
                )
            ),

            str(
                event.get(
                    "price",
                    ""
                )
            ),

            str(
                event.get(
                    "currency",
                    ""
                )
            ),

            str(
                event.get(
                    "product_category",
                    ""
                )
            ),

            str(
                event.get(
                    "product_family",
                    ""
                )
            ),
        ]
    )


    digest = (
        hashlib.sha256(
            identity.encode(
                "utf-8"
            )
        ).hexdigest()
    )


    try:

        result = (
            await redis_client.set(

                (
                    "lotus:dedupe:"
                    + digest
                ),

                "1",

                nx=True,

                ex=120,
            )
        )


        return (
            result is None
        )


    except Exception as error:

        print(
            (
                "DEDUPE ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return False


# =========================================================
# SAFE FLOAT
# =========================================================

def safe_float(
    value,
):

    if value is None:

        return None


    try:

        return float(
            value
        )


    except (
        TypeError,
        ValueError,
    ):

        return None


# =========================================================
# PERCENT
# =========================================================

def format_percent(
    value,
):

    parsed = (
        safe_float(
            value
        )
    )


    if parsed is None:

        return None


    sign = (

        "+"

        if parsed > 0

        else ""
    )


    return (
        f"{sign}{parsed:.1f}%"
    )


# =========================================================
# PRODUCT FAMILY
# =========================================================

def get_event_family(
    event,
):

    return (
        normalize_product_family(
            event.get(
                "product_family"
            )
        )
        or "UNKNOWN"
    )


# =========================================================
# PRODUCT CATEGORY
# =========================================================

def get_event_category(
    event,
):

    category = (
        str(
            event.get(
                "product_category"
            )
            or "UNKNOWN"
        )
        .strip()
        .upper()
    )


    if category not in {

        "SEALED",
        "SINGLE",
        "ACCESSORY",
        "UNKNOWN",

    }:

        return (
            "UNKNOWN"
        )


    return category


# =========================================================
# VALID HTTP URL
# =========================================================

def is_valid_http_url(
    value,
):

    if not value:

        return False


    try:

        parsed = (
            urlparse(
                str(
                    value
                ).strip()
            )
        )


        return (
            parsed.scheme
            in {
                "http",
                "https",
            }

            and

            bool(
                parsed.netloc
            )
        )


    except Exception:

        return False


# =========================================================
# SHOULD VALIDATE SMART CART
#
# We only spend another HTTP request when it is useful.
#
# No need to validate:
#
# - simulation
# - queue events
# - sold-out alerts
# - products without a variant
# =========================================================

def should_validate_smart_cart(
    event,
):

    source_type = (
        str(
            event.get(
                "source_type"
            )
            or ""
        )
        .strip()
        .lower()
    )


    if (
        source_type
        != "shopify"
    ):

        return False


    if not bool(
        event.get(
            "in_stock"
        )
    ):

        return False


    variant_id = (
        event.get(
            "variant_id"
        )
    )


    if not variant_id:

        return False


    return True


# =========================================================
# LIVE SMART CART VALIDATION
# =========================================================

async def get_live_variant_validation(
    event,
):

    if not should_validate_smart_cart(
        event
    ):

        return None


    try:

        validation = (
            await validate_event_variant(
                event
            )
        )


        print(
            (
                "SHOPIFY VARIANT VALIDATION | "
                f"Store={event.get('store_name')} | "
                f"Product={event.get('product_name')} | "
                f"{variant_validation_summary(validation)}"
            )
        )


        return validation


    except Exception as error:

        print(
            (
                "SHOPIFY VARIANT VALIDATION ERROR | "
                f"Store={event.get('store_name')} | "
                f"Product={event.get('product_name')} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


        return None


# =========================================================
# SMART CART READY
#
# Stored event state alone is no longer enough.
#
# Requirements:
#
# Event in stock
# Smart Cart supported
# Validation exists
# Variant valid
# Variant available
# =========================================================

def is_smart_cart_ready(
    event,
    smart_cart,
    validation,
):

    if smart_cart is None:

        return False


    if not smart_cart.supported:

        return False


    if not bool(
        event.get(
            "in_stock"
        )
    ):

        return False


    if validation is None:

        return False


    if not validation.checked:

        return False


    if not validation.valid:

        return False


    if not validation.available:

        return False


    if (
        validation.variant_id

        and

        smart_cart.variant_id

        and

        str(
            validation.variant_id
        )
        !=
        str(
            smart_cart.variant_id
        )
    ):

        return False


    return True



# =========================================================
# LIVE INVENTORY HELPERS
# =========================================================

def get_validation_inventory(
    validation,
):

    if validation is None:

        return (
            None,
            False,
        )

    known = bool(
        getattr(
            validation,
            "inventory_quantity_known",
            False,
        )
    )

    if not known:

        return (
            None,
            False,
        )

    value = getattr(
        validation,
        "inventory_quantity",
        None,
    )

    if value is None or isinstance(
        value,
        bool,
    ):

        return (
            None,
            False,
        )

    try:

        value = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return (
            None,
            False,
        )

    if value < 0:

        return (
            None,
            False,
        )

    return (
        value,
        True,
    )


def get_guarded_cart_quantities(
    smart_cart,
    validation,
):

    if smart_cart is None:

        return []

    base_quantities = list(
        smart_cart.quantities
        or []
    )

    inventory_quantity, inventory_known = (
        get_validation_inventory(
            validation
        )
    )

    if inventory_known:

        if inventory_quantity <= 0:

            return []

        return [
            quantity
            for quantity in base_quantities
            if quantity <= inventory_quantity
        ]

    # Exact inventory is unknown. Never imply x5/x10 means
    # those units definitely exist.
    if 1 in base_quantities:

        return [
            1
        ]

    return (
        base_quantities[
            :1
        ]
    )

# =========================================================
# BUILD EVENT EMBED
# =========================================================

async def build_event_embed(
    event,
    *,
    variant_validation=None,
):

    event_type = (
        event.get(
            "event_type",
            "UNKNOWN",
        )
    )

    product_name = (
        event.get(
            "product_name"
        )
        or "Unknown Product"
    )

    store_name = (
        event.get(
            "store_name"
        )
        or "Unknown Store"
    )

    product_url = (
        event.get(
            "product_url"
        )
        or ""
    )


    final_url, affiliate_used = (
        build_affiliate_url(

            product_url,

            store_name,
        )
    )


    embed = (
        discord.Embed(

            title=(
                EVENT_TITLES.get(

                    event_type,

                    "📡 LOTUS PRODUCT EVENT",
                )
            ),

            description=(
                f"**{product_name}**"
            ),

            url=(

                final_url

                if is_valid_http_url(
                    final_url
                )

                else None
            ),
        )
    )


    # =====================================================
    # IMAGE
    # =====================================================

    image_url = (
        event.get(
            "image_url"
        )
    )


    if image_url:

        embed.set_thumbnail(
            url=image_url
        )


    # =====================================================
    # STORE
    # =====================================================

    embed.add_field(

        name="Store",

        value=(
            store_name
        ),

        inline=True,
    )


    # =====================================================
    # GAME
    # =====================================================

    game = (
        event.get(
            "game"
        )
    )


    if game:

        embed.add_field(

            name="Game",

            value=(
                game
            ),

            inline=True,
        )


    # =====================================================
    # PRODUCT TYPE
    # =====================================================

    product_type = (
        event.get(
            "product_type"
        )
    )


    if product_type:

        embed.add_field(

            name="Type",

            value=(
                product_type
            ),

            inline=True,
        )


    # =====================================================
    # CATEGORY
    # =====================================================

    category = (
        get_event_category(
            event
        )
    )


    embed.add_field(

        name="Category",

        value=(
            PRODUCT_CATEGORY_LABELS.get(

                category,

                category,
            )
        ),

        inline=True,
    )


    # =====================================================
    # PRODUCT FAMILY
    # =====================================================

    family = (
        get_event_family(
            event
        )
    )


    embed.add_field(

        name="Product Family",

        value=(
            PRODUCT_FAMILY_LABELS.get(

                family,

                family,
            )
        ),

        inline=True,
    )


    # =====================================================
    # CURRENT PRICE
    # =====================================================

    price = (
        safe_float(
            event.get(
                "price"
            )
        )
    )

    currency = (
        str(
            event.get(
                "currency"
            )
            or "USD"
        )
        .strip()
        .upper()
    )


    if price is not None:

        native_text = (
            format_currency(

                price,

                currency,
            )
        )


        if (
            currency
            == "USD"
        ):

            price_text = (
                native_text
            )


        else:

            converted_usd = (
                await convert_currency(

                    price,

                    currency,

                    "USD",
                )
            )


            if converted_usd is not None:

                usd_text = (
                    format_currency(

                        converted_usd,

                        "USD",
                    )
                )


                price_text = (
                    f"{native_text}\n"
                    f"≈ {usd_text}"
                )


            else:

                price_text = (
                    native_text
                )


        embed.add_field(

            name="Price",

            value=(
                price_text
            ),

            inline=True,
        )


    # =====================================================
    # PREVIOUS PRICE
    # =====================================================

    old_price = (
        safe_float(
            event.get(
                "old_price"
            )
        )
    )


    if (
        old_price is not None

        and

        price is not None

        and

        old_price
        != price
    ):

        embed.add_field(

            name="Previous Price",

            value=(
                format_currency(

                    old_price,

                    currency,
                )
            ),

            inline=True,
        )


    # =====================================================
    # MSRP
    # =====================================================

    msrp = (
        safe_float(
            event.get(
                "msrp"
            )
        )
    )

    msrp_currency = (
        str(
            event.get(
                "msrp_currency"
            )
            or currency
        )
        .strip()
        .upper()
    )


    if msrp is not None:

        msrp_text = (
            format_currency(

                msrp,

                msrp_currency,
            )
        )


        original_msrp = (
            safe_float(
                event.get(
                    "msrp_original"
                )
            )
        )

        original_currency = (
            event.get(
                "msrp_original_currency"
            )
        )


        if (
            bool(
                event.get(
                    "msrp_conversion_used"
                )
            )

            and

            original_msrp is not None

            and

            original_currency
        ):

            original_currency = (
                str(
                    original_currency
                )
                .strip()
                .upper()
            )


            original_text = (
                format_currency(

                    original_msrp,

                    original_currency,
                )
            )


            msrp_text += (
                f"\nReference: {original_text}"
            )


        embed.add_field(

            name="MSRP",

            value=(
                msrp_text
            ),

            inline=True,
        )


    # =====================================================
    # MSRP DIFFERENCE
    # =====================================================

    price_vs_msrp = (
        format_percent(
            event.get(
                "price_vs_msrp_pct"
            )
        )
    )


    if price_vs_msrp:

        embed.add_field(

            name="vs MSRP",

            value=(
                price_vs_msrp
            ),

            inline=True,
        )


    # =====================================================
    # MSRP SOURCE
    # =====================================================

    msrp_source = (
        event.get(
            "msrp_source"
        )
    )

    msrp_confidence = (
        event.get(
            "msrp_confidence"
        )
    )


    if msrp_source:

        source_text = (
            str(
                msrp_source
            )
        )


        if msrp_confidence:

            source_text += (
                "\n"
                f"Confidence: {msrp_confidence}"
            )


        embed.add_field(

            name="MSRP Reference",

            value=(
                source_text[
                    :1024
                ]
            ),

            inline=False,
        )


    # =====================================================
    # DEAL SCORE
    # =====================================================

    deal_score = (
        safe_float(
            event.get(
                "deal_score"
            )
        )
    )

    deal_label = (
        event.get(
            "deal_label"
        )
    )


    if (
        deal_score is not None

        or

        deal_label
    ):

        if (
            deal_score is not None

            and

            deal_label
        ):

            deal_text = (
                f"{deal_score:.0f}/100\n"
                f"{deal_label}"
            )


        elif deal_score is not None:

            deal_text = (
                f"{deal_score:.0f}/100"
            )


        else:

            deal_text = (
                str(
                    deal_label
                )
            )


        embed.add_field(

            name="Deal Score",

            value=(
                deal_text
            ),

            inline=True,
        )


    # =====================================================
    # SCALPER PROTECTION
    # =====================================================

    scalper_risk = (
        event.get(
            "scalper_risk"
        )
    )


    if scalper_risk:

        risk_value = (
            str(
                scalper_risk
            )
            .strip()
            .upper()
        )


        risk_labels = {

            "LOW":
                "🟢 Low",

            "MEDIUM":
                "🟡 Medium",

            "HIGH":
                "🟠 High",

            "EXTREME":
                "🔴 Extreme",
        }


        embed.add_field(

            name="Markup Risk",

            value=(
                risk_labels.get(

                    risk_value,

                    risk_value,
                )
            ),

            inline=True,
        )


    # =====================================================
    # 30-DAY HISTORY
    # =====================================================

    price_30d_low = (
        safe_float(
            event.get(
                "price_30d_low"
            )
        )
    )

    price_30d_average = (
        safe_float(
            event.get(
                "price_30d_average"
            )
        )
    )


    if (
        price_30d_low is not None

        or

        price_30d_average is not None
    ):

        history_lines = []


        if price_30d_low is not None:

            history_lines.append(

                (
                    "Low: "
                    + format_currency(

                        price_30d_low,

                        currency,
                    )
                )
            )


        if price_30d_average is not None:

            history_lines.append(

                (
                    "Average: "
                    + format_currency(

                        price_30d_average,

                        currency,
                    )
                )
            )


        samples = (
            event.get(
                "price_history_samples"
            )
        )


        if samples:

            history_lines.append(
                f"Samples: {samples}"
            )


        embed.add_field(

            name="30-Day Pricing",

            value=(
                "\n".join(
                    history_lines
                )
            ),

            inline=True,
        )


    # =====================================================
    # STOCK STATUS
    # =====================================================

    if event_type in {

        "STOCK_AVAILABLE",
        "RESTOCK",
        "SOLD_OUT",
        "INVENTORY_FLICKER",

    }:

        embed.add_field(

            name="Status",

            value=(

                "🟢 IN STOCK"

                if event.get(
                    "in_stock"
                )

                else

                "🔴 OUT OF STOCK"
            ),

            inline=True,
        )


    # =====================================================
    # LIVE INVENTORY QUANTITY
    # =====================================================

    if (
        variant_validation is not None
        and
        bool(
            event.get(
                "in_stock"
            )
        )
    ):

        (
            live_inventory_quantity,
            live_inventory_known,
        ) = (
            get_validation_inventory(
                variant_validation
            )
        )

        if live_inventory_known:

            if live_inventory_quantity == 1:

                stock_text = (
                    "⚠️ 1 remaining"
                )

            elif live_inventory_quantity <= 5:

                stock_text = (
                    f"⚠️ {live_inventory_quantity} remaining"
                )

            else:

                stock_text = (
                    f"📦 {live_inventory_quantity} remaining"
                )

        else:

            stock_text = (
                "🟢 In Stock\n"
                "Quantity Unknown"
            )

        embed.add_field(

            name="Stock",

            value=(
                stock_text
            ),

            inline=True,
        )


    # =====================================================
    # PURCHASE LIMIT
    # =====================================================

    purchase_limit = (
        event.get(
            "purchase_limit"
        )
    )


    if purchase_limit:

        embed.add_field(

            name="Purchase Limit",

            value=(
                f"Max {purchase_limit}"
            ),

            inline=True,
        )


    # =====================================================
    # REGION
    # =====================================================

    region = (
        event.get(
            "region"
        )
    )


    if region:

        embed.add_field(

            name="Store Region",

            value=(
                region
            ),

            inline=True,
        )


    # =====================================================
    # SOURCE
    # =====================================================

    source_type = (
        event.get(
            "source_type"
        )
        or "unknown"
    )


    source_labels = {

        "shopify":
            "Shopify / TCG Store",

        "major_retailer":
            "Major Retailer",

        "pokemon_center":
            "Pokémon Center",

        "queue":
            "Queue Intelligence",

        "simulation":
            "Simulation",
    }


    embed.add_field(

        name="Source",

        value=(
            source_labels.get(

                source_type,

                source_type,
            )
        ),

        inline=True,
    )


    # =====================================================
    # QUICK PRODUCT LINK
    # =====================================================

    if (
        final_url

        and

        is_valid_http_url(
            final_url
        )
    ):

        embed.add_field(

            name="Quick Link",

            value=(
                f"[🛒 Open Product]"
                f"({final_url})"
            ),

            inline=False,
        )


    # =====================================================
    # SMART CART STATUS
    #
    # v1.0.3:
    #
    # Smart Cart must now pass LIVE variant validation.
    # =====================================================

    try:

        smart_cart = (
            build_smart_cart_from_event(
                event
            )
        )


        smart_cart_ready = (
            is_smart_cart_ready(

                event,

                smart_cart,

                variant_validation,
            )
        )


        if smart_cart_ready:

            guarded_quantities = (
                get_guarded_cart_quantities(
                    smart_cart,
                    variant_validation,
                )
            )

            quantity_text = (
                ", ".join(

                    f"x{quantity}"

                    for quantity
                    in guarded_quantities
                )
            )


            embed.add_field(

                name="⚡ Smart Cart",

                value=(

                    "✅ Live Variant Verified\n"

                    f"Quantities: "
                    f"{quantity_text}"
                    + (
                        "\n📦 Exact stock verified"
                        if bool(
                            getattr(
                                variant_validation,
                                "inventory_quantity_known",
                                False,
                            )
                        )
                        else
                        "\nℹ️ Exact stock unknown — conservative cart"
                    )
                ),

                inline=False,
            )


    except Exception as error:

        print(
            (
                "SMART CART EMBED ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


    # =====================================================
    # AFFILIATE DISCLOSURE
    # =====================================================

    if affiliate_used:

        embed.add_field(

            name="Affiliate Disclosure",

            value=(
                AFFILIATE_DISCLOSURE
            ),

            inline=False,
        )


    # =====================================================
    # FOOTER
    # =====================================================

    footer_parts = [
        "Lotus Tracker Bot",
        "PonDeX Trackers",
        "v1.0.3",
    ]


    if (
        currency
        != "USD"

        and

        price is not None
    ):

        footer_parts.append(
            "USD conversion approximate"
        )


    embed.set_footer(

        text=(
            " • ".join(
                footer_parts
            )
        )
    )


    return (
        embed,
        affiliate_used,
        final_url,
    )


# =========================================================
# ALERT BUTTON VIEW
#
# Row 0:
#
# 🛒 Quick Cart
# 🔗 Product Page
#
# Row 1+:
#
# x1 x2 x3...
#
# Smart Cart buttons ONLY appear after validation.
# =========================================================

def build_alert_view(
    event,
    *,
    product_url=None,
    variant_validation=None,
):

    view = (
        discord.ui.View(
            timeout=None
        )
    )


    buttons_added = 0


    # =====================================================
    # SMART CART
    # =====================================================

    try:

        smart_cart = (
            build_smart_cart_from_event(
                event
            )
        )


    except Exception as error:

        print(
            (
                "SMART CART BUILD ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


        smart_cart = None


    smart_cart_ready = (
        is_smart_cart_ready(

            event,

            smart_cart,

            variant_validation,
        )
    )


    # =====================================================
    # QUICK CART
    # =====================================================

    if (
        smart_cart_ready

        and

        smart_cart.primary_cart_url

        and

        is_valid_http_url(
            smart_cart.primary_cart_url
        )
    ):

        view.add_item(

            discord.ui.Button(

                label="Quick Cart",

                emoji="🛒",

                style=(
                    discord.ButtonStyle.link
                ),

                url=(
                    smart_cart.primary_cart_url
                ),

                row=0,
            )
        )


        buttons_added += 1


    # =====================================================
    # PRODUCT PAGE
    #
    # ALWAYS retained when we have a valid URL.
    #
    # So validation failure never kills the useful alert.
    # =====================================================

    final_product_url = (

        product_url

        if is_valid_http_url(
            product_url
        )

        else None
    )


    if final_product_url:

        view.add_item(

            discord.ui.Button(

                label="Product Page",

                emoji="🔗",

                style=(
                    discord.ButtonStyle.link
                ),

                url=(
                    final_product_url
                ),

                row=0,
            )
        )


        buttons_added += 1


    # =====================================================
    # QUANTITY BUTTONS
    # =====================================================

    if smart_cart_ready:

        quantities = (
            get_guarded_cart_quantities(
                smart_cart,
                variant_validation,
            )
        )


        for index, quantity in enumerate(
            quantities
        ):

            cart_url = (
                smart_cart.cart_links.get(
                    quantity
                )
            )


            if not (
                cart_url

                and

                is_valid_http_url(
                    cart_url
                )
            ):

                continue


            row = (
                1
                + (
                    index
                    // 5
                )
            )


            if row > 4:

                break


            view.add_item(

                discord.ui.Button(

                    label=(
                        f"x{quantity}"
                    ),

                    style=(
                        discord.ButtonStyle.link
                    ),

                    url=(
                        cart_url
                    ),

                    row=(
                        row
                    ),
                )
            )


            buttons_added += 1


    # =====================================================
    # DEBUG
    # =====================================================

    if smart_cart is not None:

        validation_text = (

            variant_validation_summary(
                variant_validation
            )

            if variant_validation is not None

            else "VariantValidation(Not Run)"
        )


        print(
            (
                "SMART CART | "
                f"Store={event.get('store_name')} | "
                f"Product={event.get('product_name')} | "
                f"{smart_cart_debug_summary(smart_cart)} | "
                f"{validation_text} | "
                f"Ready={smart_cart_ready} | "
                f"Buttons={buttons_added}"
            )
        )


    if buttons_added == 0:

        return None


    return view


# =========================================================
# PRIMARY GUILD
# =========================================================

def get_primary_guild(
    bot,
):

    if not bot.guilds:

        return None


    return (
        bot.guilds[
            0
        ]
    )


# =========================================================
# BASE GAME MEMBERS
# =========================================================

def get_game_members(
    guild,
    game,
):

    if not game:

        return []


    role_id = (
        safe_int(
            GAME_ROLES.get(
                game
            )
        )
    )


    if not role_id:

        return []


    role = (
        guild.get_role(
            role_id
        )
    )


    if role is None:

        return []


    return [

        member

        for member
        in role.members

        if (
            not member.bot
        )
    ]


# =========================================================
# CATEGORY ALLOWANCE
# =========================================================

async def member_allows_category(
    member,
    game,
    category,
):

    try:

        preferences = (
            await get_product_preferences(

                member.id,

                game,
            )
        )


        return bool(
            preferences.get(
                category,
                False,
            )
        )


    except Exception as error:

        print(
            (
                "CATEGORY PREF ERROR | "
                f"User={member.id} | "
                f"Game={game} | "
                f"Category={category} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


        return False


# =========================================================
# ELIGIBLE MEMBERS
#
# GAME
# +
# PRODUCT CATEGORY
# +
# PRODUCT FAMILY
# =========================================================

async def get_eligible_members(
    guild,
    event,
):

    game = (
        event.get(
            "game"
        )
    )


    if not game:

        return []


    category = (
        get_event_category(
            event
        )
    )


    family = (
        get_event_family(
            event
        )
    )


    base_members = (
        get_game_members(

            guild,

            game,
        )
    )


    if not base_members:

        return []


    family_preferences = (
        await get_family_preferences_for_users(

            [
                member.id

                for member
                in base_members
            ],

            game,
        )
    )


    eligible = []


    for member in base_members:

        member_family_preferences = (
            family_preferences.get(
                member.id,
                {}
            )
        )


        family_allowed = bool(
            member_family_preferences.get(
                family,
                False,
            )
        )


        if not family_allowed:

            continue


        category_allowed = (
            await member_allows_category(

                member,

                game,

                category,
            )
        )


        if not category_allowed:

            continue


        eligible.append(
            member
        )


    return eligible


# =========================================================
# MENTION CHUNKS
# =========================================================

def build_mention_chunks(
    members,
    *,
    max_length=1800,
):

    if not members:

        return []


    chunks = []

    current = []


    for member in members:

        mention = (
            member.mention
        )


        candidate = (
            " ".join(
                current
                + [
                    mention
                ]
            )
        )


        if (
            len(
                candidate
            )
            > max_length

            and

            current
        ):

            chunks.append(
                " ".join(
                    current
                )
            )


            current = [
                mention
            ]


        else:

            current.append(
                mention
            )


    if current:

        chunks.append(
            " ".join(
                current
            )
        )


    return chunks


# =========================================================
# SEND EVENT
# =========================================================

async def route_event_to_discord(
    bot,
    event,
):

    alert_type = (
        determine_alert_route(
            event
        )
    )


    if not alert_type:

        print(
            (
                "NO SAFE ROUTE FOR EVENT | "
                f"Event={event.get('event_type')} | "
                f"Source={event.get('source_type')} | "
                f"Store={event.get('store_name')}"
            )
        )

        return False


    if await should_suppress_duplicate(
        event
    ):

        return True


    access = (
        ALERT_ACCESS.get(
            alert_type
        )
    )


    if not access:

        print(
            (
                "ALERT ACCESS MISSING | "
                f"Route={alert_type}"
            )
        )

        return False


    channel_id = (
        safe_int(
            CHANNEL_MAP.get(
                access[
                    "channel_variable"
                ]
            )
        )
    )


    if not channel_id:

        print(
            (
                "ALERT CHANNEL ID MISSING | "
                f"Route={alert_type}"
            )
        )

        return False


    guild = (
        get_primary_guild(
            bot
        )
    )


    if guild is None:

        return False


    channel = (
        guild.get_channel(
            channel_id
        )
    )


    if channel is None:

        print(
            (
                "ALERT CHANNEL NOT FOUND | "
                f"Route={alert_type} | "
                f"ChannelID={channel_id}"
            )
        )

        return False


    # =====================================================
    # AUDIENCE
    # =====================================================

    queue_event = (
        event.get(
            "event_type"
        )
        in {

            "QUEUE_DETECTED",
            "QUEUE_ACTIVE",
            "QUEUE_CLEARED",

        }
    )


    mention_chunks = []


    if queue_event:

        game = (
            event.get(
                "game"
            )
            or "Pokemon"
        )


        role_id = (
            safe_int(
                GAME_ROLES.get(
                    game
                )
            )
        )


        role = (

            guild.get_role(
                role_id
            )

            if role_id

            else None
        )


        if role:

            mention_chunks = [
                role.mention
            ]


    else:

        eligible_members = (
            await get_eligible_members(

                guild,

                event,
            )
        )


        mention_chunks = (
            build_mention_chunks(
                eligible_members
            )
        )


        print(
            (
                "ALERT AUDIENCE | "
                f"Game={event.get('game')} | "
                f"Category={get_event_category(event)} | "
                f"Family={get_event_family(event)} | "
                f"Eligible={len(eligible_members)}"
            )
        )


    # =====================================================
    # LIVE VARIANT VALIDATION
    #
    # This happens immediately before building the Discord
    # alert.
    # =====================================================

    variant_validation = (
        await get_live_variant_validation(
            event
        )
    )


    # =====================================================
    # EMBED
    # =====================================================

    (
        embed,
        affiliate_used,
        final_product_url,
    ) = (
        await build_event_embed(

            event,

            variant_validation=(
                variant_validation
            ),
        )
    )


    # =====================================================
    # BUTTONS
    # =====================================================

    alert_view = (
        build_alert_view(

            event,

            product_url=(
                final_product_url
            ),

            variant_validation=(
                variant_validation
            ),
        )
    )


    first_content = (

        mention_chunks[
            0
        ]

        if mention_chunks

        else None
    )


    message = None


    # =====================================================
    # SEND
    # =====================================================

    for attempt in range(
        1,
        4,
    ):

        try:

            message = (
                await channel.send(

                    content=(
                        first_content
                    ),

                    embed=(
                        embed
                    ),

                    view=(
                        alert_view
                    ),

                    allowed_mentions=(
                        discord.AllowedMentions(

                            roles=True,

                            users=True,

                            everyone=False,
                        )
                    ),
                )
            )


            break


        except discord.DiscordServerError as error:

            print(
                (
                    "DISCORD ALERT RETRY | "
                    f"Attempt={attempt} | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )


            if (
                attempt
                < 3
            ):

                await asyncio.sleep(
                    attempt * 2
                )


        except Exception as error:

            print(
                (
                    "DISCORD ALERT ERROR | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )


            break


    if message is None:

        return False


    # =====================================================
    # EXTRA MEMBER PINGS
    # =====================================================

    if (
        len(
            mention_chunks
        )
        > 1
    ):

        for extra_chunk in mention_chunks[
            1:
        ]:

            try:

                await channel.send(

                    content=(
                        extra_chunk
                    ),

                    allowed_mentions=(
                        discord.AllowedMentions(

                            roles=False,

                            users=True,

                            everyone=False,
                        )
                    ),

                    delete_after=30,
                )


            except Exception as error:

                print(
                    (
                        "EXTRA MEMBER PING ERROR | "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )
                )


    # =====================================================
    # SAVE DELIVERY
    # =====================================================

    await save_alert_delivery(

        alert_type=(
            alert_type
        ),

        minimum_tier=(
            access.get(
                "minimum_tier",
                "Free",
            )
        ),

        discord_channel_id=(
            channel.id
        ),

        discord_message_id=(
            message.id
        ),
    )


    # =====================================================
    # SMART CART FINAL STATUS
    # =====================================================

    try:

        smart_cart = (
            build_smart_cart_from_event(
                event
            )
        )


        smart_cart_ready = (
            is_smart_cart_ready(

                event,

                smart_cart,

                variant_validation,
            )
        )


    except Exception:

        smart_cart_ready = (
            False
        )


    validation_reason = (

        variant_validation.reason

        if variant_validation is not None

        else "NOT_RUN"
    )


    print(
        (
            "ALERT SENT | "
            f"Event={event.get('event_type')} | "
            f"Store={event.get('store_name')} | "
            f"Game={event.get('game')} | "
            f"Category={get_event_category(event)} | "
            f"Family={get_event_family(event)} | "
            f"Currency={event.get('currency')} | "
            f"Route={alert_type} | "
            f"Image={bool(event.get('image_url'))} | "
            f"SmartCart={smart_cart_ready} | "
            f"VariantValidation={validation_reason} | "
            f"Affiliate={affiliate_used}"
        )
    )


    return True


# =========================================================
# EVENT WORKER
# =========================================================

async def run_event_worker(
    bot,
):

    await bot.wait_until_ready()


    print(
        "Lotus Event Worker v1.0.3 started."
    )


    while not bot.is_closed():

        try:

            if not await check_redis():

                await init_redis()

                bot.redis_ready = (
                    True
                )


            event = (
                await pop_next_event(
                    timeout=5
                )
            )


            if event is None:

                continue


            await route_event_to_discord(

                bot,

                event,
            )


        except asyncio.CancelledError:

            raise


        except Exception as error:

            print(
                (
                    "EVENT WORKER ERROR | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )


            await asyncio.sleep(
                2
            )
