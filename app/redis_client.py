import os

import redis.asyncio as redis


# =========================================================
# LOTUS REDIS CLIENT
# PonDeX Trackers
# Version 0.7.4a
#
# Stable blocking queue support
# Railway Redis support
# Automatic connection verification
# =========================================================


REDIS_URL = os.getenv(
    "REDIS_URL"
)


_redis_client = None


# =========================================================
# NORMALIZE URL
# =========================================================

def normalize_redis_url(
    url: str | None,
):

    if not url:

        return None

    return url.strip()


# =========================================================
# INITIALIZE REDIS
# =========================================================

async def init_redis():

    global _redis_client

    redis_url = normalize_redis_url(
        REDIS_URL
    )

    if not redis_url:

        raise RuntimeError(
            "REDIS_URL is missing."
        )

    # Close an old client before replacing it.

    if _redis_client is not None:

        try:

            await _redis_client.aclose()

        except Exception:

            pass

        _redis_client = None

    # -----------------------------------------------------
    # socket_timeout=None is intentional.
    #
    # Lotus uses blocking Redis commands such as BLPOP.
    # A short socket read timeout causes:
    #
    # Timeout reading from redis.railway.internal:6379
    #
    # BLPOP itself already has its own queue timeout.
    # -----------------------------------------------------

    _redis_client = redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=None,
        health_check_interval=30,
        retry_on_timeout=True,
    )

    try:

        pong = await _redis_client.ping()

        if not pong:

            raise RuntimeError(
                "Redis did not respond to PING."
            )

    except Exception:

        try:

            await _redis_client.aclose()

        except Exception:

            pass

        _redis_client = None

        raise

    print(
        "Redis initialized successfully."
    )

    return _redis_client


# =========================================================
# GET CLIENT
# =========================================================

def get_redis():

    return _redis_client


# =========================================================
# HEALTH CHECK
# =========================================================

async def check_redis():

    global _redis_client

    if _redis_client is None:

        return False

    try:

        return bool(
            await _redis_client.ping()
        )

    except Exception as error:

        print(
            (
                "REDIS HEALTH CHECK FAILED: "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return False


# =========================================================
# CLOSE
# =========================================================

async def close_redis():

    global _redis_client

    if _redis_client is None:

        return

    try:

        await _redis_client.aclose()

    finally:

        _redis_client = None