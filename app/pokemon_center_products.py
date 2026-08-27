import asyncio
import html as html_lib
import os
import re

from datetime import (
    datetime,
    timedelta,
)

from urllib.parse import urlparse

import aiohttp

from sqlalchemy import select

from app.database import SessionLocal
from app.event_service import process_product_event
from app.events import ProductEvent, ProductEventType
from app.models import PokemonCenterProduct
from app.redis_client import get_redis


# =========================================================
# LOTUS POKEMON CENTER PRODUCT INTELLIGENCE
# Version 0.7.5
#
# Persistent registry
# Indexed discovery
# Product monitoring
# Scan diagnostics
# Blocked-request backoff
# Queue burst mode
# =========================================================


SERPER_API_KEY = os.getenv(
    "SERPER_API_KEY"
)

SERPER_ENDPOINT = (
    "https://google.serper.dev/search"
)


REGIONS = {

    "US":
        "https://www.pokemoncenter.com/",

    "CA":
        "https://www.pokemoncenter.com/en-ca/",

    "UK":
        "https://www.pokemoncenter.com/en-gb/",

    "DE":
        "https://www.pokemoncenter.com/en-de/",

    "AU":
        "https://www.pokemoncenter.com/en-au/",

    "NZ":
        "https://www.pokemoncenter.com/en-nz/",
}


NORMAL_POLL_SECONDS = 90
BURST_POLL_SECONDS = 15
BURST_DURATION_SECONDS = 300

BLOCK_COOLDOWN_MINUTES = 30

DISCOVERY_EVERY_LOOPS = 10


BURST_KEY_PREFIX = (
    "lotus:pokemon_center:burst:"
)


INDEX_QUERIES = [

    'site:pokemoncenter.com/product "Pokemon TCG"',

    'site:pokemoncenter.com/product "Elite Trainer Box"',

    'site:pokemoncenter.com/product "Booster Bundle"',

    'site:pokemoncenter.com/product "Booster Pack"',

    'site:pokemoncenter.com/product "Premium Collection"',

    'site:pokemoncenter.com/product "Special Collection"',

    'site:pokemoncenter.com/product "Collector Chest"',

    'site:pokemoncenter.com/product "Mini Tin"',

    'site:pokemoncenter.com/product "Pokemon Center Elite Trainer Box"',

    'site:pokemoncenter.com/product "Trading Card Game"',
]


MONITOR_STATUS = {

    "running":
        False,

    "last_scan":
        None,

    "last_discovery":
        None,

    "known_products":
        0,

    "products_checked":
        0,

    "products_skipped_backoff":
        0,

    "successful_products":
        0,

    "blocked_products":
        0,

    "events_created":
        0,

    "indexed_products_discovered":
        0,

    "index_queries_run":
        0,

    "index_results_seen":
        0,

    "burst_regions":
        0,

    "last_error":
        None,
}


# =========================================================
# URL HELPERS
# =========================================================

def normalize_product_url(
    url: str,
):

    if not url:

        raise ValueError(
            "Product URL is empty."
        )

    url = html_lib.unescape(
        url.strip()
    )

    url = (
        url
        .replace(
            "\\/",
            "/"
        )
        .replace(
            "\\u002F",
            "/"
        )
    )

    if url.startswith(
        "/"
    ):

        url = (
            "https://www.pokemoncenter.com"
            + url
        )

    parsed = urlparse(
        url
    )

    if not parsed.scheme:

        url = (
            "https://www.pokemoncenter.com/"
            + url.lstrip("/")
        )

        parsed = urlparse(
            url
        )

    hostname = (
        parsed.hostname
        or ""
    ).lower()

    if hostname not in {
        "pokemoncenter.com",
        "www.pokemoncenter.com",
    }:

        raise ValueError(
            "Not a Pokémon Center URL."
        )

    path = (
        parsed.path
        or ""
    )

    if "/product/" not in path.lower():

        raise ValueError(
            "URL is not a Pokémon Center product page."
        )

    return (
        "https://www.pokemoncenter.com"
        + path.rstrip("/")
    )


