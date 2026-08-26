import json

from sqlalchemy import select

from app.database import SessionLocal

from app.events import ProductEvent

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
# Version 0.5.1
# =========================================================


REDIS_EVENT_QUEUE = (
    "lotus:product_events"
)


# =========================================================
# SAVE PRODUCT EVENT TO POSTGRESQL
# =========================================================

async def save_event_to_database(
    event: ProductEvent
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database not configured."
        )

    async with SessionLocal() as session:

        record = ProductEventRecord(
            game=event.game,
            product_name=event.product_name,
            store_name=event.store_name,
            product_url=event.product_url,
            event_type=event.event_type.value,
            price=event.price,
            currency=event.currency,
            in_stock=event.in_stock,
            region=event.region,
            language=event.language,
            product_type=event.product_type,
        )

        session.add(
            record
        )

        await session.commit()

        return record


# =========================================================
# PUSH PRODUCT EVENT INTO REDIS
# =========================================================

async def push_event_to_redis(
    event: ProductEvent
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        raise RuntimeError(
            "Redis is not configured."
        )

    payload = {

        "event_type": (
            event.event_type.value
        ),

        "game": (
            event.game
        ),

        "product_name": (
            event.product_name
        ),

        "store_name": (
            event.store_name
        ),

        "product_url": (
            event.product_url
        ),

        "price": (
            event.price
        ),

        "currency": (
            event.currency
        ),

        "in_stock": (
            event.in_stock
        ),

        "region": (
            event.region
        ),

        "language": (
            event.language
        ),

        "product_type": (
            event.product_type
        ),

        "timestamp": (
            event.timestamp.isoformat()
        ),
    }

    await redis_client.rpush(
        REDIS_EVENT_QUEUE,
        json.dumps(
            payload
        ),
    )


# =========================================================
# PROCESS NEW PRODUCT EVENT
# =========================================================

async def process_product_event(
    event: ProductEvent
):

    database_saved = False
    redis_saved = False

    # -----------------------------------------------------
    # SAVE HISTORY
    # -----------------------------------------------------

    try:

        await save_event_to_database(
            event
        )

        database_saved = True

    except Exception as error:

        print(
            "EVENT DATABASE ERROR: "
            f"{type(error).__name__}: {error}"
        )

    # -----------------------------------------------------
    # QUEUE EVENT
    # -----------------------------------------------------

    try:

        await push_event_to_redis(
            event
        )

        redis_saved = True

    except Exception as error:

        print(
            "EVENT REDIS ERROR: "
            f"{type(error).__name__}: {error}"
        )

    return {

        "database_saved": (
            database_saved
        ),

        "redis_saved": (
            redis_saved
        ),
    }


# =========================================================
# POP NEXT EVENT FROM REDIS
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
            REDIS_EVENT_QUEUE,
            timeout=timeout,
        )
    )

    if not result:

        return None

    _, payload = result

    try:

        return json.loads(
            payload
        )

    except json.JSONDecodeError as error:

        print(
            "INVALID REDIS EVENT: "
            f"{error}"
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

        return await redis_client.llen(
            REDIS_EVENT_QUEUE
        )

    except Exception as error:

        print(
            "REDIS QUEUE ERROR: "
            f"{type(error).__name__}: {error}"
        )

        return 0


# =========================================================
# SAVE DELIVERED DISCORD ALERT
# =========================================================

async def save_alert_delivery(
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

                alert_type=alert_type,

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
            "ALERT HISTORY ERROR: "
            f"{type(error).__name__}: {error}"
        )

        return False