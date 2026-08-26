import asyncio
import html as html_lib
import os
import re

from datetime import datetime
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
# PonDeX Trackers
# Version 0.7.4
#
# Persistent registry
# Indexed discovery
# Public-page discovery fallback
# Product monitoring
# Queue-triggered burst mode
# Preorder intelligence
# =========================================================


SERPER_API_KEY = os.getenv(
    "SERPER_API_KEY"
)

SERPER_ENDPOINT = (
    "https://google.serper.dev/search"
)


REGIONS = {
    "US": "https://www.pokemoncenter.com/",
    "CA": "https://www.pokemoncenter.com/en-ca/",
    "UK": "https://www.pokemoncenter.com/en-gb/",
    "DE": "https://www.pokemoncenter.com/en-de/",
    "AU": "https://www.pokemoncenter.com/en-au/",
    "NZ": "https://www.pokemoncenter.com/en-nz/",
}


NORMAL_POLL_SECONDS = 90
BURST_POLL_SECONDS = 15
BURST_DURATION_SECONDS = 300
DISCOVERY_EVERY_LOOPS = 10

BURST_KEY_PREFIX = (
    "lotus:pokemon_center:burst:"
)


# =========================================================
# INDEX SEARCH QUERIES
# =========================================================

INDEX_QUERIES = [

    (
        "site:pokemoncenter.com/product "
        "\"Pokemon TCG\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Pokémon TCG\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Elite Trainer Box\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Booster Bundle\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Booster Pack\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Premium Collection\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Special Collection\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Collector Chest\""
    ),

    (
        "site:pokemoncenter.com/product "
        "\"Mini Tin\""
    ),
]


# =========================================================
# PUBLIC DISCOVERY FALLBACKS
# =========================================================

DISCOVERY_PATHS = [

    "/category/trading-card-game",

    "/search/pokemon-tcg",

    "/search/pokemon-trading-card-game",

    "/search/trading-card-game",

    "/search/elite-trainer-box",

    "/search/booster-bundle",

    "/search/premium-collection",
]


# =========================================================
# STATUS
# =========================================================

MONITOR_STATUS = {

    "running": False,

    "last_scan": None,

    "last_discovery": None,

    "last_index_scan": None,

    "known_products": 0,

    "products_checked": 0,

    "events_created": 0,

    "blocked_products": 0,

    "products_discovered": 0,

    "indexed_products_discovered": 0,

    "index_queries_run": 0,

    "index_results_seen": 0,

    "discovery_pages_checked": 0,

    "discovery_pages_blocked": 0,

    "burst_regions": 0,

    "last_error": None,
}


