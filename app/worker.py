import asyncio
import hashlib

import discord

from app.affiliate import (
    AFFILIATE_DISCLOSURE,
    build_affiliate_url,
)

from app.config import (
    ALERT_ACCESS,
    CHANNEL_MAP,
)

from app.currency_service import (
    convert_currency,
    format_currency,
)

from app.event_service import (
    pop_next_event,
    save_alert_delivery,
)

from app.helpers import (
    safe_int,
)

from app.preference_service import (
    get_event_notification_role,
)

from app.redis_client import (
    check_redis,
    get_redis,
    init_redis,
)

from app.smart_cart import (
    build_smart_cart,
)

# =========================================================
# LOTUS EVENT WORKER
# PonDeX Trackers
# Version 1.0.0
#
# Compact alert layout
# Previous -> current price display
# Smart Cart v1 URL buttons
# Historical Pricing + Deal Score v2
# Persistent MSRP + Scalper Protection
# Preference-aware category pings
# Native currency + USD conversion
# Product images
# Affiliate links
# Source routing
# Game validation failsafe
# Realtime flicker protection
# =========================================================


EVENT_TITLES = {
    "DISCOVERED": "ð¡ PRODUCT DISCOVERED",
    "PAGE_LIVE": "ðµ PRODUCT PAGE LIVE",
    "COMING_SOON": "ð¡ COMING SOON",
    "PREORDER_LIVE": "ð£ PREORDER LIVE",
    "STOCK_AVAILABLE": "ð¢ IN STOCK",
    "RESTOCK": "ð¨ RESTOCK",
    "SOLD_OUT": "ð´ SOLD OUT",
    "PRICE_DROP": "ð¥ PRICE DROP",
    "PRICE_INCREASE": "ð PRICE INCREASE",
    "PRICE_ERROR": "â ï¸ POSSIBLE PRICE ERROR",
    "INVENTORY_FLICKER": "â¡ INVENTORY FLICKER",
    "RELEASE_DATE_CHANGED": "ð RELEASE DATE CHANGED",
    "QUEUE_DETECTED": "ð¨ POKÃMON CENTER QUEUE DETECTED",
    "QUEUE_ACTIVE": "ð¨ POKÃMON CENTER QUEUE LIVE",
    "QUEUE_CLEARED": "â POKÃMON CENTER QUEUE CLEARED",
}


# =========================================================
# WORKER GAME VALIDATION
#
# Second defense against incorrect role pings.
# =========================================================

def validate_event_game(event):
    game = (
        event.get("game")
        or ""
    )

    title = (
        event.get("product_name")
        or ""
    ).lower()

    product_type = (
        event.get("product_type")
        or ""
    ).lower()

    combined = (
        f"{title} "
        f"{product_type}"
    )

    # =====================================================
    # OBVIOUS NON-TARGET PRODUCTS
    # =====================================================

    obvious_other_products = [
        "warhammer",
        "games workshop",
        "star wars unlimited",
        "magic the gathering",
        "magic: the gathering",
        "flesh and blood",
        "yu-gi-oh",
        "yugioh",
        "lorcana",
        "digimon",
        "weiss schwarz",
        "union arena",
        "cyberpunk edgerunners",
        "combat zone",
        "miniatures",
        "board game",
        "boardgame",
    ]

    if game == "One Piece":
        for term in obvious_other_products:
            if term in combined:
                print(
                    (
                        "GAME VALIDATION REJECTED | "
                        "Assigned=One Piece | "
                        f"Product={event.get('product_name')} | "
                        f"Conflict={term}"
                    )
                )
                return False

    # =====================================================
    # POKEMON CONTRADICTIONS
    # =====================================================

    if game == "Pokemon":
        pokemon_conflicts = [
            "warhammer",
            "games workshop",
            "star wars unlimited",
            "magic the gathering",
            "magic: the gathering",
            "one piece card game",
            "gundam card game",
            "dragon ball fusion world",
        ]

        for term in pokemon_conflicts:
            if term in combined:
                print(
                    (
                        "GAME VALIDATION REJECTED | "
                        "Assigned=Pokemon | "
                        f"Product={event.get('product_name')} | "
                        f"Conflict={term}"
                    )
                )
                return False

    return True


