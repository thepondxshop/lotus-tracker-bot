import os

import redis.asyncio as redis


# =========================================================
# LOTUS TRACKER REDIS CLIENT
# PonDeX Trackers
# Version 0.5
# =========================================================


REDIS_URL = os.getenv("REDIS_URL")


redis_client = None


# =========================================================
# CONNECT TO REDIS
# =========================================================

async def init_redis():

    global redis_client

    if not REDIS_URL:

        raise RuntimeError(
            "REDIS_URL is missing."
        )

    redis_client = redis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    await redis_client.ping()

    return redis_client


# =========================================================
# GET CLIENT
# =========================================================

def get_redis():

    return redis_client


# =========================================================
# HEALTH CHECK
# =========================================================

async def check_redis():

    if redis_client is None:

        return False

    try:

        result = await redis_client.ping()

        return bool(
            result
        )

    except Exception:

        return False