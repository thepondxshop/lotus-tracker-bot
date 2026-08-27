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


# =========================================================
# LOTUS EVENT WORKER
# PonDeX Trackers
# Version 0.7.8
#
# Strict Game Validation
# Product Category Preferences
# Smart Quick Cart
# Native Currency + USD
# Affiliate Links
# Correct Channel Routing
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
# GAME VALIDATION FAILSAFE
# =========================================================

def validate_event_game(
    event,
):

    game = (
        event.get(
            "game"
        )
        or ""
    )


    title = (
        event.get(
            "product_name"
        )
        or ""
    ).lower()


    product_type = (
        event.get(
            "product_type"
        )
        or ""
    ).lower()


    combined = (
        f"{title} "
        f"{product_type}"
    )


    # =====================================================
    # PRODUCTS THAT MUST NEVER BE ONE PIECE
    # =====================================================

    if (
        game
        == "One Piece"
    ):

        conflicts = [

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


        for term in conflicts:

            if term in combined:

                print(
                    (
                        "GAME VALIDATION REJECTED | "
                        f"Assigned=One Piece | "
                        f"Product={event.get('product_name')} | "
                        f"Conflict={term}"
                    )
                )

                return False


    # =====================================================
    # PRODUCTS THAT MUST NEVER BE POKEMON
    # =====================================================

    if (
        game
        == "Pokemon"
    ):

        conflicts = [

            "warhammer",

            "games workshop",

            "star wars unlimited",

            "magic the gathering",

            "magic: the gathering",

            "one piece card game",

            "gundam card game",

            "dragon ball fusion world",

            "flesh and blood",

            "yu-gi-oh",

            "lorcana",

            "digimon",
        ]


        for term in conflicts:

            if term in combined:

                print(
                    (
                        "GAME VALIDATION REJECTED | "
                        f"Assigned=Pokemon | "
                        f"Product={event.get('product_name')} | "
                        f"Conflict={term}"
                    )
                )

                return False


    return True


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
    # QUEUE
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

    if (
        source_type
        == "shopify"
    ):

        # New listings/pages belong in early detection.

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


        if (
            event_type
            == "RELEASE_DATE_CHANGED"
        ):

            return (
                "release_radar"
            )


        if event_type in {

            "STOCK_AVAILABLE",

            "RESTOCK",

            "SOLD_OUT",

        }:

            return (
                "shopify"
            )


        return None


    # =====================================================
    # POKEMON CENTER
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
                "page_live"
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

            "DISCOVERED",

            "PAGE_LIVE",

            "COMING_SOON",

        }:

            return (
                "page_live"
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
# SMART CART QUANTITIES
# =========================================================

def get_quick_cart_quantities(
    purchase_limit,
):

    # =====================================================
    # KNOWN LIMIT
    # =====================================================

    if purchase_limit:

        try:

            limit = int(
                purchase_limit
            )

        except (
            TypeError,
            ValueError,
        ):

            limit = None


        if limit:

            if (
                limit
                <= 5
            ):

                return list(
                    range(
                        1,
                        limit + 1,
                    )
                )


            preferred = [
                1,
                2,
                3,
                5,
                10,
            ]


            quantities = [

                quantity

                for quantity
                in preferred

                if quantity
                <= limit
            ]


            if (
                limit
                not in quantities

                and

                len(
                    quantities
                )
                < 5
            ):

                quantities.append(
                    limit
                )


            return (
                quantities[:5]
            )


    # =====================================================
    # UNKNOWN LIMIT
    # =====================================================

    return [
        1,
        2,
        3,
        5,
    ]


# =========================================================
# SHOPIFY CART URL
# =========================================================

def build_shopify_cart_url(
    event,
    quantity,
):

    variant_id = (
        event.get(
            "variant_id"
        )
    )


    cart_base_url = (
        event.get(
            "cart_base_url"
        )
    )


    if (
        not variant_id
        or
        not cart_base_url
    ):

        return None


    cart_base_url = (
        cart_base_url.rstrip(
            "/"
        )
    )


    return (
        f"{cart_base_url}"
        f"/cart/"
        f"{variant_id}:"
        f"{quantity}"
    )


# =========================================================
# SMART CART VIEW
# =========================================================

def build_quick_cart_view(
    event,
):

    # =====================================================
    # CURRENTLY SHOPIFY ONLY
    # =====================================================

    if (
        event.get(
            "source_type"
        )
        != "shopify"
    ):

        return None


    event_type = (
        event.get(
            "event_type"
        )
    )


    # =====================================================
    # ONLY WHEN PURCHASABLE
    # =====================================================

    if event_type not in {

        "STOCK_AVAILABLE",

        "RESTOCK",

        "PREORDER_LIVE",

        "INVENTORY_FLICKER",

    }:

        return None


    if not event.get(
        "in_stock"
    ):

        return None


    if (
        not event.get(
            "variant_id"
        )
        or
        not event.get(
            "cart_base_url"
        )
    ):

        return None


    quantities = (
        get_quick_cart_quantities(
            event.get(
                "purchase_limit"
            )
        )
    )


    view = (
        discord.ui.View(
            timeout=None
        )
    )


    store_name = (
        event.get(
            "store_name"
        )
        or ""
    )


    for quantity in quantities:

        cart_url = (
            build_shopify_cart_url(
                event,
                quantity,
            )
        )


        if not cart_url:

            continue


        final_cart_url, _ = (
            build_affiliate_url(

                cart_url,

                store_name,
            )
        )


        view.add_item(

            discord.ui.Button(

                label=(
                    f"Add {quantity}"
                ),

                emoji="🛒",

                style=(
                    discord.ButtonStyle.link
                ),

                url=(
                    final_cart_url
                    or cart_url
                ),
            )
        )


    if not view.children:

        return None


    return view


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
                or None
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

            value=game,

            inline=True,
        )


    # =====================================================
    # CATEGORY
    # =====================================================

    product_category = (
        event.get(
            "product_category"
        )
        or "UNKNOWN"
    ).upper()


    category_labels = {

        "SEALED":
            "📦 Sealed",

        "SINGLE":
            "🃏 Single",

        "ACCESSORY":
            "🎒 Accessory",

        "UNKNOWN":
            "❔ Unknown",
    }


    embed.add_field(

        name="Category",

        value=(
            category_labels.get(
                product_category,
                product_category.title(),
            )
        ),

        inline=True,
    )


    # =====================================================
    # TYPE
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
    ).upper()


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


            if (
                converted_usd
                is not None
            ):

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
    # STATUS
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
    # SMART CART
    # =====================================================

    if (

        source_type
        == "shopify"

        and

        event.get(
            "variant_id"
        )

    ):

        purchase_limit = (
            event.get(
                "purchase_limit"
            )
        )


        if purchase_limit:

            cart_status = (
                f"Limit detected: "
                f"**{purchase_limit}**"
            )

        else:

            cart_status = (
                "Limit not detected • "
                "retailer may adjust quantity"
            )


        embed.add_field(

            name="🛒 Smart Cart",

            value=(
                cart_status
            ),

            inline=False,
        )


    # =====================================================
    # PRODUCT LINK
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
    # AFFILIATE
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

    if (

        currency
        != "USD"

        and

        price
        is not None

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
# GUILD
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
# SEND
# =========================================================

async def route_event_to_discord(
    bot,
    event,
):

    # =====================================================
    # SAFETY VALIDATION
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


    # =====================================================
    # ROUTE
    # =====================================================

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
                "DUPLICATE SUPPRESSED | "
                f"{event.get('product_name')}"
            )
        )

        return True


    # =====================================================
    # CHANNEL CONFIG
    # =====================================================

    access = (
        ALERT_ACCESS.get(
            alert_type
        )
    )


    if not access:

        print(
            (
                "MISSING ALERT ACCESS | "
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
                "MISSING CHANNEL ID | "
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
                "CHANNEL NOT FOUND | "
                f"ID={channel_id}"
            )
        )

        return False


    # =====================================================
    # PREFERENCE-AWARE ROLE
    # =====================================================

    game = (
        event.get(
            "game"
        )
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
            f"Role="
            f"{role.name if role else 'NONE'}"
        )
    )


    # =====================================================
    # EMBED + CART BUTTONS
    # =====================================================

    embed, affiliate_used = (
        await build_event_embed(
            event
        )
    )


    quick_cart_view = (
        build_quick_cart_view(
            event
        )
    )


    # =====================================================
    # DISCORD SEND
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

                    view=(
                        quick_cart_view
                    ),

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

        return False


    # =====================================================
    # DELIVERY HISTORY
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


    print(
        (
            "ALERT SENT | "
            f"Event={event.get('event_type')} | "
            f"Game={event.get('game')} | "
            f"Store={event.get('store_name')} | "
            f"Category={product_category} | "
            f"Route={alert_type} | "
            f"Channel={channel.name} | "
            f"Currency={event.get('currency')} | "
            f"Image={bool(event.get('image_url'))} | "
            f"Variant={event.get('variant_id')} | "
            f"Limit={event.get('purchase_limit')} | "
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
        "Lotus Event Worker v0.7.8 started."
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