# =========================================================
# ROUTING
# =========================================================

def determine_alert_route(event):
    event_type = (
        event.get("event_type")
        or ""
    )

    source_type = (
        event.get("source_type")
        or ""
    ).lower()

    if event_type in {
        "QUEUE_DETECTED",
        "QUEUE_ACTIVE",
        "QUEUE_CLEARED",
    }:
        return "pokemon_queue"

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
            return "page_live"

        if event_type == "PREORDER_LIVE":
            return "preorder"

        if event_type in {
            "PRICE_DROP",
            "PRICE_INCREASE",
            "PRICE_ERROR",
        }:
            return "deal"

        if event_type == "INVENTORY_FLICKER":
            return "inventory_flicker"

        if event_type == "RELEASE_DATE_CHANGED":
            return "release_radar"

        if event_type in {
            "STOCK_AVAILABLE",
            "RESTOCK",
            "SOLD_OUT",
        }:
            return "shopify"

        return None

    # =====================================================
    # POKEMON CENTER
    # =====================================================

    if source_type == "pokemon_center":
        if event_type == "PREORDER_LIVE":
            return "preorder"

        if event_type in {
            "DISCOVERED",
            "PAGE_LIVE",
            "COMING_SOON",
        }:
            return "page_live"

        if event_type in {
            "PRICE_DROP",
            "PRICE_INCREASE",
            "PRICE_ERROR",
        }:
            return "deal"

        if event_type == "INVENTORY_FLICKER":
            return "inventory_flicker"

        return "major_retailer"

    # =====================================================
    # MAJOR RETAILER
    # =====================================================

    if source_type == "major_retailer":
        if event_type == "PREORDER_LIVE":
            return "preorder"

        if event_type in {
            "DISCOVERED",
            "PAGE_LIVE",
            "COMING_SOON",
        }:
            return "page_live"

        if event_type in {
            "PRICE_DROP",
            "PRICE_INCREASE",
            "PRICE_ERROR",
        }:
            return "deal"

        if event_type == "INVENTORY_FLICKER":
            return "inventory_flicker"

        return "major_retailer"

    if source_type == "simulation":
        return "major_retailer"

    return None


# =========================================================
# DEDUPE
#
# Realtime events remain unsuppressed because rapid stock
# movement is useful intelligence for Inventory Flicker.
# =========================================================

REALTIME_EVENTS = {
    "RESTOCK",
    "SOLD_OUT",
    "INVENTORY_FLICKER",
    "QUEUE_DETECTED",
    "QUEUE_ACTIVE",
    "QUEUE_CLEARED",
}


async def should_suppress_duplicate(event):
    if (
        event.get("event_type")
        in REALTIME_EVENTS
    ):
        return False

    redis_client = get_redis()

    if redis_client is None:
        return False

    identity = "|".join(
        [
            str(
                event.get(
                    "event_type",
                    "",
                )
            ),
            str(
                event.get(
                    "source_type",
                    "",
                )
            ),
            str(
                event.get(
                    "game",
                    "",
                )
            ),
            str(
                event.get(
                    "store_name",
                    "",
                )
            ),
            str(
                event.get(
                    "product_url",
                    "",
                )
            ),
            str(
                event.get(
                    "price",
                    "",
                )
            ),
            str(
                event.get(
                    "currency",
                    "",
                )
            ),
            str(
                event.get(
                    "product_category",
                    "",
                )
            ),
        ]
    )

    digest = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()

    try:
        result = await redis_client.set(
            (
                "lotus:dedupe:"
                + digest
            ),
            "1",
            nx=True,
            ex=120,
        )

        return result is None

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
# DISPLAY HELPERS
# =========================================================

def _pretty_text(value):
    if value is None:
        return ""

    return (
        str(value)
        .replace("_", " ")
        .strip()
        .title()
    )


