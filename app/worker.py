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

from app.helpers import safe_int

from app.redis_client import (
    check_redis,
    get_redis,
    init_redis,
)


# =========================================================
# LOTUS EVENT WORKER
# PonDeX Trackers
# Version 0.7.7
#
# Source Routing
# Images
# Affiliate Links
# Native Currency
# USD Conversion
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

    if source_type == "shopify":

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

        return (
            "shopify"
        )

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

        return (
            "major_retailer"
        )

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

    if (
        source_type
        == "simulation"
    ):

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
        ]
    )

    digest = (
        hashlib.sha256(
            identity.encode(
                "utf-8"
            )
        ).hexdigest()
    )

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


# =========================================================
# EMBED
# =========================================================

async def build_event_embed(
    event,
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

    image_url = (
        event.get(
            "image_url"
        )
    )

    if image_url:

        embed.set_thumbnail(
            url=image_url
        )

    embed.add_field(
        name="Store",
        value=store_name,
        inline=True,
    )

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
    # PRICE + CURRENCY CONVERSION
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
    ).upper()

    if price is not None:

        native_text = (
            format_currency(
                price,
                currency,
            )
        )

        if currency == "USD":

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
            value=price_text,
            inline=True,
        )

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

    if final_url:

        embed.add_field(
            name="Quick Link",
            value=(
                f"[🛒 Open Product]"
                f"({final_url})"
            ),
            inline=False,
        )

    if affiliate_used:

        embed.add_field(
            name="Affiliate Disclosure",
            value=(
                AFFILIATE_DISCLOSURE
            ),
            inline=False,
        )

    if (
        currency
        != "USD"
        and price is not None
    ):

        embed.set_footer(
            text=(
                "Lotus Tracker Bot • "
                "USD conversion is approximate"
            )
        )

    else:

        embed.set_footer(
            text=(
                "Lotus Tracker Bot • "
                "PonDeX Trackers"
            )
        )

    return (
        embed,
        affiliate_used,
    )


# =========================================================
# SEND
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

    embed, affiliate_used = (
        await build_event_embed(
            event
        )
    )

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

        except discord.DiscordServerError:

            if (
                attempt
                < 3
            ):

                await asyncio.sleep(
                    attempt * 2
                )

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
            f"Store="
            f"{event.get('store_name')} | "
            f"Currency="
            f"{event.get('currency')} | "
            f"Route={alert_type} | "
            f"Image="
            f"{bool(event.get('image_url'))}"
        )
    )

    return True


# =========================================================
# WORKER
# =========================================================

async def run_event_worker(
    bot,
):

    await bot.wait_until_ready()

    print(
        "Lotus Event Worker v0.7.7 started."
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