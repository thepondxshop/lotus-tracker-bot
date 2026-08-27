import json

from app.database import SessionLocal

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
# Version 1.0.0
#
# Redis Event Queue
# Product Event History
# Historical Pricing
# MSRP Intelligence
# Scalper Protection
# Deal Score
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

        return value.value

    return str(
        value
    )


# =========================================================
# SERIALIZE PRODUCT EVENT
# =========================================================

def serialize_product_event(
    event: ProductEvent,
):

    return {

        # =================================================
        # EVENT
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
        # HISTORICAL PRICING
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
        # MSRP / REFERENCE PRICE
        #
        # msrp:
        # Converted comparison MSRP in current store
        # currency.
        #
        # msrp_original:
        # Original verified reference amount.
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
        # MSRP ANALYSIS
        # =================================================

        "price_vs_msrp_pct":
            event.price_vs_msrp_pct,

        "markup_amount":
            event.markup_amount,

        "msrp_price_state":
            event.msrp_price_state,

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
        # INVENTORY
        # =================================================

        "in_stock":
            event.in_stock,


        # =================================================
        # PRODUCT
        # =================================================

        "region":
            event.region,

        "language":
            event.language,

        "product_type":
            event.product_type,

        "product_category":
            event.product_category,


        # =================================================
        # SOURCE
        # =================================================

        "source_type":
            event.source_type,

        "retailer_key":
            event.retailer_key,

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
            (
                "EVENT REDIS SAVE ERROR | "
                "Redis unavailable"
            )
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
                f"Game={payload['game']} | "
                f"Store={payload['store_name']} | "
                f"Price={payload['price']} | "
                f"Currency={payload['currency']} | "
                f"OldPrice={payload['old_price']} | "
                f"MSRP={payload['msrp']} | "
                f"MSRPCurrency={payload['msrp_currency']} | "
                f"OriginalMSRP={payload['msrp_original']} | "
                f"OriginalMSRPCurrency="
                f"{payload['msrp_original_currency']} | "
                f"MSRPConverted="
                f"{payload['msrp_conversion_used']} | "
                f"VsMSRP="
                f"{payload['price_vs_msrp_pct']} | "
                f"ScalperRisk="
                f"{payload['scalper_risk']} | "
                f"DealScore="
                f"{payload['deal_score']} | "
                f"Confidence="
                f"{payload['deal_confidence']} | "
                f"Samples="
                f"{payload['price_history_samples']} | "
                f"Category="
                f"{payload['product_category']} | "
                f"Variant="
                f"{payload['variant_id']} | "
                f"Limit="
                f"{payload['purchase_limit']}"
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
# PROCESS PRODUCT EVENT
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

            timeout=timeout,
        )
    )


    if not result:

        return None


    _, raw_payload = (
        result
    )


    try:

        return json.loads(
            raw_payload
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
#
# Only removes:
#
# lotus:product_events
#
# PostgreSQL history and other Redis keys remain untouched.
# =========================================================

async def clear_event_queue():

    redis_client = (
        get_redis()
    )


    if redis_client is None:

        return 0


    try:

        existing = int(

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
                f"Removed={existing}"
            )
        )


        return existing


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
# SAVE DISCORD ALERT DELIVERY
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