# =========================================================
# URL NORMALIZATION
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
            "Not a Pokémon Center product URL."
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
        match.group(1)
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

    region = region.upper()

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
            result.scalar_one_or_none()
        )

        if existing:

            existing.active = True

            existing.region = region

            existing.last_error = None

            await session.commit()

            await session.refresh(
                existing
            )

            return (
                existing,
                False,
            )

        product = (
            PokemonCenterProduct(

                region=region,

                url=clean_url,

                product_code=code,

                active=True,
            )
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
            result.scalar_one_or_none()
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
            result.scalar_one_or_none()
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
# INDEXED DISCOVERY
# =========================================================

async def indexed_product_discovery():

    if not SERPER_API_KEY:

        return {
            "enabled": False,
            "queries": 0,
            "results": 0,
            "new": 0,
        }

    timeout = (
        aiohttp.ClientTimeout(
            total=20
        )
    )

    headers = {

        "X-API-KEY":
            SERPER_API_KEY,

        "Content-Type":
            "application/json",
    }

    new_count = 0
    results_seen = 0
    queries_run = 0

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        for query in INDEX_QUERIES:

            payload = {
                "q": query,
                "num": 20,
            }

            try:

                async with session.post(
                    SERPER_ENDPOINT,
                    json=payload,
                    headers=headers,
                ) as response:

                    if response.status != 200:

                        print(
                            (
                                "SERPER ERROR: "
                                f"HTTP {response.status}"
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

                    for result in organic:

                        link = (
                            result.get(
                                "link"
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

                            if created:

                                new_count += 1

                                print(
                                    (
                                        "INDEXED POKEMON PRODUCT: "
                                        f"{product.product_code} | "
                                        f"{product.url}"
                                    )
                                )

                        except ValueError:

                            continue

                        except Exception as error:

                            print(
                                (
                                    "INDEX SAVE ERROR: "
                                    f"{type(error).__name__}: "
                                    f"{error}"
                                )
                            )

            except Exception as error:

                print(
                    (
                        "INDEX QUERY ERROR: "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )
                )

            await asyncio.sleep(
                0.25
            )

    MONITOR_STATUS[
        "last_index_scan"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "indexed_products_discovered"
    ] = new_count

    MONITOR_STATUS[
        "index_queries_run"
    ] = queries_run

    MONITOR_STATUS[
        "index_results_seen"
    ] = results_seen

    return {
        "enabled": True,
        "queries": queries_run,
        "results": results_seen,
        "new": new_count,
    }


# =========================================================
# PUBLIC PAGE DISCOVERY
# =========================================================

async def discover_pokemon_products():

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
            "PonDeX-Trackers/0.7.4",
    }

    pages_checked = 0
    pages_blocked = 0
    new_count = 0

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:

        for region, base_url in REGIONS.items():

            for path in DISCOVERY_PATHS:

                url = (
                    base_url.rstrip("/")
                    + path
                )

                try:

                    async with session.get(
                        url,
                        allow_redirects=True,
                    ) as response:

                        pages_checked += 1

                        if response.status in (
                            401,
                            403,
                            429,
                        ):

                            pages_blocked += 1

                            continue

                        if response.status != 200:

                            continue

                        body = (
                            await response.text(
                                errors="ignore"
                            )
                        )

                        links = re.findall(
                            (
                                r'https://www\.pokemoncenter\.com/'
                                r'product/[^"\'<>\s]+'
                            ),
                            body,
                            flags=re.IGNORECASE,
                        )

                        links += re.findall(
                            (
                                r'href=["\']'
                                r'(/product/[^"\']+)'
                                r'["\']'
                            ),
                            body,
                            flags=re.IGNORECASE,
                        )

                        for link in links:

                            try:

                                product, created = (
                                    await add_pokemon_product(
                                        link,
                                        region,
                                    )
                                )

                                if created:

                                    new_count += 1

                            except Exception:

                                continue

                except Exception as error:

                    print(
                        (
                            "PUBLIC DISCOVERY ERROR: "
                            f"{type(error).__name__}: "
                            f"{error}"
                        )
                    )

                await asyncio.sleep(
                    0.25
                )

    MONITOR_STATUS[
        "last_discovery"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "products_discovered"
    ] = new_count

    MONITOR_STATUS[
        "discovery_pages_checked"
    ] = pages_checked

    MONITOR_STATUS[
        "discovery_pages_blocked"
    ] = pages_blocked

    indexed = (
        await indexed_product_discovery()
    )

    return (
        new_count
        + indexed[
            "new"
        ]
    )


# =========================================================
# PRODUCT PAGE HELPERS
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

    return clean_html(
        match.group(
            1
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
            flags=re.IGNORECASE,
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
        or
        "available soon"
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

    event = ProductEvent(

        event_type=event_type,

        game="Pokemon",

        product_name=title,

        store_name="Pokémon Center",

        product_url=product.url,

        price=price,

        currency="USD",

        in_stock=available,

        region=product.region,

        language="English",

        product_type="Pokémon TCG Product",
    )

    return await process_product_event(
        event
    )


# =========================================================
# PRODUCT MONITORING
# =========================================================

async def scan_registered_product(
    session,
    product,
):

    async with session.get(
        product.url,
        allow_redirects=True,
    ) as response:

        if response.status in (
            401,
            403,
            429,
        ):

            return {
                "success": False,
                "blocked": True,
                "events": 0,
                "error": (
                    f"HTTP {response.status}"
                ),
            }

        if response.status != 200:

            return {
                "success": False,
                "blocked": False,
                "events": 0,
                "error": (
                    f"HTTP {response.status}"
                ),
            }

        html = (
            await response.text(
                errors="ignore"
            )
        )

    title = extract_title(
        html
    )

    price = extract_price(
        html
    )

    state, available = (
        classify_product_state(
            html
        )
    )

    events = 0

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

        result = (
            await emit_product_event(
                product,
                ProductEventType.DISCOVERED,
                title,
                price,
                available,
            )
        )

        if result[
            "redis_saved"
        ]:

            events += 1

    else:

        transition = None

        if (
            state
            == "PREORDER_LIVE"
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

        if (
            transition
            and state
            != old_state
        ):

            result = (
                await emit_product_event(
                    product,
                    transition,
                    title,
                    price,
                    available,
                )
            )

            if result[
                "redis_saved"
            ]:

                events += 1

        if (
            old_price is not None
            and price is not None
            and old_price
            != price
        ):

            event_type = (

                ProductEventType.PRICE_DROP

                if price
                < old_price

                else ProductEventType.PRICE_INCREASE
            )

            result = (
                await emit_product_event(
                    product,
                    event_type,
                    title,
                    price,
                    available,
                )
            )

            if result[
                "redis_saved"
            ]:

                events += 1

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
            result.scalar_one_or_none()
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

            stored.last_error = None

            await db.commit()

    return {
        "success": True,
        "blocked": False,
        "events": events,
        "error": None,
    }


async def scan_pokemon_center_products():

    products = (
        await list_pokemon_products(
            active_only=True
        )
    )

    MONITOR_STATUS[
        "known_products"
    ] = len(
        products
    )

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
            "PonDeX-Trackers/0.7.4",
    }

    checked = 0
    blocked = 0
    events = 0

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

                checked += 1

                events += (
                    result[
                        "events"
                    ]
                )

                if result[
                    "blocked"
                ]:

                    blocked += 1

            except Exception as error:

                MONITOR_STATUS[
                    "last_error"
                ] = (
                    f"{type(error).__name__}: "
                    f"{error}"
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
        "products_checked"
    ] = checked

    MONITOR_STATUS[
        "blocked_products"
    ] = blocked

    MONITOR_STATUS[
        "events_created"
    ] = events

    return {
        "known": len(products),
        "checked": checked,
        "events": events,
        "blocked": blocked,
    }


# =========================================================
# BURST MODE
# =========================================================

async def trigger_product_burst(
    region: str = "US",
):

    region = (
        region.upper()
    )

    if region not in REGIONS:

        raise ValueError(
            "Unsupported region."
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
        ex=BURST_DURATION_SECONDS,
    )

    return True


async def any_burst_active():

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        MONITOR_STATUS[
            "burst_regions"
        ] = 0

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
    ] = count

    return (
        count > 0
    )


# =========================================================
# BACKGROUND LOOP
# =========================================================

async def run_pokemon_center_product_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

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
                or loop_counter
                % DISCOVERY_EVERY_LOOPS
                == 0
            ):

                await discover_pokemon_products()

            await scan_pokemon_center_products()

            loop_counter += 1

        except asyncio.CancelledError:

            MONITOR_STATUS[
                "running"
            ] = False

            raise

        except Exception as error:

            MONITOR_STATUS[
                "last_error"
            ] = (
                f"{type(error).__name__}: "
                f"{error}"
            )

        await asyncio.sleep(
            (
                BURST_POLL_SECONDS
                if await any_burst_active()
                else NORMAL_POLL_SECONDS
            )
        )


def get_pokemon_product_status():

    return dict(
        MONITOR_STATUS
    )