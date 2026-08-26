import asyncio

from datetime import datetime

import aiohttp


from app.event_service import (
    process_product_event,
)

from app.events import (
    ProductEvent,
    ProductEventType,
)

from app.redis_client import (
    get_redis,
)


# =========================================================
# POKEMON CENTER QUEUE INTELLIGENCE
# PonDeX Trackers
# Version 0.7.3
#
# Public queue-state observation only.
#
# Queue events automatically trigger Pokémon Center
# product discovery / monitoring burst mode.
# =========================================================


POKEMON_CENTER_URLS = {

    "US":
        "https://www.pokemoncenter.com/",

    "CA":
        "https://www.pokemoncenter.com/en-ca",

    "UK":
        "https://www.pokemoncenter.com/en-gb",

    "DE":
        "https://www.pokemoncenter.com/en-de",

    "AU":
        "https://www.pokemoncenter.com/en-au",

    "NZ":
        "https://www.pokemoncenter.com/en-nz",
}


POLL_SECONDS = 30


QUEUE_CACHE_PREFIX = (
    "lotus:pokemon_center:queue:"
)


QUEUE_HOST_HINTS = (

    "queue-it",

    "queueit",

    "waitingroom",

    "waiting-room",
)


QUEUE_TEXT_HINTS = (

    "virtual queue",

    "waiting room",

    "you are now in line",

    "you are in line",

    "estimated wait time",

    "waiting to enter",
)


MONITOR_STATUS = {

    "running":
        False,

    "last_scan":
        None,

    "regions_checked":
        0,

    "queues_active":
        0,

    "events_created":
        0,

    "burst_triggers":
        0,

    "last_error":
        None,
}


# =========================================================
# QUEUE DETECTION
# =========================================================

def response_looks_like_queue(
    final_url: str,
    body: str,
):

    final_url_lower = (
        final_url.lower()
    )

    body_lower = (
        body.lower()
    )

    if any(
        hint in final_url_lower
        for hint in QUEUE_HOST_HINTS
    ):

        return True

    if any(
        hint in body_lower
        for hint in QUEUE_TEXT_HINTS
    ):

        return True

    return False


# =========================================================
# REDIS STATE
# =========================================================