def extract_product_code(
    url: str,
):

    match = re.search(
        r"/product/([^/?#]+)",
        url,
        flags=re.IGNORECASE,
    )

    if not match:

        return None

    return (
        match.group(
            1
        )
        .strip()
        .upper()
    )


# =========================================================
# REGISTRY
# =========================================================

async def add_pokemon_product(
    url: str,
    region: str = "US",
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database unavailable."
        )

    region = (
        region.upper()
    )

    if region not in REGIONS:

        raise ValueError(
            "Unsupported region."
        )

    clean_url = (
        normalize_product_url(
            url
        )
    )

    code = (
        extract_product_code(
            clean_url
        )
    )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                PokemonCenterProduct
            ).where(
                PokemonCenterProduct.url
                == clean_url
            )
        )

        existing = (
            result.scalars().first()
        )

        if existing:

            existing.active = True
            existing.region = region

            await session.commit()

            await session.refresh(
                existing
            )

            return (
                existing,
                False,
            )

        product = PokemonCenterProduct(

            region=region,

            url=clean_url,

            product_code=code,

            active=True,

            scan_status=(
                "NOT_SCANNED"
            ),

            block_count=0,
        )

        session.add(
            product
        )

        await session.commit()

        await session.refresh(
            product
        )

        return (
            product,
            True,
        )


async def list_pokemon_products(
    active_only: bool = True,
):

    if SessionLocal is None:

        return []

    async with SessionLocal() as session:

        query = (
            select(
                PokemonCenterProduct
            )
            .order_by(
                PokemonCenterProduct.id.asc()
            )
        )

        if active_only:

            query = query.where(
                PokemonCenterProduct.active
                == True
            )

        result = await session.execute(
            query
        )

        return list(
            result.scalars().all()
        )


async def remove_pokemon_product(
    product_id: int,
):

    if SessionLocal is None:

        return None

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                PokemonCenterProduct
            ).where(
                PokemonCenterProduct.id
                == product_id
            )
        )

        product = (
            result.scalars().first()
        )

        if product is None:

            return None

        product.active = False

        await session.commit()

        await session.refresh(
            product
        )

        return product


async def restore_pokemon_product(
    product_id: int,
):

    if SessionLocal is None:

        return None

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                PokemonCenterProduct
            ).where(
                PokemonCenterProduct.id
                == product_id
            )
        )

        product = (
            result.scalars().first()
        )

        if product is None:

            return None

        product.active = True
        product.last_error = None

        await session.commit()

        await session.refresh(
            product
        )

        return product


# =========================================================
# SERPER DISCOVERY
# =========================================================

async def indexed_product_discovery():

    if not SERPER_API_KEY:

        return 0

    timeout = (
        aiohttp.ClientTimeout(
            total=30
        )
    )

    headers = {

        "X-API-KEY":
            SERPER_API_KEY,

        "Content-Type":
            "application/json",

        "Accept":
            "application/json",
    }

    queries_run = 0
    results_seen = 0
    new_count = 0

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        for query in INDEX_QUERIES:

            try:

                async with session.post(
                    SERPER_ENDPOINT,
                    json={
                        "q":
                            query
                    },
                    headers=headers,
                ) as response:

                    body = (
                        await response.text(
                            errors="ignore"
                        )
                    )

                    if response.status != 200:

                        print(
                            (
                                "SERPER ERROR | "
                                f"HTTP={response.status} | "
                                f"Body={body[:500]}"
                            )
                        )

                        continue

                    data = (
                        await response.json()
                    )

                    queries_run += 1

                    organic = (
                        data.get(
                            "organic",
                            []
                        )
                    )

                    for item in organic:

                        link = (
                            item.get(
                                "link"
                            )
                        )

                        title = (
                            item.get(
                                "title",
                                ""
                            )
                        )

                        if not link:

                            continue

                        results_seen += 1

                        try:

                            product, created = (
                                await add_pokemon_product(
                                    link,
                                    "US",
                                )
                            )

                            if title:

                                async with SessionLocal() as db:

                                    result = await db.execute(

                                        select(
                                            PokemonCenterProduct
                                        ).where(
                                            PokemonCenterProduct.id
                                            == product.id
                                        )
                                    )

                                    stored = (
                                        result.scalars().first()
                                    )

                                    if stored:

                                        stored.title = (
                                            title[
                                                :500
                                            ]
                                        )

                                        await db.commit()

                            if created:

                                new_count += 1

                        except ValueError:

                            continue

            except Exception as error:

                print(
                    (
                        "SERPER DISCOVERY ERROR | "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )
                )

            await asyncio.sleep(
                0.3
            )

    MONITOR_STATUS[
        "last_discovery"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "indexed_products_discovered"
    ] = (
        new_count
    )

    MONITOR_STATUS[
        "index_queries_run"
    ] = (
        queries_run
    )

    MONITOR_STATUS[
        "index_results_seen"
    ] = (
        results_seen
    )

    return (
        new_count
    )


