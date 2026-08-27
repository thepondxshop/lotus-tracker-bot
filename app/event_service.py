import json

from app.database import (
    SessionLocal,
)

from app.events import (
    ProductEvent,
    ProductEventType,
)

from app.models import (
    Alert,
    ProductEventRecord,
)

from app.redis_client import (
    get_redis,
)


# =========================================================
# LOTUS EVENT SERVICE
# PonDeX Trackers
# Version 1.0.2
#
# PostgreSQL Event History
# Redis Event Queue
# Product Family Serialization
# Product Category Serialization
# Historical Pricing
# MSRP Intelligence
# Scalper Protection
# Smart Quick Cart
# =========================================================


EVENT_QUEUE_KEY = (
    "lotus:product_events"
)


# =========================================================
# ENUM VALUE
# =========================================================

def enum_value(
    value,
):

    if isinstance(
        value,
        ProductEventType,
    ):

        return (
            value.value
        )

    return str(
        value
    )


# =========================================================
# EVENT -> REDIS DICTIONARY
# =========================================================

def serialize_product_event(
    event: ProductEvent,
):

    return {

        # =================================================
        # CORE EVENT
        # =================================================

        "event_type":
            enum_value(
                event.event_type
            ),

        "game":
            event.game,

        "product_name":
            event.product_name,

        "store_name":
            event.store_name,

        "product_url":
            event.product_url,


        # =================================================
        # CURRENT PRICE
        # =================================================

        "price":
            event.price,

        "old_price":
            event.old_price,

        "currency":
            event.currency,


        # =================================================
        # INVENTORY
        # =================================================

        "in_stock":
            event.in_stock,


        # =================================================
        # REGION
        # =================================================

        "region":
            event.region,

        "language":
            event.language,


        # =================================================
        # PRODUCT IDENTITY
        # =================================================

        "product_type":
            event.product_type,

        "product_category":
            event.product_category,

        "product_family":
            event.product_family,


        # =================================================
        # SOURCE
        # =================================================

        "source_type":
            event.source_type,

        "retailer_key":
            event.retailer_key,


        # =================================================
        # IMAGE
        # =================================================

        "image_url":
            event.image_url,


        # =================================================
        # SMART QUICK CART
        # =================================================

        "variant_id":
            event.variant_id,

        "purchase_limit":
            event.purchase_limit,

        "cart_base_url":
            event.cart_base_url,


        # =================================================
        # HISTORICAL PRICE INTELLIGENCE
        # =================================================

        "price_window_days":
            event.price_window_days,

        "price_30d_low":
            event.price_30d_low,

        "price_30d_average":
            event.price_30d_average,

        "price_30d_high":
            event.price_30d_high,

        "price_history_samples":
            event.price_history_samples,

        "price_vs_average_pct":
            event.price_vs_average_pct,

        "price_vs_low_pct":
            event.price_vs_low_pct,

        "price_drop_pct":
            event.price_drop_pct,

        "historical_deal_score":
            event.historical_deal_score,


        # =================================================
        # MSRP INTELLIGENCE
        # =================================================

        "msrp":
            event.msrp,

        "msrp_currency":
            event.msrp_currency,

        "msrp_source":
            event.msrp_source,

        "msrp_confidence":
            event.msrp_confidence,

        "msrp_original":
            event.msrp_original,

        "msrp_original_currency":
            event.msrp_original_currency,

        "msrp_conversion_used":
            event.msrp_conversion_used,


        # =================================================
        # MSRP COMPARISON
        # =================================================

        "price_vs_msrp_pct":
            event.price_vs_msrp_pct,

        "markup_amount":
            event.markup_amount,

        "msrp_price_state":
            event.msrp_price_state,


        # =================================================
        # SCALPER PROTECTION
        # =================================================

        "scalper_risk":
            event.scalper_risk,


        # =================================================
        # DEAL INTELLIGENCE
        # =================================================

        "deal_score":
            event.deal_score,

        "deal_label":
            event.deal_label,

        "deal_confidence":
            event.deal_confidence,


        # =================================================
        # TIME
        # =================================================

        "timestamp": (

            event.timestamp.isoformat()

            if event.timestamp

            else None
        ),
    }


# =========================================================
# SAVE EVENT HISTORY
#
# IMPORTANT:
#
# The current ProductEventRecord database table stores the
# core event history fields.
#
# Product-family/category/deal metadata travels through
# Redis immediately for alert routing.
#
# We can extend ProductEventRecord with those additional
# historical fields in a later migration without blocking
# the live v1.0.2 alert system.
# =========================================================

