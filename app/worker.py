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
# Version 0.6.1
#
# Redis Consumer
# Discord Routing
# Smart Deduplication
# Affiliate Link Pipeline
# =========================================================


# =========================================================
# EVENT ROUTING
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
}


# =========================================================
# EVENTS WHERE REAL REPEATED TRANSITIONS MATTER
#
# DO NOT globally dedupe these.
# =========================================================

REALTIME_TRANSITION_EVENTS = {

    "RESTOCK",

    "SOLD_OUT",

    "INVENTORY_FLICKER",
}


# =========================================================
# SHOULD DUPLICATE EVENT BE SUPPRESSED?
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

    # -----------------------------------------------------
    # Genuine stock transitions are intentionally not
    # suppressed here.
    # -----------------------------------------------------

    if event_type in REALTIME_TRANSITION_EVENTS:

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

    dedupe_key = (
        f"lotus:dedupe:"
        f"{digest}"
    )

    try:

        # NX means only create if key does not exist.
        #
        # EX 120 means the exact same event cannot
        # accidentally send twice within 2 minutes.

        result = (
            await redis_client.set(
                dedupe_key,
                "1",
                ex=120,
                nx=True,
            )
        )

        # None means the key already existed.

        return (
            result is None
        )

    except Exception as error:

        print(
            "DEDUPE ERROR: "
            f"{type(error).__name__}: {error}"
        )

        # Never lose an alert because dedupe failed.

        return False


# =========================================================
# BUILD DISCORD EMBED
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

    title = EVENT_TITLES.get(
        event_type,
        "📡 LOTUS PRODUCT EVENT",
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

    # =====================================================
    # BASIC PRODUCT DETAILS
    # =====================================================

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
            name="Product Type",
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
                f"{price} {currency}"
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

    language = (
        event.get(
            "language"
        )
    )

    if language:

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

        stock_text = (
            "🟢 In Stock"
            if in_stock
            else "🔴 Out of Stock"
        )

        embed.add_field(
            name="Availability",
            value=stock_text,
            inline=True,
        )

    # =====================================================
    # PREMIUM+ FLICKER MESSAGE
    # =====================================================

    if event_type == "INVENTORY_FLICKER":

        embed.add_field(
            name="⚡ Rapid Inventory Activity",
            value=(
                "Lotus detected multiple legitimate "
                "stock transitions within a short period.\n\n"
                "**Inventory may only be available briefly.**"
            ),
            inline=False,
        )

        if event.get(
            "in_stock"
        ):

            embed.add_field(
                name="Action",
                value=(
                    "🔥 **TRY CHECKOUT NOW**"
                ),
                inline=False,
            )

    # =====================================================
    # PRODUCT LINK
    # =====================================================

    if final_url:

        embed.add_field(
            name="Product Link",
            value=(
                f"[Open Product]({final_url})"
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
# PRIMARY DISCORD SERVER
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
# ROUTE EVENT TO DISCORD
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
    # SMART DUPLICATE PROTECTION
    # =====================================================

    suppress = (
        await should_suppress_duplicate(
            event
        )
    )

    if suppress:

        print(
            "DUPLICATE EVENT SUPPRESSED: "
            f"{event_type} | "
            f"{event.get('product_name')}"
        )

        return True

    # =====================================================
    # ROUTE LOOKUP
    # =====================================================

    alert_type = (
        EVENT_ROUTE_MAP.get(
            event_type
        )
    )

    if not alert_type:

        print(
            "NO ROUTE FOR EVENT: "
            f"{event_type}"
        )

        return False

    access_config = (
        ALERT_ACCESS.get(
            alert_type
        )
    )

    if not access_config:

        print(
            "NO ALERT ACCESS CONFIG: "
            f"{alert_type}"
        )

        return False

    channel_variable = (
        access_config.get(
            "channel_variable"
        )
    )

    minimum_tier = (
        access_config.get(
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
            "MISSING CHANNEL FOR EVENT: "
            f"{event_type} -> "
            f"{channel_variable}"
        )

        return False

    # =====================================================
    # DISCORD GUILD + CHANNEL
    # =====================================================

    guild = (
        get_primary_guild(
            bot
        )
    )

    if guild is None:

        print(
            "EVENT WORKER: "
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
            "EVENT WORKER CHANNEL NOT FOUND: "
            f"{channel_id}"
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
    # EMBED + AFFILIATE PIPELINE
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

                content=(
                    mention_text
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
            "ALERT SENT: "
            f"{event_type} | "
            f"{game} | "
            f"{channel.name} | "
            f"Affiliate="
            f"{affiliate_used}"
        )

        return True

    except Exception as error:

        print(
            "EVENT DISCORD SEND ERROR: "
            f"{type(error).__name__}: {error}"
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

                    bot.redis_error = None

                    print(
                        "Event Worker reconnected to Redis."
                    )

                except Exception as error:

                    bot.redis_ready = False

                    bot.redis_error = (
                        f"{type(error).__name__}: "
                        f"{error}"
                    )

                    import asyncio

                    await asyncio.sleep(
                        5
                    )

                    continue

            # =================================================
            # WAIT FOR NEXT EVENT
            # =================================================

            event = (
                await pop_next_event(
                    timeout=5
                )
            )

            if event is None:

                continue

            print(
                "EVENT RECEIVED: "
                f"{event.get('event_type')} | "
                f"{event.get('product_name')}"
            )

            # =================================================
            # DISCORD ROUTING
            # =================================================

            await route_event_to_discord(
                bot,
                event,
            )

        except Exception as error:

            import asyncio

            if isinstance(
                error,
                asyncio.CancelledError,
            ):

                print(
                    "Lotus Event Worker stopped."
                )

                raise

            print(
                "EVENT WORKER ERROR: "
                f"{type(error).__name__}: {error}"
            )

            await asyncio.sleep(
                2
            )