import time

from app.redis_client import (
    get_redis,
)


# =========================================================
# LOTUS INVENTORY FLICKER ENGINE
# PonDeX Trackers
# Version 0.6.1
# =========================================================


FLICKER_WINDOW_SECONDS = 180

FLICKER_MIN_TRANSITIONS = 3


# =========================================================
# RECORD STOCK TRANSITION
# =========================================================

async def record_stock_transition(
    store_product_id: int,
    in_stock: bool,
):
    """
    Records a legitimate inventory transition.

    Example:

    OUT
    IN
    OUT
    IN

    When enough transitions happen inside the configured
    window, Lotus classifies the product as inventory
    flickering.

    IMPORTANT:
    This does NOT suppress transitions.
    """

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return {
            "flickering": False,
            "transition_count": 0,
        }

    now = time.time()

    history_key = (
        f"lotus:flicker:"
        f"{store_product_id}"
    )

    state = (
        "IN"
        if in_stock
        else "OUT"
    )

    # Unique member so multiple transitions within
    # the same second are still retained.

    member = (
        f"{now}:{state}"
    )

    try:

        await redis_client.zadd(
            history_key,
            {
                member: now
            },
        )

        cutoff = (
            now
            - FLICKER_WINDOW_SECONDS
        )

        await redis_client.zremrangebyscore(
            history_key,
            0,
            cutoff,
        )

        # Keep this history around only temporarily.

        await redis_client.expire(
            history_key,
            FLICKER_WINDOW_SECONDS
            * 2,
        )

        transition_count = (
            await redis_client.zcard(
                history_key
            )
        )

        flickering = (
            transition_count
            >= FLICKER_MIN_TRANSITIONS
        )

        return {
            "flickering": flickering,
            "transition_count": (
                transition_count
            ),
        }

    except Exception as error:

        print(
            "FLICKER ENGINE ERROR: "
            f"{type(error).__name__}: {error}"
        )

        return {
            "flickering": False,
            "transition_count": 0,
        }


# =========================================================
# GET RECENT FLICKER HISTORY
# =========================================================

async def get_flicker_history(
    store_product_id: int,
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return []

    history_key = (
        f"lotus:flicker:"
        f"{store_product_id}"
    )

    try:

        entries = (
            await redis_client.zrange(
                history_key,
                0,
                -1,
                withscores=True,
            )
        )

        history = []

        for member, timestamp in entries:

            parts = (
                member.split(
                    ":"
                )
            )

            state = (
                parts[-1]
                if parts
                else "UNKNOWN"
            )

            history.append(
                {
                    "state": state,
                    "timestamp": timestamp,
                }
            )

        return history

    except Exception as error:

        print(
            "FLICKER HISTORY ERROR: "
            f"{type(error).__name__}: {error}"
        )

        return []


# =========================================================
# SETTINGS / STATUS
# =========================================================

def get_flicker_settings():

    return {
        "window_seconds":
            FLICKER_WINDOW_SECONDS,

        "minimum_transitions":
            FLICKER_MIN_TRANSITIONS,
    }