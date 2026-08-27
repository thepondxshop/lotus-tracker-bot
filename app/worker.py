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
# Version 0.8.0
#
# Compact alert layout
# Previous -> current price display
# Smart Cart v1 URL buttons
# Native currency + USD conversion
# Product images
# Affiliate links
# Source routing
# Game validation failsafe
# Realtime flicker protection
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
        name="🛒 Smart Cart",
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
        text=" • ".join(
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
    # GAME ROLE
    # =====================================================

    game = event.get(
        "game"
    )

    role_id = safe_int(
        GAME_ROLES.get(
            game
        )
    )

    role = (
        guild.get_role(
            role_id
        )
        if role_id
        else None
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
                emoji = "🛒"
            else:
                button_style = (
                    discord.ButtonStyle.link
                )
                emoji = "🔗"

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
                        else (
                            f"**{game}**"
                            if game
                            else None
                        )
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
            f"SmartCartActions={len(smart_cart.actions)}"
        )
    )

    return True


# =========================================================
# WORKER
# =========================================================

async def run_event_worker(bot):
    await bot.wait_until_ready()

    print(
        "Lotus Event Worker v0.8.0 started."
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
