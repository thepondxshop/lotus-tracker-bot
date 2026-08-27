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


# =========================================================
# LOTUS EVENT WORKER
# PonDeX Trackers
# Version 0.7.6a
#
# Source-first routing
# Shopify isolation
# Product thumbnails
# Affiliate links
# Safe handling of legacy events
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
# ROUTING
# =========================================================

def determine_alert_route(
    event: dict,
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
    )

    source_type = (
        source_type.lower()
    )

    # =====================================================
    # QUEUE INTELLIGENCE
    # =====================================================

    if (
        event_type
        in {
            "QUEUE_DETECTED",
            "QUEUE_ACTIVE",
            "QUEUE_CLEARED",
        }
    ):

        return (
            "pokemon_queue"
        )


    # =====================================================
    # LEGACY EVENT SAFETY
    #
    # Events queued before v0.7.6a do not contain
    # source_type.
    #
    # Do NOT guess that they belong to Target.
    # =====================================================

    if not source_type:

        print(
            (
                "LEGACY EVENT SKIPPED | "
                f"Event={event_type} | "
                f"Store={event.get('store_name')} | "
                "Reason=Missing source_type"
            )
        )

        return None


    # =====================================================
    # SHOPIFY
    #
    # Saga Concepts
    # Hobbiesville
    # Independent Shopify stores
    # =====================================================

    if (
        source_type
        == "shopify"
    ):

        # Premium+ inventory flicker retains its
        # specialized channel.

        if (
            event_type
            == "INVENTORY_FLICKER"
        ):

            return (
                "inventory_flicker"
            )

        # Price changes can retain Deals.

        if (
            event_type
            in {
                "PRICE_DROP",
                "PRICE_INCREASE",
                "PRICE_ERROR",
            }
        ):

            return (
                "deal"
            )

        # Everything else from Shopify goes here.

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
            == "INVENTORY_FLICKER"
        ):

            return (
                "inventory_flicker"
            )

        if (
            event_type
            in {
                "PRICE_DROP",
                "PRICE_INCREASE",
                "PRICE_ERROR",
            }
        ):

            return (
                "deal"
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
            in {
                "DISCOVERED",
                "PAGE_LIVE",
                "COMING_SOON",
            }
        ):

            return (
                "release_radar"
            )

        return (
            "major_retailer"
        )


    # =====================================================
    # MAJOR RETAILERS
    #
    # Target
    # Walmart
    # GameStop
    # Best Buy
    # etc.
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

        if (
            event_type
            in {
                "PRICE_DROP",
                "PRICE_INCREASE",
                "PRICE_ERROR",
            }
        ):

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

        return (
            "major_retailer"
        )


    print(
        (
            "UNKNOWN EVENT SOURCE | "
            f"Source={source_type} | "
            f"Event={event_type}"
        )
    )

    return None


