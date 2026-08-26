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
# Version 0.7.1
# =========================================================


EVENT_ROUTE_MAP = {

    "DISCOVERED":
        "release_radar",

    "PAGE_LIVE":
        "page_live",

    "COMING_SOON":
        "release_radar",

    "PREORDER_LIVE":
        "preorder",

    "STOCK_AVAILABLE":
        "major_retailer",

    "RESTOCK":
        "major_retailer",

    "SOLD_OUT":
        "major_retailer",

    "PRICE_DROP":
        "deal",

    "PRICE_INCREASE":
        "deal",

    "PRICE_ERROR":
        "deal",

    "INVENTORY_FLICKER":
        "inventory_flicker",

    "RELEASE_DATE_CHANGED":
        "release_radar",

    "QUEUE_DETECTED":
        "pokemon_queue",

    "QUEUE_ACTIVE":
        "pokemon_queue",

    "QUEUE_CLEARED":
        "pokemon_queue",
}


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
        "🟢 STOCK AVAILABLE",

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


REALTIME_TRANSITION_EVENTS = {

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
            "UNKNOWN",
        )
    )

    if (
        event_type
        in REALTIME_TRANSITION_EVENTS
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
                    f"lotus:dedupe:"
                    f"{digest}"
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
                "DEDUPE ERROR: "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return False


def build_event_embed(
    event: dict,
):

    event_type = (
        event.get(
            "event_type",
            "UNKNOWN",
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
            "product_name",
            "Unknown Product",
        )
    )

    store_name = (
        event.get(
            "store_name",
            "Unknown Store",
        )
    )

    original_url = (
        event.get(
            "product_url",
            "",
        )
    )

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

    price = (
        event.get(
            "price"
        )
    )

    currency = (
        event.get(
            "currency",
            "USD",
        )
    )

    if price is not None:

        try:

            price_text = (
                f"{float(price):.2f} "
                f"{currency}"
            )

        except (
            TypeError,
            ValueError,
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

    if event_type in {

        "STOCK_AVAILABLE",

        "RESTOCK",

        "SOLD_OUT",

        "INVENTORY_FLICKER",
    }:

        embed.add_field(
            name="Availability",
            value=(
                "🟢 In Stock"
                if event.get(
                    "in_stock"
                )
                else "🔴 Out of Stock"
            ),
            inline=True,
        )

    if event_type in {

        "QUEUE_DETECTED",

        "QUEUE_ACTIVE",

        "QUEUE_CLEARED",
    }:

        embed.add_field(
            name="⚡ Queue Intelligence",
            value=(
                "This is an early Pokémon Center "
                "traffic/queue signal. It does not "
                "guarantee that a specific product "
                "is launching."
            ),
            inline=False,
        )

    if (
        store_name
        == "Pokémon Center"
        and event_type
        not in {
            "QUEUE_DETECTED",
            "QUEUE_ACTIVE",
            "QUEUE_CLEARED",
        }
    ):

        embed.add_field(
            name="Pokémon Center Product Intelligence",
            value=(
                "This alert is based on a publicly "
                "observable Pokémon Center product-page "
                "state change."
            ),
            inline=False,
        )

    if final_url:

        embed.add_field(
            name="Link",
            value=(
                f"[Open Product]({final_url})"
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

    embed.set_footer(
        text=(
            "Lotus Tracker Bot "
            "• PonDeX Trackers"
        )
    )

    return (
        embed,
        affiliate_used,
    )


def get_primary_guild(
    bot,
):

    if not bot.guilds:

        return None

    return bot.guilds[
        0
    ]


async def route_event_to_discord(
    bot,
    event: dict,
):

    event_type = (
        event.get(
            "event_type"
        )
    )

    if await should_suppress_duplicate(
        event
    ):

        print(
            (
                "DUPLICATE EVENT SUPPRESSED: "
                f"{event_type} | "
                f"{event.get('product_name')}"
            )
        )

        return True

    alert_type = (
        EVENT_ROUTE_MAP.get(
            event_type
        )
    )

    if not alert_type:

        print(
            (
                "NO ROUTE FOR EVENT: "
                f"{event_type}"
            )
        )

        return False

    access = (
        ALERT_ACCESS.get(
            alert_type
        )
    )

    if not access:

        return False

    channel_variable = (
        access.get(
            "channel_variable"
        )
    )

    minimum_tier = (
        access.get(
            "minimum_tier",
            "Free",
        )
    )

    channel_id = safe_int(
        CHANNEL_MAP.get(
            channel_variable
        )
    )

    if not channel_id:

        print(
            (
                "MISSING ALERT CHANNEL: "
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

        return False

    game = (
        event.get(
            "game"
        )
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

    embed, affiliate_used = (
        build_event_embed(
            event
        )
    )

    try:

        message = (
            await channel.send(
                content=(
                    role.mention
                    if role
                    else (
                        f"**{game}**"
                        if game
                        else ""
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

        await save_alert_delivery(
            alert_type=alert_type,
            minimum_tier=minimum_tier,
            discord_channel_id=(
                channel.id
            ),
            discord_message_id=(
                message.id
            ),
        )

        print(
            (
                "ALERT SENT: "
                f"{event_type} | "
                f"{game} | "
                f"{channel.name} | "
                f"Affiliate={affiliate_used}"
            )
        )

        return True

    except Exception as error:

        print(
            (
                "DISCORD ALERT ERROR: "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return False


async def run_event_worker(
    bot,
):

    await bot.wait_until_ready()

    print(
        "Lotus Event Worker started."
    )

    while not bot.is_closed():

        try:

            if not await check_redis():

                try:

                    await init_redis()

                    bot.redis_ready = True

                except Exception:

                    bot.redis_ready = False

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
                    "EVENT WORKER ERROR: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

            await asyncio.sleep(
                2
            )