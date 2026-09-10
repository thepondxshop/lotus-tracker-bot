import asyncio
import hashlib
import time

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

from app.helpers import (
    safe_int,
    get_subscription,
    tier_allows,
)

from app.preference_service import (
    get_product_preferences,
)

from app.family_preference_service import (
    get_family_preferences,
)

from app.alert_preference_service import (
    member_allows_alert,
)

from app.redis_client import (
    check_redis,
    get_redis,
    init_redis,
)

# =========================================================
# LOTUS EVENT WORKER
# PonDeX Trackers
# Version 1.0.6
#
# Compact alert layout
# Previous -> current price display
# Smart Cart presentation
# Native currency + USD conversion
# Product images
# Affiliate links
# Source routing
# Game validation failsafe
# Realtime flicker protection
# Step 6K-2C2 legacy preference compatibility
# =========================================================


EVENT_TITLES = {
    "DISCOVERED": "📡 PRODUCT DISCOVERED",
    "PAGE_LIVE": "🔵 PRODUCT PAGE LIVE",
    "COMING_SOON": "🟡 COMING SOON",
    "PREORDER_LIVE": "🟣 PREORDER LIVE",
    "STOCK_AVAILABLE": "🟢 IN STOCK",
    "RESTOCK": "🚨 RESTOCK",
    "SOLD_OUT": "🔴 SOLD OUT",
    "PRICE_DROP": "🔥 PRICE DROP",
    "PRICE_INCREASE": "📈 PRICE INCREASE",
    "PRICE_ERROR": "⚠️ POSSIBLE PRICE ERROR",
    "INVENTORY_FLICKER": "⚡ INVENTORY FLICKER",
    "RELEASE_DATE_CHANGED": "📅 RELEASE DATE CHANGED",
    "QUEUE_DETECTED": "🚨 POKÉMON CENTER QUEUE DETECTED",
    "QUEUE_ACTIVE": "🚨 POKÉMON CENTER QUEUE LIVE",
    "QUEUE_CLEARED": "✅ POKÉMON CENTER QUEUE CLEARED",
}


# Existing members may predate the product/family preference rows introduced
# by the newer member-level notification system.  Missing keys must use the
# same defaults shown by the slash commands instead of silently becoming OFF.
DEFAULT_PRODUCT_PREFERENCES = {
    "SEALED": True,
    "SINGLE": False,
    "ACCESSORY": False,
    "UNKNOWN": True,
}

