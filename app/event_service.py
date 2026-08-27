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
# Version 0.7.9
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
# SERIALIZE EVENT
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

        # =================================================
        # PRICE DATA
        # =================================================

        "price":
            event.price,

        "old_price":
            getattr(
                event,
                "old_price",
                None,
            ),

        "currency":
            event.currency,

        # =================================================
        # INVENTORY
        # =================================================

        "in_stock":
            event.in_stock,

        # =================================================
        # PRODUCT METADATA
        # =================================================

        "region":
            event.region,

        "language":
            event.language,

        "product_type":
            event.product_type,

        "product_category":
            getattr(
                event,
                "product_category",
                "UNKNOWN",
            ),

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
        # QUICK CART / SMART CART
        # =================================================

        "variant_id":
            getattr(
                event,
                "variant_id",
                None,
            ),

        "purchase_limit":
            getattr(
                event,
                "purchase_limit",
                None,
            ),

        "cart_base_url":
            getattr(
                event,
                "cart_base_url",
                None,
            ),

        # =================================================
        # TIMESTAMP
        # =================================================

        "timestamp": (
            event.timestamp.isoformat()
            if event.timestamp
            else None
        ),
    }


# =========================================================
# SAVE DATABASE EVENT
# =========================================================

async def save_product_event(
    event: ProductEvent,
):

    if SessionLocal is None:

        return False

    try:

        async with SessionLocal() as session:

            record = ProductEventRecord(

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
# REDIS QUEUE
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
                f"Source={payload['source_type']} | "
                f"Store={payload['store_name']} | "
                f"Category={payload['product_category']} | "
                f"Price={payload['price']} | "
                f"OldPrice={payload['old_price']} | "
                f"Variant={payload['variant_id']} | "
                f"Limit={payload['purchase_limit']} | "
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
# POP EVENT
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
# CLEAR ONLY LOTUS PRODUCT EVENT QUEUE
#
# This does NOT flush Redis.
# It does NOT delete database records.
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
# SAVE ALERT DELIVERY
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