async def save_product_event(
    event: ProductEvent,
):

    if SessionLocal is None:

        return False


    try:

        async with SessionLocal() as session:

            record = (
                ProductEventRecord(

                    game=(
                        event.game
                    ),

                    product_name=(
                        event.product_name
                    ),

                    store_name=(
                        event.store_name
                    ),

                    product_url=(
                        event.product_url
                    ),

                    event_type=(
                        enum_value(
                            event.event_type
                        )
                    ),

                    price=(
                        event.price
                    ),

                    currency=(
                        event.currency
                    ),

                    in_stock=(
                        event.in_stock
                    ),

                    region=(
                        event.region
                    ),

                    language=(
                        event.language
                    ),

                    product_type=(
                        event.product_type
                    ),
                )
            )


            session.add(
                record
            )


            await session.commit()


        return True


    except Exception as error:

        print(
            (
                "EVENT DATABASE SAVE ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


        return False


# =========================================================
# PUSH EVENT TO REDIS
# =========================================================

async def push_product_event(
    event: ProductEvent,
):

    redis_client = (
        get_redis()
    )


    if redis_client is None:

        print(
            "EVENT REDIS SAVE ERROR | Redis unavailable"
        )

        return False


    try:

        payload = (
            serialize_product_event(
                event
            )
        )


        await redis_client.rpush(

            EVENT_QUEUE_KEY,

            json.dumps(
                payload
            ),
        )


        print(
            (
                "EVENT QUEUED | "
                f"Event={payload['event_type']} | "
                f"Source={payload['source_type']} | "
                f"Store={payload['store_name']} | "
                f"Game={payload['game']} | "
                f"Category={payload['product_category']} | "
                f"Family={payload['product_family']} | "
                f"Currency={payload['currency']} | "
                f"Image={bool(payload['image_url'])}"
            )
        )


        return True


    except Exception as error:

        print(
            (
                "EVENT REDIS SAVE ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


        return False


# =========================================================
# PROCESS EVENT
# =========================================================

async def process_product_event(
    event: ProductEvent,
):

    database_saved = (
        await save_product_event(
            event
        )
    )


    redis_saved = (
        await push_product_event(
            event
        )
    )


    return {

        "database_saved":
            database_saved,

        "redis_saved":
            redis_saved,
    }


# =========================================================
# POP NEXT EVENT
# =========================================================

async def pop_next_event(
    timeout: int = 5,
):

    redis_client = (
        get_redis()
    )


    if redis_client is None:

        return None


    result = (
        await redis_client.blpop(

            EVENT_QUEUE_KEY,

            timeout=(
                timeout
            ),
        )
    )


    if not result:

        return None


    _, raw_payload = (
        result
    )


    # =====================================================
    # REDIS CLIENT MAY RETURN BYTES OR STRING
    # =====================================================

    if isinstance(
        raw_payload,
        bytes,
    ):

        raw_payload = (
            raw_payload.decode(
                "utf-8"
            )
        )


    try:

        event = (
            json.loads(
                raw_payload
            )
        )


    except Exception as error:

        print(
            (
                "EVENT JSON DECODE ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return None


    # =====================================================
    # BACKWARD COMPATIBILITY
    #
    # If an older queued event exists from before v1.0.2,
    # give it safe defaults instead of crashing the worker.
    # =====================================================

    event.setdefault(
        "product_category",
        "UNKNOWN",
    )

    event.setdefault(
        "product_family",
        "UNKNOWN",
    )

    event.setdefault(
        "old_price",
        None,
    )

    event.setdefault(
        "variant_id",
        None,
    )

    event.setdefault(
        "purchase_limit",
        None,
    )

    event.setdefault(
        "cart_base_url",
        None,
    )

    event.setdefault(
        "msrp",
        None,
    )

    event.setdefault(
        "msrp_currency",
        None,
    )

    event.setdefault(
        "msrp_source",
        None,
    )

    event.setdefault(
        "msrp_confidence",
        None,
    )

    event.setdefault(
        "msrp_original",
        None,
    )

    event.setdefault(
        "msrp_original_currency",
        None,
    )

    event.setdefault(
        "msrp_conversion_used",
        False,
    )

    event.setdefault(
        "price_vs_msrp_pct",
        None,
    )

    event.setdefault(
        "markup_amount",
        None,
    )

    event.setdefault(
        "msrp_price_state",
        None,
    )

    event.setdefault(
        "scalper_risk",
        None,
    )

    event.setdefault(
        "deal_score",
        None,
    )

    event.setdefault(
        "deal_label",
        None,
    )

    event.setdefault(
        "deal_confidence",
        None,
    )

    event.setdefault(
        "price_window_days",
        None,
    )

    event.setdefault(
        "price_30d_low",
        None,
    )

    event.setdefault(
        "price_30d_average",
        None,
    )

    event.setdefault(
        "price_30d_high",
        None,
    )

    event.setdefault(
        "price_history_samples",
        None,
    )

    event.setdefault(
        "price_vs_average_pct",
        None,
    )

    event.setdefault(
        "price_vs_low_pct",
        None,
    )

    event.setdefault(
        "price_drop_pct",
        None,
    )

    event.setdefault(
        "historical_deal_score",
        None,
    )


    return event


# =========================================================
# QUEUE SIZE
# =========================================================

async def get_queue_size():

    redis_client = (
        get_redis()
    )


    if redis_client is None:

        return 0


    try:

        return int(
            await redis_client.llen(
                EVENT_QUEUE_KEY
            )
        )


    except Exception:

        return 0


# =========================================================
# CLEAR EVENT QUEUE
# =========================================================

async def clear_event_queue():

    redis_client = (
        get_redis()
    )


    if redis_client is None:

        return 0


    try:

        queue_size = int(
            await redis_client.llen(
                EVENT_QUEUE_KEY
            )
        )


        await redis_client.delete(
            EVENT_QUEUE_KEY
        )


        print(
            (
                "EVENT QUEUE CLEARED | "
                f"Removed={queue_size}"
            )
        )


        return queue_size


    except Exception as error:

        print(
            (
                "EVENT QUEUE CLEAR ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


        return 0


# =========================================================
# ALERT DELIVERY RECORD
# =========================================================

async def save_alert_delivery(
    *,
    alert_type: str,
    minimum_tier: str,
    discord_channel_id: int,
    discord_message_id: int,
):

    if SessionLocal is None:

        return False


    try:

        async with SessionLocal() as session:

            record = (
                Alert(

                    product_id=None,

                    store_id=None,

                    alert_type=(
                        alert_type
                    ),

                    minimum_tier=(
                        minimum_tier
                    ),

                    discord_channel_id=(
                        discord_channel_id
                    ),

                    discord_message_id=(
                        discord_message_id
                    ),
                )
            )


            session.add(
                record
            )


            await session.commit()


        return True


    except Exception as error:

        print(
            (
                "ALERT DELIVERY SAVE ERROR | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )


        return False