DEFAULT_FAMILY_PREFERENCES = {
    "GLOBAL_STANDARD": True,
    "JP": False,
    "KR": False,
    "CN": False,
    "UNKNOWN": False,
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
    #
    # International major-retailer events are Premium and route through
    # the International channel. The member preference layer then requires
    # BOTH the INTERNATIONAL switch and the event-specific switch.
    # =====================================================

    if source_type == "major_retailer":
        region = str(event.get("region") or "US").strip().upper()
        is_international = region not in {"US", "USA", "UNITED STATES"}

        # Premium+ routes remain Premium+ even for international stores.
        if event_type == "INVENTORY_FLICKER":
            return "inventory_flicker"

        if event_type == "RELEASE_DATE_CHANGED":
            return "release_radar"

        if is_international:
            return "international"

        if event_type == "PREORDER_LIVE":
            return "preorder"

        if event_type in {
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

        # Major-retailer discoveries and verified online stock lifecycle
        # events are part of the Free major-retailer route.
        if event_type in {
            "DISCOVERED",
            "STOCK_AVAILABLE",
            "RESTOCK",
            "SOLD_OUT",
        }:
            return "major_retailer"

        return None

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
        "US": "🇺🇸",
        "USA": "🇺🇸",
        "CA": "🇨🇦",
        "CAN": "🇨🇦",
        "CANADA": "🇨🇦",
        "UK": "🇬🇧",
        "GB": "🇬🇧",
        "GBR": "🇬🇧",
        "JP": "🇯🇵",
        "JPN": "🇯🇵",
        "JAPAN": "🇯🇵",
        "EU": "🇪🇺",
        "AU": "🇦🇺",
        "AUS": "🇦🇺",
        "NZ": "🇳🇿",
    }

    flag = region_flags.get(
        region_upper,
        "🌎",
    )

    return (
        f"{flag} "
        f"**{region_upper}**"
    )


def _game_display(game):
    if not game:
        return None

    game_icons = {
        "One Piece": "🏴‍☠️",
        "Pokemon": "⚡",
        "Pokémon": "⚡",
        "Magic: The Gathering": "🧙",
        "MTG": "🧙",
        "Riftbound": "⚔️",
        "Gundam": "🤖",
        "Dragon Ball": "🐉",
        "LEGO": "🧱",
        "Video Games": "🎮",
        "Board Games": "🎲",
    }

    icon = game_icons.get(
        game,
        "🎴",
    )

    return (
        f"{icon} "
        f"**{game}**"
    )


def _source_label(source_type):
    labels = {
        "shopify": "Shopify • TCG Store",
        "major_retailer": "Major Retailer",
        "pokemon_center": "Pokémon Center",
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
                "📡 LOTUS PRODUCT EVENT",
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
    # C$34.99 → C$39.33
    # 📈 +C$4.34 • +12.4%
    # ≈ US$28.37
    #
    # NORMAL:
    #
    # C$39.33
    # ≈ US$28.37
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
                            f"**{old_text} → "
                            f"{native_text}**"
                        )
                    )

                    price_lines.append(
                        (
                            "🔥 Save "
                            f"**{difference_text}** "
                            "• "
                            f"**{abs(percentage):.1f}%**"
                        )
                    )

                elif difference > 0:
                    price_lines.append(
                        (
                            f"**{old_text} → "
                            f"{native_text}**"
                        )
                    )

                    price_lines.append(
                        (
                            "📈 +"
                            f"**{difference_text}** "
                            "• "
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
                    f"≈ **{usd_text}**"
                )

        embed.add_field(
            name="💰 Price",
            value="\n".join(
                price_lines
            ),
            inline=False,
        )

    # =====================================================
    # STORE + REGION
    #
    # 🏪 Hobbiesville • 🇨🇦 CA
    # =====================================================

    store_parts = [
        f"🏪 **{store_name}**"
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
        value=" • ".join(
            store_parts
        ),
        inline=False,
    )

    # =====================================================
    # GAME + CATEGORY / TYPE
    #
    # 🏴‍☠️ One Piece • 🃏 Single
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
            f"🃏 {category_display}"
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
            value=" • ".join(
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
                "🟢 **IN STOCK**"
            )
        else:
            stock_text = (
                "🔴 **OUT OF STOCK**"
            )

        if event_type == "INVENTORY_FLICKER":
            if in_stock:
                stock_text += (
                    "\n⚡ Brief inventory activity "
                    "detected • checkout quickly"
                )
            else:
                stock_text += (
                    "\n⚡ Rapid inventory movement "
                    "detected"
                )

        embed.add_field(
            name="📦 Status",
            value=stock_text,
            inline=False,
        )

    # =====================================================
    # SMART CART
    # =====================================================

    if purchase_limit:
        try:
            limit_number = int(
                purchase_limit
            )

            smart_cart_text = (
                "Detected retailer limit: "
                f"**{limit_number}**"
            )

        except (
            TypeError,
            ValueError,
        ):
            smart_cart_text = (
                "Detected retailer limit: "
                f"**{purchase_limit}**"
            )

    else:
        smart_cart_text = (
            "Limit not detected • "
            "retailer may adjust quantity"
        )

    embed.add_field(
        name="🛒 Smart Cart",
        value=smart_cart_text,
        inline=False,
    )

    # =====================================================
    # QUICK LINK
    # =====================================================

    if final_url:
        embed.add_field(
            name="🔗 Quick Link",
            value=(
                f"[**Open Product**]"
                f"({final_url})"
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
        text=" • ".join(
            footer_parts
        )
    )

    return (
        embed,
        affiliate_used,
    )


# =========================================================
# GUILD
# =========================================================

def get_primary_guild(bot):
    if not bot.guilds:
        return None

    return bot.guilds[0]


# =========================================================
# MEMBER-LEVEL NOTIFICATION ELIGIBILITY
# Step 6K-2B
# =========================================================

def get_game_members(guild, game):
    if not game:
        return []
    role_id = safe_int(GAME_ROLES.get(game))
    if not role_id:
        return []
    role = guild.get_role(role_id)
    if role is None:
        return []
    return [member for member in role.members if not member.bot]


def _normalize_category(value):
    if value is None:
        return None
    raw = str(value).strip().upper()
    aliases = {
        "SEALED": "SEALED",
        "SINGLE": "SINGLE",
        "SINGLES": "SINGLE",
        "ACCESSORY": "ACCESSORY",
        "ACCESSORIES": "ACCESSORY",
        "UNKNOWN": "UNKNOWN",
    }
    return aliases.get(raw, "UNKNOWN")


def _normalize_family(value):
    if value is None:
        return None
    raw = str(value).strip().upper()
    aliases = {
        "GLOBAL": "GLOBAL_STANDARD",
        "ENGLISH": "GLOBAL_STANDARD",
        "GLOBAL_STANDARD": "GLOBAL_STANDARD",
        "JP": "JP",
        "JAPAN": "JP",
        "JAPANESE": "JP",
        "KR": "KR",
        "KOREA": "KR",
        "KOREAN": "KR",
        "CN": "CN",
        "CHINA": "CN",
        "CHINESE": "CN",
        "SIMPLIFIED_CHINESE": "CN",
        "UNKNOWN": "UNKNOWN",
    }
    return aliases.get(raw, "UNKNOWN")


async def get_eligible_members(guild, event, alert_type, minimum_tier):
    game = event.get("game")
    if not game:
        return []

    base_members = get_game_members(guild, game)
    if not base_members:
        return []

    event_type = str(event.get("event_type") or "").upper()
    is_queue_event = event_type in {
        "QUEUE_DETECTED", "QUEUE_ACTIVE", "QUEUE_CLEARED"
    }
    category = _normalize_category(event.get("product_category"))
    family = _normalize_family(event.get("product_family"))
    eligible = []
    rejected_tier = 0
    rejected_alert_preference = 0
    rejected_product_preference = 0
    rejected_family_preference = 0
    preference_errors = 0

    async def check_member(member):
        nonlocal rejected_tier, rejected_alert_preference, rejected_product_preference
        nonlocal rejected_family_preference, preference_errors
        try:
            tier = get_subscription(member)

            # Route entitlement remains authoritative even if a stored user
            # preference is stale or manually manipulated.
            if not tier_allows(tier, minimum_tier):
                rejected_tier += 1
                return

            if not await member_allows_alert(
                discord_user_id=member.id,
                game=game,
                event_type=event_type,
                alert_route=alert_type,
                tier=tier,
                region=event.get("region"),
            ):
                rejected_alert_preference += 1
                return

            # Queue alerts are not product-category/family events.
            if not is_queue_event:
                if category is not None:
                    product_preferences = await get_product_preferences(
                        member.id,
                        game,
                    )
                    product_default = DEFAULT_PRODUCT_PREFERENCES.get(
                        category,
                        False,
                    )
                    if not bool(product_preferences.get(category, product_default)):
                        rejected_product_preference += 1
                        return

                if family is not None:
                    family_preferences = await get_family_preferences(
                        member.id,
                        game,
                    )
                    family_default = DEFAULT_FAMILY_PREFERENCES.get(
                        family,
                        False,
                    )
                    if not bool(family_preferences.get(family, family_default)):
                        rejected_family_preference += 1
                        return

            eligible.append(member)

        except Exception as error:
            # Fail closed for pings: the channel alert can still be posted,
            # but a member is not pinged when entitlement/preferences cannot
            # be verified.
            print(
                "MEMBER ALERT PREF ERROR | "
                f"User={getattr(member, 'id', None)} | "
                f"Game={game} | Event={event_type} | "
                f"{type(error).__name__}: {error}"
            )
            preference_errors += 1

    for offset in range(0, len(base_members), 4):
        await asyncio.gather(*(check_member(member) for member in base_members[offset:offset + 4]))
    eligible_ids = {member.id for member in eligible}
    eligible = [member for member in base_members if member.id in eligible_ids]

    print(
        "MEMBER ALERT ELIGIBILITY | "
        f"Game={game} | Event={event_type} | Route={alert_type} | "
        f"GameMembers={len(base_members)} | Eligible={len(eligible)} | "
        f"TierBlocked={rejected_tier} | "
        f"AlertPrefBlocked={rejected_alert_preference} | "
        f"ProductPrefBlocked={rejected_product_preference} | "
        f"FamilyPrefBlocked={rejected_family_preference} | "
        f"Errors={preference_errors}"
    )

    return eligible


def build_mention_chunks(members, max_length=1800):
    chunks = []
    current = []
    for member in members:
        mention = member.mention
        candidate = " ".join(current + [mention])
        if len(candidate) > max_length and current:
            chunks.append(" ".join(current))
            current = [mention]
        else:
            current.append(mention)
    if current:
        chunks.append(" ".join(current))
    return chunks


# =========================================================
# ROUTE EVENT
# =========================================================

async def route_event_to_discord(
    bot,
    event,
):
    dispatch_started = time.monotonic()
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
    # MEMBER-LEVEL ELIGIBILITY
    # Tier + game + product type + family + alert toggle
    # =====================================================

    game = event.get("game")
    minimum_tier = access.get("minimum_tier", "Free")

    eligible_members = await get_eligible_members(
        guild,
        event,
        alert_type,
        minimum_tier,
    )
    mention_chunks = build_mention_chunks(eligible_members)

    embed, affiliate_used = (
        await build_event_embed(
            event
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
                        mention_chunks[0]
                        if mention_chunks
                        else None
                    ),
                    embed=embed,
                    allowed_mentions=(
                        discord.AllowedMentions(
                            roles=False,
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

    # Large servers can exceed one Discord content field. Additional chunks
    # contain mentions only; the product embed is posted once.
    for mention_chunk in mention_chunks[1:]:
        try:
            await channel.send(
                content=mention_chunk,
                allowed_mentions=discord.AllowedMentions(
                    roles=False,
                    users=True,
                    everyone=False,
                ),
            )
        except Exception as error:
            print(
                "DISCORD MENTION CHUNK ERROR | "
                f"{type(error).__name__}: {error}"
            )

    print(f"LOTUS DISPATCH TIMING | Event={event.get('event_type')} | "
          f"Store={event.get('store_name')} | "
          f"DispatchSeconds={time.monotonic() - dispatch_started:.3f} | "
          f"EligibleMentions={len(eligible_members)}")
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
            f"EligibleMentions={len(eligible_members)}"
        )
    )

    return True


# =========================================================
# WORKER
# =========================================================

async def run_event_worker(bot):
    await bot.wait_until_ready()

    print(
        "Lotus Event Worker v1.0.6 / 6K-2C3 started."
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