async def get_previous_queue_state(
    region: str,
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return None

    value = (
        await redis_client.get(
            (
                QUEUE_CACHE_PREFIX
                + region
            )
        )
    )

    if value is None:

        return None

    return (
        value == "1"
    )


async def set_queue_state(
    region: str,
    active: bool,
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return

    await redis_client.set(
        (
            QUEUE_CACHE_PREFIX
            + region
        ),
        (
            "1"
            if active
            else "0"
        ),
    )


# =========================================================
# PRODUCT BURST TRIGGER
#
# Import happens inside the function intentionally.
#
# This avoids a circular import between the queue monitor
# and product monitor.
# =========================================================

async def trigger_queue_product_burst(
    region: str,
):

    try:

        from app.pokemon_center_products import (
            trigger_product_burst,
        )

        success = (
            await trigger_product_burst(
                region
            )
        )

        if success:

            MONITOR_STATUS[
                "burst_triggers"
            ] += 1

            print(
                (
                    "QUEUE -> PRODUCT BURST: "
                    f"{region}"
                )
            )

        return success

    except Exception as error:

        print(
            (
                "QUEUE BURST TRIGGER ERROR: "
                f"{region} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return False


# =========================================================
# CHECK REGION
# =========================================================

async def check_region(
    session,
    region: str,
    url: str,
):

    async with session.get(
        url,
        allow_redirects=True,
    ) as response:

        final_url = str(
            response.url
        )

        body = (
            await response.text(
                errors="ignore"
            )
        )

        queue_active = (
            response_looks_like_queue(
                final_url,
                body,
            )
        )

        return {

            "region":
                region,

            "original_url":
                url,

            "final_url":
                final_url,

            "http_status":
                response.status,

            "queue_active":
                queue_active,
        }


# =========================================================
# QUEUE EVENT
# =========================================================

async def create_queue_event(
    region: str,
    event_type: ProductEventType,
    url: str,
):

    event = (
        ProductEvent(

            event_type=event_type,

            game="Pokemon",

            product_name=(
                f"Pokémon Center "
                f"{region} Virtual Queue"
            ),

            store_name=(
                "Pokémon Center"
            ),

            product_url=url,

            price=None,

            currency="USD",

            in_stock=False,

            region=region,

            language="English",

            product_type=(
                "Virtual Queue"
            ),
        )
    )

    return await process_product_event(
        event
    )


# =========================================================
# SCAN
# =========================================================

async def scan_pokemon_center():

    timeout = (
        aiohttp.ClientTimeout(
            total=20
        )
    )

    headers = {

        "Accept":
            (
                "text/html,"
                "application/xhtml+xml"
            ),

        "Accept-Language":
            "en-US,en;q=0.9",

        "User-Agent":
            "PonDeX-Trackers/0.7.3",
    }

    results = []

    events_created = 0

    active_count = 0

    MONITOR_STATUS[
        "last_error"
    ] = None

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:

        for (
            region,
            url,
        ) in POKEMON_CENTER_URLS.items():

            try:

                result = (
                    await check_region(
                        session,
                        region,
                        url,
                    )
                )

                current = (
                    result[
                        "queue_active"
                    ]
                )

                previous = (
                    await get_previous_queue_state(
                        region
                    )
                )

                # =========================================
                # FIRST OBSERVATION
                # =========================================

                if previous is None:

                    await set_queue_state(
                        region,
                        current,
                    )

                    if current:

                        event_result = (
                            await create_queue_event(

                                region,

                                ProductEventType.QUEUE_DETECTED,

                                result[
                                    "final_url"
                                ],
                            )
                        )

                        if event_result[
                            "redis_saved"
                        ]:

                            events_created += 1

                        # ---------------------------------
                        # Queue already active when Lotus
                        # starts. Begin product burst.
                        # ---------------------------------

                        await trigger_queue_product_burst(
                            region
                        )

                # =========================================
                # QUEUE ACTIVATED
                # =========================================

                elif (
                    previous is False
                    and current is True
                ):

                    await set_queue_state(
                        region,
                        True,
                    )

                    event_result = (
                        await create_queue_event(

                            region,

                            ProductEventType.QUEUE_ACTIVE,

                            result[
                                "final_url"
                            ],
                        )
                    )

                    if event_result[
                        "redis_saved"
                    ]:

                        events_created += 1

                    # -------------------------------------
                    # Automatic 5-minute burst.
                    # -------------------------------------

                    await trigger_queue_product_burst(
                        region
                    )

                # =========================================
                # QUEUE CLEARED
                # =========================================

                elif (
                    previous is True
                    and current is False
                ):

                    await set_queue_state(
                        region,
                        False,
                    )

                    event_result = (
                        await create_queue_event(

                            region,

                            ProductEventType.QUEUE_CLEARED,

                            result[
                                "original_url"
                            ],
                        )
                    )

                    if event_result[
                        "redis_saved"
                    ]:

                        events_created += 1

                    # -------------------------------------
                    # This may be the most important scan:
                    # products can become accessible after
                    # the waiting room clears.
                    # -------------------------------------

                    await trigger_queue_product_burst(
                        region
                    )

                if current:

                    active_count += 1

                results.append(
                    result
                )

            except Exception as error:

                error_text = (
                    f"{region}: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                print(
                    (
                        "POKEMON CENTER "
                        "QUEUE ERROR: "
                        f"{error_text}"
                    )
                )

                MONITOR_STATUS[
                    "last_error"
                ] = (
                    error_text
                )

    MONITOR_STATUS[
        "last_scan"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "regions_checked"
    ] = len(
        results
    )

    MONITOR_STATUS[
        "queues_active"
    ] = (
        active_count
    )

    MONITOR_STATUS[
        "events_created"
    ] = (
        events_created
    )

    return results


# =========================================================
# BACKGROUND MONITOR
# =========================================================

async def run_pokemon_center_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

    print(
        (
            "Pokémon Center Queue "
            "Monitor v0.7.3 started."
        )
    )

    await asyncio.sleep(
        15
    )

    while True:

        try:

            await scan_pokemon_center()

        except asyncio.CancelledError:

            MONITOR_STATUS[
                "running"
            ] = False

            print(
                (
                    "Pokémon Center "
                    "Queue Monitor stopped."
                )
            )

            raise

        except Exception as error:

            MONITOR_STATUS[
                "last_error"
            ] = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            print(
                (
                    "POKEMON CENTER LOOP ERROR: "
                    f"{MONITOR_STATUS['last_error']}"
                )
            )

        await asyncio.sleep(
            POLL_SECONDS
        )


# =========================================================
# STATUS
# =========================================================

def get_pokemon_center_status():

    return dict(
        MONITOR_STATUS
    )