def _region_display(region):
    if not region:
        return None

    region_upper = (
        str(region)
        .strip()
        .upper()
    )

    region_flags = {
        "US": "ðºð¸",
        "USA": "ðºð¸",
        "CA": "ð¨ð¦",
        "CAN": "ð¨ð¦",
        "CANADA": "ð¨ð¦",
        "UK": "ð¬ð§",
        "GB": "ð¬ð§",
        "GBR": "ð¬ð§",
        "JP": "ð¯ðµ",
        "JPN": "ð¯ðµ",
        "JAPAN": "ð¯ðµ",
        "EU": "ðªðº",
        "AU": "ð¦ðº",
        "AUS": "ð¦ðº",
        "NZ": "ð³ð¿",
    }

    flag = region_flags.get(
        region_upper,
        "ð",
    )

    return (
        f"{flag} "
        f"**{region_upper}**"
    )


def _game_display(game):
    if not game:
        return None

    game_icons = {
        "One Piece": "ð´ââ ï¸",
        "Pokemon": "â¡",
        "PokÃ©mon": "â¡",
        "Magic: The Gathering": "ð§",
        "MTG": "ð§",
        "Riftbound": "âï¸",
        "Gundam": "ð¤",
        "Dragon Ball": "ð",
        "LEGO": "ð§±",
        "Video Games": "ð®",
        "Board Games": "ð²",
    }

    icon = game_icons.get(
        game,
        "ð´",
    )

    return (
        f"{icon} "
        f"**{game}**"
    )


def _source_label(source_type):
    labels = {
        "shopify": "Shopify â¢ TCG Store",
        "major_retailer": "Major Retailer",
        "pokemon_center": "PokÃ©mon Center",
        "queue": "Queue Intelligence",
        "simulation": "Simulation",
    }

    return labels.get(
        source_type,
        _pretty_text(source_type)
        or "Unknown Source",
    )


# =========================================================
# EMBED
# =========================================================