async def discover_pokemon_products():

    return await indexed_product_discovery()


# =========================================================
# HTML
# =========================================================

def clean_html(
    value: str,
):

    value = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        value,
        flags=(
            re.IGNORECASE
            |
            re.DOTALL
        ),
    )

    value = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        value,
        flags=(
            re.IGNORECASE
            |
            re.DOTALL
        ),
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = html_lib.unescape(
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def extract_title(
    html: str,
):

    match = re.search(
        r"<title[^>]*>(.*?)</title>",
        html,
        flags=(
            re.IGNORECASE
            |
            re.DOTALL
        ),
    )

    if not match:

        return (
            "Unknown Pokémon Center Product"
        )

    return (
        clean_html(
            match.group(
                1
            )
        )
    )


def extract_price(
    html: str,
):

    patterns = [

        r'"price"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',

        r'\$\s*([0-9]+(?:\.[0-9]{2})?)',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            flags=(
                re.IGNORECASE
            ),
        )

        if not match:

            continue

        try:

            return float(
                match.group(
                    1
                )
            )

        except Exception:

            continue

    return None


def classify_product_state(
    html: str,
):

    text = (
        clean_html(
            html
        ).lower()
    )

    if (
        "preorder: add to cart"
        in text
        or
        "preorder: add to basket"
        in text
    ):

        return (
            "PREORDER_LIVE",
            True,
        )

    if (
        "add to cart"
        in text
        or
        "add to basket"
        in text
    ):

        return (
            "STOCK_AVAILABLE",
            True,
        )

    if (
        "coming soon"
        in text
    ):

        return (
            "COMING_SOON",
            False,
        )

    if (
        "sold out"
        in text
        or
        "out of stock"
        in text
    ):

        return (
            "SOLD_OUT",
            False,
        )

    return (
        "PAGE_LIVE",
        False,
    )


# =========================================================
# EVENT
# =========================================================

async def emit_product_event(
    product,
    event_type,
    title,
    price,
    available,
):

    return await process_product_event(

        ProductEvent(

            event_type=event_type,

            game="Pokemon",

            product_name=title,

            store_name="Pokémon Center",

            product_url=(
                product.url
            ),

            price=price,

            currency="USD",

            in_stock=available,

            region=(
                product.region
            ),

            language="English",

            product_type=(
                "Pokémon TCG Product"
            ),
        )
    )


# =========================================================
# SCAN STATUS HELPERS
# =========================================================

async def save_blocked_scan(
    product_id: int,
    http_status: int,
):

    async with SessionLocal() as db:

        result = await db.execute(

            select(
                PokemonCenterProduct
            ).where(
                PokemonCenterProduct.id
                == product_id
            )
        )

        stored = (
            result.scalars().first()
        )

        if stored is None:

            return

        stored.scan_status = (
            "BLOCKED"
        )

        stored.last_http_status = (
            http_status
        )

        stored.last_scan_attempt_at = (
            datetime.utcnow()
        )

        stored.block_count = (
            (
                stored.block_count
                or 0
            )
            + 1
        )

        stored.blocked_until = (
            datetime.utcnow()
            + timedelta(
                minutes=(
                    BLOCK_COOLDOWN_MINUTES
                )
            )
        )

        stored.last_error = (
            f"HTTP {http_status}"
        )

        await db.commit()


async def save_scan_error(
    product_id: int,
    error_text: str,
):

    async with SessionLocal() as db:

        result = await db.execute(

            select(
                PokemonCenterProduct
            ).where(
                PokemonCenterProduct.id
                == product_id
            )
        )

        stored = (
            result.scalars().first()
        )

        if stored is None:

            return

        stored.scan_status = (
            "ERROR"
        )

        stored.last_scan_attempt_at = (
            datetime.utcnow()
        )

        stored.last_error = (
            error_text[
                :2000
            ]
        )

        await db.commit()


# =========================================================
# SCAN PRODUCT
# =========================================================

async def scan_registered_product(
    session,
    product,
):

    now = (
        datetime.utcnow()
    )

    if (
        product.blocked_until
        and product.blocked_until
        > now
    ):

        return {

            "success":
                False,

            "blocked":
                False,

            "skipped_backoff":
                True,

            "events":
                0,
        }

    async with session.get(
        product.url,
        allow_redirects=True,
    ) as response:

        if response.status in (
            401,
            403,
            429,
        ):

            await save_blocked_scan(
                product.id,
                response.status,
            )

            return {

                "success":
                    False,

                "blocked":
                    True,

                "skipped_backoff":
                    False,

                "events":
                    0,
            }

        if response.status != 200:

            await save_scan_error(
                product.id,
                (
                    f"HTTP "
                    f"{response.status}"
                ),
            )

            return {

                "success":
                    False,

                "blocked":
                    False,

                "skipped_backoff":
                    False,

                "events":
                    0,
            }

        html = (
            await response.text(
                errors="ignore"
            )
        )

    title = (
        extract_title(
            html
        )
    )

    price = (
        extract_price(
            html
        )
    )

    state, available = (
        classify_product_state(
            html
        )
    )

    events_created = 0

    old_state = (
        product.last_state
    )

    old_available = bool(
        product.last_available
    )

    old_price = (
        product.last_price
    )

    if old_state is None:

        result = await emit_product_event(

            product,

            ProductEventType.DISCOVERED,

            title,

            price,

            available,
        )

        if result.get(
            "redis_saved"
        ):

            events_created += 1

    else:

        transition = None

        if (
            state
            == "PREORDER_LIVE"
            and state
            != old_state
        ):

            transition = (
                ProductEventType.PREORDER_LIVE
            )

        elif (
            not old_available
            and available
        ):

            transition = (
                ProductEventType.RESTOCK
            )

        elif (
            old_available
            and not available
        ):

            transition = (
                ProductEventType.SOLD_OUT
            )

        if transition:

            result = await emit_product_event(

                product,

                transition,

                title,

                price,

                available,
            )

            if result.get(
                "redis_saved"
            ):

                events_created += 1

        if (
            old_price is not None
            and price is not None
            and old_price
            != price
        ):

            result = await emit_product_event(

                product,

                (
                    ProductEventType.PRICE_DROP
                    if price
                    < old_price
                    else
                    ProductEventType.PRICE_INCREASE
                ),

                title,

                price,

                available,
            )

            if result.get(
                "redis_saved"
            ):

                events_created += 1

    async with SessionLocal() as db:

        result = await db.execute(

            select(
                PokemonCenterProduct
            ).where(
                PokemonCenterProduct.id
                == product.id
            )
        )

        stored = (
            result.scalars().first()
        )

        if stored:

            stored.title = title

            stored.last_state = state

            stored.last_price = price

            stored.last_available = (
                available
            )

            stored.last_seen_at = (
                datetime.utcnow()
            )

            stored.last_scan_attempt_at = (
                datetime.utcnow()
            )

            stored.scan_status = (
                "SUCCESS"
            )

            stored.last_http_status = (
                200
            )

            stored.blocked_until = (
                None
            )

            stored.last_error = (
                None
            )

            await db.commit()

    return {

        "success":
            True,

        "blocked":
            False,

        "skipped_backoff":
            False,

        "events":
            events_created,
    }


# =========================================================
# SCAN ALL
# =========================================================

async def scan_pokemon_center_products():

    products = (
        await list_pokemon_products(
            active_only=True
        )
    )

    checked = 0
    successful = 0
    blocked = 0
    skipped = 0
    events = 0

    timeout = (
        aiohttp.ClientTimeout(
            total=20
        )
    )

    headers = {

        "Accept":
            "text/html,application/xhtml+xml",

        "Accept-Language":
            "en-US,en;q=0.9",

        "User-Agent":
            "PonDeX-Trackers/0.7.5",
    }

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:

        for product in products:

            try:

                result = (
                    await scan_registered_product(
                        session,
                        product,
                    )
                )

                if result[
                    "skipped_backoff"
                ]:

                    skipped += 1

                    continue

                checked += 1

                if result[
                    "success"
                ]:

                    successful += 1

                if result[
                    "blocked"
                ]:

                    blocked += 1

                events += (
                    result[
                        "events"
                    ]
                )

            except Exception as error:

                checked += 1

                await save_scan_error(
                    product.id,
                    (
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                )

            await asyncio.sleep(
                0.25
            )

    MONITOR_STATUS[
        "last_scan"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "known_products"
    ] = (
        len(
            products
        )
    )

    MONITOR_STATUS[
        "products_checked"
    ] = (
        checked
    )

    MONITOR_STATUS[
        "products_skipped_backoff"
    ] = (
        skipped
    )

    MONITOR_STATUS[
        "successful_products"
    ] = (
        successful
    )

    MONITOR_STATUS[
        "blocked_products"
    ] = (
        blocked
    )

    MONITOR_STATUS[
        "events_created"
    ] = (
        events
    )

    return {

        "known":
            len(
                products
            ),

        "checked":
            checked,

        "successful":
            successful,

        "blocked":
            blocked,

        "skipped":
            skipped,

        "events":
            events,
    }


# =========================================================
# BURST
# =========================================================

async def trigger_product_burst(
    region: str = "US",
):

    region = (
        region.upper()
    )

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return False

    await redis_client.set(
        (
            BURST_KEY_PREFIX
            + region
        ),
        "1",
        ex=(
            BURST_DURATION_SECONDS
        ),
    )

    return True


async def any_burst_active():

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return False

    count = 0

    for region in REGIONS:

        if await redis_client.exists(
            (
                BURST_KEY_PREFIX
                + region
            )
        ):

            count += 1

    MONITOR_STATUS[
        "burst_regions"
    ] = (
        count
    )

    return (
        count > 0
    )


# =========================================================
# BACKGROUND LOOP
# =========================================================

async def run_pokemon_center_product_monitor():

    MONITOR_STATUS[
        "running"
    ] = (
        True
    )

    print(
        (
            "Pokémon Center Product "
            "Intelligence v0.7.5 started."
        )
    )

    await asyncio.sleep(
        20
    )

    loop_counter = 0

    while True:

        try:

            burst = (
                await any_burst_active()
            )

            if (
                burst
                or (
                    loop_counter
                    % DISCOVERY_EVERY_LOOPS
                    == 0
                )
            ):

                await discover_pokemon_products()

            await scan_pokemon_center_products()

            loop_counter += 1

        except asyncio.CancelledError:

            MONITOR_STATUS[
                "running"
            ] = (
                False
            )

            raise

        except Exception as error:

            MONITOR_STATUS[
                "last_error"
            ] = (
                f"{type(error).__name__}: "
                f"{error}"
            )

        await asyncio.sleep(

            BURST_POLL_SECONDS

            if await any_burst_active()

            else NORMAL_POLL_SECONDS
        )


def get_pokemon_product_status():

    return dict(
        MONITOR_STATUS
    )