# =========================================================
# DUPLICATE PROTECTION
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
    event: dict,
):

    event_type = (
        event.get(
            "event_type",
            "UNKNOWN"
        )
    )

    if (
        event_type
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
# EMBED
# =========================================================

def build_event_embed(
    event: dict,
):

    event_type = (
        event.get(
            "event_type",
            "UNKNOWN"
        )
    )

    title = (
        EVENT_TITLES.get(
            event_type,
            "📡 LOTUS PRODUCT EVENT",
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

    original_url = (
        event.get(
            "product_url"
        )
        or ""
    )

    source_type = (
        event.get(
            "source_type"
        )
        or "unknown"
    )

    # =====================================================
    # AFFILIATE LINK
    # =====================================================

    final_url, affiliate_used = (
        build_affiliate_url(
            original_url,
            store_name,
        )
    )


    embed = discord.Embed(

        title=title,

        description=(
            f"**{product_name}**"
        ),

        url=(
            final_url
            if final_url
            else None
        ),
    )


    # =====================================================
    # PRODUCT IMAGE
    # =====================================================

    image_url = (
        event.get(
            "image_url"
        )
    )

    if image_url:

        try:

            embed.set_thumbnail(
                url=image_url
            )

        except Exception:

            pass


    # =====================================================
    # STORE
    # =====================================================

    embed.add_field(

        name="Store",

        value=store_name,

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

            value=game,

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

            value=product_type,

            inline=True,
        )


    # =====================================================
    # PRICE
    # =====================================================

    price = (
        event.get(
            "price"
        )
    )

    currency = (
        event.get(
            "currency"
        )
        or "USD"
    )

    if price is not None:

        try:

            numeric_price = (
                float(
                    price
                )
            )

            if (
                currency
                == "USD"
            ):

                price_text = (
                    f"${numeric_price:.2f}"
                )

            else:

                price_text = (
                    f"{numeric_price:.2f} "
                    f"{currency}"
                )

        except (
            ValueError,
            TypeError,
        ):

            price_text = (
                f"{price} "
                f"{currency}"
            )

        embed.add_field(

            name="Price",

            value=price_text,

            inline=True,
        )


    # =====================================================
    # STOCK
    # =====================================================

    if (
        event_type
        in {
            "STOCK_AVAILABLE",
            "RESTOCK",
            "SOLD_OUT",
            "INVENTORY_FLICKER",
        }
    ):

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
    # REGION
    # =====================================================

    region = (
        event.get(
            "region"
        )
    )

    if region:

        embed.add_field(

            name="Region",

            value=region,

            inline=True,
        )


    # =====================================================
    # SOURCE
    # =====================================================

    source_names = {

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
            source_names.get(
                source_type,
                source_type,
            )
        ),

        inline=True,
    )


    # =====================================================
    # QUICK LINK
    # =====================================================

    if final_url:

        embed.add_field(

            name="Quick Link",

            value=(
                f"[🛒 Open Product]"
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


    embed.set_footer(

        text=(
            "Lotus Tracker Bot • PonDeX Trackers"
        )
    )

    return (
        embed,
        affiliate_used,
    )


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
# SEND EVENT
# =========================================================

async def route_event_to_discord(
    bot,
    event: dict,
):

    event_type = (
        event.get(
            "event_type"
        )
    )


    # =====================================================
    # DETERMINE ROUTE FIRST
    #
    # Important:
    # legacy Source=None events are rejected here before
    # they can contaminate another channel.
    # =====================================================

    alert_type = (
        determine_alert_route(
            event
        )
    )

    if not alert_type:

        return False


    # =====================================================
    # DEDUPE
    # =====================================================

    if (
        await should_suppress_duplicate(
            event
        )
    ):

        print(
            (
                "DUPLICATE EVENT SUPPRESSED | "
                f"{event_type} | "
                f"{event.get('product_name')}"
            )
        )

        return True


    access = (
        ALERT_ACCESS.get(
            alert_type
        )
    )

    if not access:

        print(
            (
                "NO ALERT ACCESS CONFIG | "
                f"Route={alert_type}"
            )
        )

        return False


    channel_variable = (
        access.get(
            "channel_variable"
        )
    )

    minimum_tier = (
        access.get(
            "minimum_tier",
            "Free"
        )
    )

    channel_id = (
        safe_int(
            CHANNEL_MAP.get(
                channel_variable
            )
        )
    )

    if not channel_id:

        print(
            (
                "MISSING ALERT CHANNEL | "
                f"Route={alert_type} | "
                f"Variable="
                f"{channel_variable}"
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
                "DISCORD CHANNEL NOT FOUND | "
                f"ID={channel_id}"
            )
        )

        return False


    # =====================================================
    # GAME ROLE
    # =====================================================

    game = (
        event.get(
            "game"
        )
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


    # =====================================================
    # EMBED
    # =====================================================

    embed, affiliate_used = (
        build_event_embed(
            event
        )
    )


    # =====================================================
    # SEND WITH BASIC RETRY
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

            return False


    if message is None:

        print(
            (
                "DISCORD ALERT FAILED AFTER RETRIES | "
                f"Event={event_type} | "
                f"Store="
                f"{event.get('store_name')}"
            )
        )

        return False


    # =====================================================
    # DELIVERY HISTORY
    # =====================================================

    await save_alert_delivery(

        alert_type=(
            alert_type
        ),

        minimum_tier=(
            minimum_tier
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
            f"Event={event_type} | "
            f"Source="
            f"{event.get('source_type')} | "
            f"Store="
            f"{event.get('store_name')} | "
            f"Route={alert_type} | "
            f"Channel={channel.name} | "
            f"Image="
            f"{bool(event.get('image_url'))} | "
            f"Affiliate="
            f"{affiliate_used}"
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
        "Lotus Event Worker v0.7.6a started."
    )

    while not bot.is_closed():

        try:

            if not await check_redis():

                try:

                    await init_redis()

                    bot.redis_ready = True

                except Exception as error:

                    bot.redis_ready = False

                    print(
                        (
                            "EVENT WORKER REDIS "
                            "RECONNECT ERROR | "
                            f"{type(error).__name__}: "
                            f"{error}"
                        )
                    )

                    await asyncio.sleep(
                        5
                    )

                    continue


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