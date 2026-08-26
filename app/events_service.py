import json

from sqlalchemy import (
    select,
)

from app.database import (
    SessionLocal,
)

from app.events import (
    ProductEvent,
)

from app.models import (
    ProductEventRecord,
)

from app.redis_client import (
    get_redis,
)


# =========================================================
# LOTUS EVENT SERVICE
# PonDeX Trackers
# Version 0.5
# =========================================================


REDIS_EVENT_QUEUE = (
    "lotus:product_events"
)


# =========================================================
# SAVE EVENT TO POSTGRESQL
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
# PUSH EVENT TO REDIS
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
        )
    )


# =========================================================
# PROCESS EVENT
# =========================================================

async def process_product_event(
    event: ProductEvent
):

    database_record = None
    redis_saved = False

    # PostgreSQL
    try:

        database_record = (
            await save_event_to_database(
                event
            )
        )

    except Exception as error:

        print(
            "EVENT DATABASE ERROR: "
            f"{type(error).__name__}: {error}"
        )

    # Redis
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
            database_record is not None
        ),
        "redis_saved": (
            redis_saved
        ),
    }


# =========================================================
# REDIS QUEUE SIZE
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

    except Exception:

        return 0