async def build_event_embed(event):
    event_type = (
        event.get(
            "event_type",
            "UNKNOWN",
        )
    )

    product_name = (
        event.get("product_name")
        or "Unknown Product"
    )

    store_name = (
        event.get("store_name")
        or "Unknown Store"
    )

    product_url = (
        event.get("product_url")
        or ""
    )

    final_url, affiliate_used = (
        build_affiliate_url(
            product_url,
            store_name,
        )
    )

    game = (
        event.get("game")
        or ""
    )

    product_category = (
        event.get("product_category")
        or "UNKNOWN"
    )

    product_type = (
        event.get("product_type")
        or ""
    )

    region = (
        event.get("region")
        or ""
    )

    source_type = (
        event.get("source_type")
        or "unknown"
    ).lower()

    price = event.get("price")
    old_price = event.get("old_price")

    currency = (
        event.get("currency")
        or "USD"
    ).upper()

    purchase_limit = (
        event.get("purchase_limit")
    )

    # =====================================================
    # CREATE EMBED
    # =====================================================

    embed = discord.Embed(
        title=(
            EVENT_TITLES.get(
                event_type,
                "ð¡ LOTUS PRODUCT EVENT",
            )
        ),
        description=(
            f"**{product_name}**"
        ),
        url=(
            final_url
            or None
        ),
    )

    # =====================================================
    # PRODUCT IMAGE
    # =====================================================

    image_url = event.get(
        "image_url"
    )

    if image_url:
        embed.set_thumbnail(
            url=image_url
        )

    # =====================================================
    # PRICE
    #
    # PRICE CHANGE:
    #
    # C$34.99 â C$39.33
    # ð +C$4.34 â¢ +12.4%
    # â US$28.37
    #
    # NORMAL:
    #
    # C$39.33
    # â US$28.37
    # =====================================================

    if price is not None:
        native_text = format_currency(
            price,
            currency,
        )

        price_lines = []

        is_price_change = (
            event_type
            in {
                "PRICE_DROP",
                "PRICE_INCREASE",
                "PRICE_ERROR",
            }
        )

        if (
            is_price_change
            and old_price is not None
        ):
            try:
                old_value = float(
                    old_price
                )

                new_value = float(
                    price
                )

                old_text = (
                    format_currency(
                        old_value,
                        currency,
                    )
                )

                difference = (
                    new_value
                    - old_value
                )

                percentage = (
                    (
                        difference
                        / old_value
                    )
                    * 100
                    if old_value != 0
                    else 0.0
                )

                difference_text = (
                    format_currency(
                        abs(difference),
                        currency,
                    )
                )

                if difference < 0:
                    price_lines.append(
                        (
                            f"**{old_text} â "
                            f"{native_text}**"
                        )
                    )

                    price_lines.append(
                        (
                            "ð¥ Save "
                            f"**{difference_text}** "
                            "â¢ "
                            f"**{abs(percentage):.1f}%**"
                        )
                    )

                elif difference > 0:
                    price_lines.append(
                        (
                            f"**{old_text} â "
                            f"{native_text}**"
                        )
                    )

                    price_lines.append(
                        (
                            "ð +"
                            f"**{difference_text}** "
                            "â¢ "
                            f"**+{percentage:.1f}%**"
                        )
                    )

                else:
                    price_lines.append(
                        f"**{native_text}**"
                    )

            except (
                TypeError,
                ValueError,
            ):
                price_lines.append(
                    f"**{native_text}**"
                )

        else:
            price_lines.append(
                f"**{native_text}**"
            )

        # =================================================
        # USD CONVERSION
        # =================================================

        if currency != "USD":
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

                price_lines.append(
                    f"â **{usd_text}**"
                )

        embed.add_field(
            name="ð° Price",
            value="\n".join(
                price_lines
            ),
            inline=False,
        )

    # =====================================================
    # PRICE INTELLIGENCE / DEAL SCORE / MSRP
    # =====================================================

    deal_score = (
        event.get(
            "deal_score"
        )
    )

    deal_label = (
        event.get(
            "deal_label"
        )
    )

    deal_confidence = (
        event.get(
            "deal_confidence"
        )
    )

    history_samples = (
        event.get(
            "price_history_samples"
        )
        or 0
    )

    history_low = (
        event.get(
            "price_30d_low"
        )
    )

    history_average = (
        event.get(
            "price_30d_average"
        )
    )

    vs_average_pct = (
        event.get(
            "price_vs_average_pct"
        )
    )

    vs_low_pct = (
        event.get(
            "price_vs_low_pct"
        )
    )

    msrp = (
        event.get(
            "msrp"
        )
    )

    msrp_currency = (
        event.get(
            "msrp_currency"
        )
        or currency
    )

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

    msrp_original = (
        event.get(
            "msrp_original"
        )
    )

    msrp_original_currency = (
        event.get(
            "msrp_original_currency"
        )
    )

    msrp_conversion_used = bool(
        event.get(
            "msrp_conversion_used"
        )
    )

    vs_msrp_pct = (
        event.get(
            "price_vs_msrp_pct"
        )
    )

    markup_amount = (
        event.get(
            "markup_amount"
        )
    )

    msrp_price_state = (
        event.get(
            "msrp_price_state"
        )
    )

    scalper_risk = (
        event.get(
            "scalper_risk"
        )
    )

    show_price_intelligence = (
        deal_score is not None
        or msrp is not None
        or history_samples >= 2
    )

    if show_price_intelligence:

        intelligence_lines = []

        # =================================================
        # HISTORICAL PRICE DATA
        # =================================================

        if history_low is not None:

            intelligence_lines.append(
                (
                    "30-day low: "
                    f"**{format_currency(history_low, currency)}**"
                )
            )

        if history_average is not None:

            intelligence_lines.append(
                (
                    "30-day average: "
                    f"**{format_currency(history_average, currency)}**"
                )
            )

        if vs_average_pct is not None:

            average_sign = (
                "+"
                if vs_average_pct > 0
                else ""
            )

            intelligence_lines.append(
                (
                    "Current vs average: "
                    f"**{average_sign}{vs_average_pct:.1f}%**"
                )
            )

        if (
            vs_low_pct is not None
            and abs(
                float(
                    vs_low_pct
                )
            )
            <= 0.10
        ):

            intelligence_lines.append(
                "ð **At the 30-day low**"
            )

        # =================================================
        # MSRP / REFERENCE PRICE
        # =================================================

        if msrp is not None:

            # If conversion was required, preserve and show
            # the original verified reference first.

            if (
                msrp_conversion_used
                and msrp_original is not None
                and msrp_original_currency
            ):

                intelligence_lines.append(
                    (
                        "ð·ï¸ MSRP: "
                        f"**{format_currency(msrp_original, msrp_original_currency)}**"
                    )
                )

                intelligence_lines.append(
                    (
                        "Converted reference: "
                        f"â **{format_currency(msrp, msrp_currency)}**"
                    )
                )

            else:

                intelligence_lines.append(
                    (
                        "ð·ï¸ MSRP: "
                        f"**{format_currency(msrp, msrp_currency)}**"
                    )
                )

            if msrp_source:

                source_text = str(msrp_source).strip()

                if msrp_confidence:
                    source_text += (
                        " â¢ "
                        f"{str(msrp_confidence).upper()} confidence"
                    )

                intelligence_lines.append(
                    f"Reference: **{source_text}**"
                )

            if vs_msrp_pct is not None:

                if msrp_price_state == "BELOW_MSRP":

                    intelligence_lines.append(
                        (
                            "ð¥ Current vs MSRP: "
                            f"**{abs(float(vs_msrp_pct)):.1f}% below**"
                        )
                    )

                elif msrp_price_state == "AT_MSRP":

                    intelligence_lines.append(
                        "â **At MSRP**"
                    )

                else:

                    intelligence_lines.append(
                        (
                            "â ï¸ Current vs MSRP: "
                            f"**+{float(vs_msrp_pct):.1f}%**"
                        )
                    )

            if (
                markup_amount is not None
                and float(markup_amount) > 0
            ):

                intelligence_lines.append(
                    (
                        "Markup: "
                        f"**+{format_currency(markup_amount, msrp_currency)}**"
                    )
                )

        # =================================================
        # SCALPER PROTECTION
        # =================================================

        risk_icons = {
            "NONE":
                "ð¢",

            "LOW":
                "ð¡",

            "MODERATE":
                "â ï¸",

            "HIGH":
                "ð¨",

            "EXTREME":
                "ð",
        }

        if scalper_risk:

            risk_upper = (
                str(
                    scalper_risk
                )
                .upper()
            )

            intelligence_lines.append(
                (
                    f"{risk_icons.get(risk_upper, 'ð¡ï¸')} "
                    "**Scalper Risk: "
                    f"{risk_upper}**"
                )
            )

        # =================================================
        # FINAL DEAL SCORE
        # =================================================

        label_icons = {
            "Excellent Deal":
                "ð¥",

            "Good Deal":
                "â",

            "Fair Price":
                "â",

            "Above Average":
                "â ï¸",

            "Marked Up":
                "â ï¸",

            "High Markup":
                "ð¨",

            "Extreme Markup":
                "ð",

            "Normal Price":
                "â¹ï¸",
        }

        label_icon = (
            label_icons.get(
                deal_label,
                "â­",
            )
        )

        score_text = (
            f"{float(deal_score):.1f}/10"
        )

        if deal_label:

            intelligence_lines.append(
                (
                    f"{label_icon} **Deal Score: "
                    f"{score_text} â "
                    f"{deal_label}**"
                )
            )

        else:

            intelligence_lines.append(
                (
                    "â­ **Deal Score: "
                    f"{score_text}**"
                )
            )

        # =================================================
        # CONFIDENCE / SOURCE
        # =================================================

        confidence_parts = []

        if deal_confidence:

            confidence_parts.append(
                (
                    "History confidence: "
                    f"**{str(deal_confidence).upper()}**"
                )
            )

        if history_samples:

            confidence_parts.append(
                (
                    f"{history_samples} "
                    + (
                        "observation"
                        if history_samples == 1
                        else "observations"
                    )
                )
            )

        if (
            msrp is not None
            and msrp_confidence
        ):

            confidence_parts.append(
                (
                    "MSRP confidence: "
                    f"**{str(msrp_confidence).upper()}**"
                )
            )

        if confidence_parts:

            intelligence_lines.append(
                " â¢ ".join(
                    confidence_parts
                )
            )

        if (
            msrp is not None
            and msrp_source
        ):

            intelligence_lines.append(
                (
                    "Reference: "
                    f"{msrp_source}"
                )
            )

        embed.add_field(
            name="ð Price Intelligence",
            value="\n".join(
                intelligence_lines
            ),
            inline=False,
        )

    # =====================================================
    # STORE + REGION
    #
    # ðª Hobbiesville â¢ ð¨ð¦ CA
    # =====================================================

    store_parts = [
        f"ðª **{store_name}**"
    ]

    region_text = (
        _region_display(
            region
        )
    )

    if region_text:
        store_parts.append(
            region_text
        )

    embed.add_field(
        name="\u200b",
        value=" â¢ ".join(
            store_parts
        ),
        inline=False,
    )

    # =====================================================
    # GAME + CATEGORY / TYPE
    #
    # ð´ââ ï¸ One Piece â¢ ð Single
    # =====================================================

    product_parts = []

    game_text = (
        _game_display(
            game
        )
    )

    if game_text:
        product_parts.append(
            game_text
        )

    category_display = None

    if (
        product_category
        and str(
            product_category
        ).upper() != "UNKNOWN"
    ):
        category_display = (
            _pretty_text(
                product_category
            )
        )

    type_display = (
        _pretty_text(
            product_type
        )
        if product_type
        else None
    )

    if category_display:
        product_parts.append(
            f"ð {category_display}"
        )

    if (
        type_display
        and (
            not category_display
            or (
                type_display.lower()
                != category_display.lower()
            )
        )
    ):
        product_parts.append(
            type_display
        )

    if product_parts:
        embed.add_field(
            name="\u200b",
            value=" â¢ ".join(
                product_parts
            ),
            inline=False,
        )

    # =====================================================
    # STOCK / AVAILABILITY
    # =====================================================

    if event_type in {
        "STOCK_AVAILABLE",
        "RESTOCK",
        "SOLD_OUT",
        "INVENTORY_FLICKER",
    }:
        in_stock = bool(
            event.get("in_stock")
        )

        if in_stock:
            stock_text = (
                "ð¢ **IN STOCK**"
            )
        else:
            stock_text = (
                "ð´ **OUT OF STOCK**"
            )

        if event_type == "INVENTORY_FLICKER":
            if in_stock:
                stock_text += (
                    "\nâ¡ Brief inventory activity "
                    "detected â¢ checkout quickly"
                )
            else:
                stock_text += (
                    "\nâ¡ Rapid inventory movement "
                    "detected"
                )

        embed.add_field(
            name="ð¦ Status",
            value=stock_text,
            inline=False,
        )

    # =====================================================
    # SMART CART
    #
    # Actual cart/product actions are rendered as Discord
    # URL buttons by route_event_to_discord().
    # =====================================================

    smart_cart = (
        build_smart_cart(
            event,
            product_url=(
                final_url
            ),
        )
    )

    embed.add_field(
        name="ð Smart Cart",
        value=(
            smart_cart.status_text
        ),
        inline=False,
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
    # COMPACT FOOTER
    # =====================================================

    footer_parts = [
        "Lotus Tracker Bot",
        _source_label(
            source_type
        ),
    ]

    if (
        currency != "USD"
        and price is not None
    ):
        footer_parts.append(
            "USD conversion approximate"
        )

    embed.set_footer(
        text=" â¢ ".join(
            footer_parts
        )
    )

    return (
        embed,
        affiliate_used,
        smart_cart,
    )


# =========================================================
# GUILD
# =========================================================

def get_primary_guild(bot):
    if not bot.guilds:
        return None

    return bot.guilds[0]


# =========================================================
# ROUTE EVENT
# =========================================================

async def route_event_to_discord(
    bot,
    event,
):
    # =====================================================
    # GAME SAFETY CHECK BEFORE ROLE PING
    # =====================================================

    if not validate_event_game(
        event
    ):
        print(
            (
                "EVENT BLOCKED BY GAME VALIDATION | "
                f"Game={event.get('game')} | "
                f"Product={event.get('product_name')}"
            )
        )

        return False

    alert_type = (
        determine_alert_route(
            event
        )
    )

    if not alert_type:
        print(
            (
                "EVENT NOT ROUTED | "
                f"Event={event.get('event_type')} | "
                f"Source={event.get('source_type')} | "
                f"Game={event.get('game')} | "
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
        return False

    channel_id = safe_int(
        CHANNEL_MAP.get(
            access[
                "channel_variable"
            ]
        )
    )

    if not channel_id:
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
        return False

    # =====================================================
    # PREFERENCE-AWARE PRODUCT ALERT ROLE
    # =====================================================

    game = event.get(
        "game"
    )

    product_category = (
        event.get(
            "product_category"
        )
        or "UNKNOWN"
    ).upper()

    role = (
        get_event_notification_role(
            guild,
            game,
            product_category,
        )
    )

    print(
        (
            "ALERT ROLE ROUTING | "
            f"Game={game} | "
            f"Category={product_category} | "
            f"Role={role.name if role else 'NONE'}"
        )
    )

    (
        embed,
        affiliate_used,
        smart_cart,
    ) = (
        await build_event_embed(
            event
        )
    )

    # =====================================================
    # SMART CART BUTTONS
    #
    # Discord link buttons do not require an interaction
    # callback. They simply open the generated retailer URL.
    # =====================================================

    view = None

    if smart_cart.actions:
        view = discord.ui.View(
            timeout=None
        )

        for action in smart_cart.actions:
            if action.kind == "cart":
                button_style = (
                    discord.ButtonStyle.success
                )
                emoji = "ð"
            else:
                button_style = (
                    discord.ButtonStyle.link
                )
                emoji = "ð"

            # URL buttons must use ButtonStyle.link.
            # Discord does not allow success/primary styles
            # on buttons that navigate directly to a URL.
            button_style = (
                discord.ButtonStyle.link
            )

            view.add_item(
                discord.ui.Button(
                    label=(
                        action.label
                    ),
                    url=(
                        action.url
                    ),
                    style=(
                        button_style
                    ),
                    emoji=(
                        emoji
                    ),
                )
            )

    # =====================================================
    # SEND WITH RETRIES
    # =====================================================

    message = None

    for attempt in range(
        1,
        4,
    ):
        try:
            message = (
                await channel.send(
                    content=(
                        role.mention
                        if role
                        else None
                    ),
                    embed=embed,
                    view=view,
                    allowed_mentions=(
                        discord.AllowedMentions(
                            roles=True,
                            users=False,
                            everyone=False,
                        )
                    ),
                )
            )

            break

        except discord.DiscordServerError as error:
            print(
                (
                    "DISCORD TEMPORARY ERROR | "
                    f"Attempt={attempt}/3 | "
                    f"{error}"
                )
            )

            if attempt < 3:
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

            return False

    if message is None:
        return False

    await save_alert_delivery(
        alert_type=alert_type,
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

    print(
        (
            "ALERT SENT | "
            f"Event={event.get('event_type')} | "
            f"Game={event.get('game')} | "
            f"Store={event.get('store_name')} | "
            f"Category={event.get('product_category')} | "
            f"Route={alert_type} | "
            f"Channel={channel.name} | "
            f"Currency={event.get('currency')} | "
            f"OldPrice={event.get('old_price')} | "
            f"Price={event.get('price')} | "
            f"Image={bool(event.get('image_url'))} | "
            f"Affiliate={affiliate_used} | "
            f"SmartCart={smart_cart.supported} | "
            f"SmartCartActions={len(smart_cart.actions)} | "
            f"DealScore={event.get('deal_score')} | "
            f"DealConfidence={event.get('deal_confidence')} | "
            f"HistorySamples={event.get('price_history_samples')} | "
            f"MSRP={event.get('msrp')} | "
            f"OriginalMSRP={event.get('msrp_original')} | "
            f"MSRPConverted={event.get('msrp_conversion_used')} | "
            f"VsMSRP={event.get('price_vs_msrp_pct')} | "
            f"ScalperRisk={event.get('scalper_risk')}"
        )
    )

    return True


# =========================================================
# WORKER
# =========================================================

async def run_event_worker(bot):
    await bot.wait_until_ready()

    print(
        "Lotus Event Worker v1.0.0 started."
    )

    while not bot.is_closed():
        try:
            if not await check_redis():
                await init_redis()
                bot.redis_ready = True

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
