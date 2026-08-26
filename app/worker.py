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
# Version 0.7
#
# Redis Event Consumer
# Smart Deduplication
# Tier / Channel Routing
# Affiliate Pipeline
# Pokemon Center Queue Intelligence
# =========================================================


# =========================================================
# EVENT -> ALERT TYPE
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

    # =====================================================
    # POKEMON CENTER
    # =====================================================

    "QUEUE_DETECTED":
        "pokemon_queue",

    "QUEUE_ACTIVE":
        "pokemon_queue",

    "QUEUE_CLEARED":
        "pokemon_queue",
}


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

    # =====================================================
    # POKEMON CENTER
    # =====================================================

    "QUEUE_DETECTED":
        "🚨 POKÉMON CENTER QUEUE DETECTED",

    "QUEUE_ACTIVE":
        "🚨 POKÉMON CENTER QUEUE LIVE",

    "QUEUE_CLEARED":
        "✅ POKÉMON CENTER QUEUE CLEARED",
}


# =========================================================
# REAL-TIME TRANSITIONS
#
# These must NOT be globally suppressed because repeated
# transitions themselves carry valuable information.
# =========================================================

REALTIME_TRANSITION_EVENTS = {

    "RESTOCK",

    "SOLD_OUT",

    "INVENTORY_FLICKER",

    "QUEUE_DETECTED",

    "QUEUE_ACTIVE",

    "QUEUE_CLEARED",
}


# =========================================================
# SMART DEDUPLICATION
# =========================================================

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

    game = (
        event.get(
            "game",
            "",
        )
    )

    store_name = (
        event.get(
            "store_name",
            "",
        )
    )

    product_url = (
        event.get(
            "product_url",
            "",
        )
    )

    price = (
        event.get(
            "price"
        )
    )

    identity = (
        f"{event_type}|"
        f"{game}|"
        f"{store_name}|"
        f"{product_url}|"
        f"{price}"
    )

    digest = (
        hashlib.sha256(
            identity.encode(
                "utf-8"
            )
        ).hexdigest()
    )

    key = (
        f"lotus:dedupe:{digest}"
    )

    try:

        result = (
            await redis_client.set(
                key,
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

        # Never lose an alert merely because
        # duplicate protection failed.

        return False


# =========================================================
# BUILD DISCORD EVENT EMBED
# =========================================================

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

    # =====================================================
    # AFFILIATE PIPELINE
    #
    # Every URL passes through here.
    #
    # Unsupported merchants remain unchanged.
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
    # LANGUAGE
    # =====================================================

    language = (
        event.get(
            "language"
        )
    )

    if (
        language
        and product_type
        != "Virtual Queue"
    ):

        embed.add_field(
            name="Language",
            value=language,
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

        in_stock = bool(
            event.get(
                "in_stock"
            )
        )

        embed.add_field(
            name="Availability",
            value=(
                "🟢 In Stock"
                if in_stock
                else "🔴 Out of Stock"
            ),
            inline=True,
        )

    # =====================================================
    # INVENTORY FLICKER
    # =====================================================

    if (
        event_type
        == "INVENTORY_FLICKER"
    ):

        embed.add_field(
            name="⚡ Rapid Inventory Activity",
            value=(
                "Lotus detected multiple legitimate "
                "stock transitions in a short period.\n\n"
                "Inventory may only be available briefly."
            ),
            inline=False,
        )

        if event.get(
            "in_stock"
        ):

            embed.add_field(
                name="Action",
                value="🔥 **TRY CHECKOUT NOW**",
                inline=False,
            )

    # =====================================================
    # POKEMON CENTER QUEUE
    # =====================================================

    if event_type in {

        "QUEUE_DETECTED",

        "QUEUE_ACTIVE",

        "QUEUE_CLEARED",
    }:

        if event_type == "QUEUE_DETECTED":

            queue_message = (
                "Lotus detected a Pokémon Center "
                "virtual queue/waiting-room signal.\n\n"
                "This can happen before a product drop, "
                "but a queue does **not guarantee** "
                "that a specific product is launching."
            )

        elif event_type == "QUEUE_ACTIVE":

            queue_message = (
                "The Pokémon Center virtual queue "
                "is currently active.\n\n"
                "Members should use Pokémon Center "
                "normally and enter the official queue."
            )

        else:

            queue_message = (
                "The previously detected Pokémon Center "
                "queue is no longer being observed."
            )

        embed.add_field(
            name="⚡ Queue Intelligence",
            value=queue_message,
            inline=False,
        )

        embed.add_field(
            name="Access",
            value="💎 Premium+ Early Intelligence",
            inline=False,
        )

    # =====================================================
    # PRODUCT / STORE LINK
    # =====================================================

    if final_url:

        label = (
            "Open Pokémon Center"
            if product_type
            == "Virtual Queue"
            else "Open Product"
        )

        embed.add_field(
            name="Link",
            value=(
                f"[{label}]({final_url})"
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
            "Lotus Tracker Bot "
            "• PonDeX Trackers"
        )
    )

    return (
        embed,
        affiliate_used,
    )


# =========================================================
# PRIMARY DISCORD GUILD
# =========================================================

def get_primary_guild(
    bot,
):

    if not bot.guilds:

        return None

    return bot.guilds[
        0
    ]


# =========================================================
# ROUTE EVENT
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
    # DUPLICATE PROTECTION
    # =====================================================

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

    # =====================================================
    # ROUTE
    # =====================================================

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

        print(
            (
                "NO ACCESS CONFIG FOR: "
                f"{alert_type}"
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

        print(
            "No Discord guild available."
        )

        return False

    channel = (
        guild.get_channel(
            channel_id
        )
    )

    if channel is None:

        print(
            (
                "DISCORD CHANNEL NOT FOUND: "
                f"{channel_id}"
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

    game_role_id = safe_int(
        GAME_ROLES.get(
            game
        )
    )

    game_role = (
        guild.get_role(
            game_role_id
        )
        if game_role_id
        else None
    )

    mention_text = (
        game_role.mention
        if game_role
        else (
            f"**{game}**"
            if game
            else ""
        )
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
    # SEND
    # =====================================================

    try:

        message = (
            await channel.send(

                content=mention_text,

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
                f"Affiliate="
                f"{affiliate_used}"
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


# =========================================================
# EVENT WORKER LOOP
# =========================================================

async def run_event_worker(
    bot,
):

    await bot.wait_until_ready()

    print(
        "Lotus Event Worker started."
    )

    while not bot.is_closed():

        try:

            redis_online = (
                await check_redis()
            )

            # =================================================
            # REDIS RECOVERY
            # =================================================

            if not redis_online:

                try:

                    await init_redis()

                    bot.redis_ready = True

                    print(
                        "Event Worker reconnected to Redis."
                    )

                except Exception as error:

                    bot.redis_ready = False

                    print(
                        (
                            "REDIS RECONNECT ERROR: "
                            f"{type(error).__name__}: "
                            f"{error}"
                        )
                    )

                    await asyncio.sleep(
                        5
                    )

                    continue

            # =================================================
            # NEXT EVENT
            # =================================================

            event = (
                await pop_next_event(
                    timeout=5
                )
            )

            if event is None:

                continue

            print(
                (
                    "EVENT RECEIVED: "
                    f"{event.get('event_type')} | "
                    f"{event.get('product_name')}"
                )
            )

            await route_event_to_discord(
                bot,
                event,
            )

        except asyncio.CancelledError:

            print(
                "Lotus Event Worker stopped."
            )

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