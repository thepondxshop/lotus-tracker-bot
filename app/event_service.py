import json

from sqlalchemy import select

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
# Version 0.7.6a
#
# PostgreSQL event history
# Redis event queue
# Source-aware event serialization
# Product-image serialization
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
# EVENT -> REDIS DICTIONARY
# =========================================================

def serialize_product_event(
    event: ProductEvent,
):

    return {

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

        "price":
            event.price,

        "currency":
            event.currency,

        "in_stock":
            event.in_stock,

        "region":
            event.region,

        "language":
            event.language,

        "product_type":
            event.product_type,

        # =================================================
        # v0.7.6 SOURCE ROUTING
        # =================================================

        "source_type":
            event.source_type,

        "retailer_key":
            event.retailer_key,

        # =================================================
        # PRODUCT IMAGE
        # =================================================

        "image_url":
            event.image_url,

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

                    game=event.game,

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

                    price=event.price,

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
                f"Image="
                f"{bool(payload['image_url'])}"
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

    result = await redis_client.blpop(
        EVENT_QUEUE_KEY,
        timeout=timeout,
    )

    if not result:

        return None

    _, raw_payload = (
        result
    )

    try:

        event = json.loads(
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

            record = Alert(

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