import asyncio
import html as html_lib
import os
import re

from datetime import datetime

from urllib.parse import (
    urlparse,
)

import aiohttp

from sqlalchemy import (
    select,
)


from app.database import (
    SessionLocal,
)

from app.event_service import (
    process_product_event,
)

from app.events import (
    ProductEvent,
    ProductEventType,
)

from app.models import (
    PokemonCenterProduct,
)

from app.redis_client import (
    get_redis,
)


# =========================================================
# LOTUS POKEMON CENTER PRODUCT INTELLIGENCE
# PonDeX Trackers
# Version 0.7.4a
#
# Persistent Registry
# Serper Indexed Discovery
# Public Discovery Fallback
# Product State Monitoring
# Queue Burst Monitoring
# Diagnostics
# =========================================================


# =========================================================
# SERPER
# =========================================================

SERPER_API_KEY = os.getenv(
    "SERPER_API_KEY"
)


SERPER_ENDPOINT = (
    "https://google.serper.dev/search"
)


# =========================================================
# REGIONS
# =========================================================

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


# =========================================================
# POLLING
# =========================================================

NORMAL_POLL_SECONDS = 90

BURST_POLL_SECONDS = 15

BURST_DURATION_SECONDS = 300

DISCOVERY_EVERY_LOOPS = 10


BURST_KEY_PREFIX = (
    "lotus:pokemon_center:burst:"
)


# =========================================================
# INDEX QUERIES
# =========================================================

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


# =========================================================
# PUBLIC FALLBACK PATHS
# =========================================================

DISCOVERY_PATHS = [

    "/category/trading-card-game",

    "/search/pokemon-tcg",

    "/search/pokemon-trading-card-game",

    "/search/trading-card-game",

    "/search/elite-trainer-box",

    "/search/booster-bundle",

    "/search/booster-pack",

    "/search/premium-collection",

    "/search/special-collection",

    "/search/mini-tin",
]


# =========================================================
# STATUS
# =========================================================

MONITOR_STATUS = {

    "running":
        False,

    "last_scan":
        None,

    "last_discovery":
        None,

    "last_index_scan":
        None,

    "known_products":
        0,

    "products_checked":
        0,

    "events_created":
        0,

    "blocked_products":
        0,

    "products_discovered":
        0,

    "indexed_products_discovered":
        0,

    "index_enabled":
        bool(
            SERPER_API_KEY
        ),

    "index_queries_run":
        0,

    "index_results_seen":
        0,

    "index_results_accepted":
        0,

    "index_results_rejected":
        0,

    "index_http_errors":
        0,

    "last_index_error":
        None,

    "discovery_pages_checked":
        0,

    "discovery_pages_blocked":
        0,

    "burst_regions":
        0,

    "last_error":
        None,
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

    # Handle escaped slash URLs.

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
            + url.lstrip(
                "/"
            )
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
            (
                "Not a Pokémon Center URL. "
                f"Host={hostname or 'None'}"
            )
        )

    path = (
        parsed.path
        or ""
    )

    if "/product/" not in path.lower():

        raise ValueError(
            (
                "URL does not contain "
                "/product/."
            )
        )

    return (
        "https://www.pokemoncenter.com"
        + path.rstrip(
            "/"
        )
    )


# =========================================================
# PRODUCT CODE
# =========================================================

def extract_product_code(
    url: str,
):

    match = re.search(
        r"/product/([^/?#]+)",
        url,
        flags=(
            re.IGNORECASE
        ),
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
            (
                "Unsupported region. "
                "Use US, CA, UK, DE, AU or NZ."
            )
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

            existing.region = (
                region
            )

            existing.last_error = (
                None
            )

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

                product_code=(
                    code
                ),

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


# =========================================================
# LIST
# =========================================================

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

            query = (
                query.where(
                    PokemonCenterProduct.active
                    == True
                )
            )

        result = (
            await session.execute(
                query
            )
        )

        return list(
            result.scalars().all()
        )


# =========================================================
# REMOVE
# =========================================================

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

        product.active = (
            False
        )

        await session.commit()

        await session.refresh(
            product
        )

        return product


# =========================================================
# RESTORE
# =========================================================

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

        product.active = (
            True
        )

        product.last_error = (
            None
        )

        await session.commit()

        await session.refresh(
            product
        )

        return product


# =========================================================
# SERPER DISCOVERY
# =========================================================

async def indexed_product_discovery():

    MONITOR_STATUS[
        "index_enabled"
    ] = bool(
        SERPER_API_KEY
    )

    if not SERPER_API_KEY:

        message = (
            "SERPER_API_KEY missing"
        )

        MONITOR_STATUS[
            "last_index_error"
        ] = (
            message
        )

        print(
            (
                "SERPER DISCOVERY COMPLETE | "
                "Enabled=False | "
                f"Reason={message}"
            )
        )

        return {

            "enabled":
                False,

            "queries":
                0,

            "results":
                0,

            "accepted":
                0,

            "rejected":
                0,

            "new":
                0,
        }

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

    accepted = 0

    rejected = 0

    new_count = 0

    http_errors = 0

    last_error = None

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        for query in INDEX_QUERIES:

            # -------------------------------------------------
            # Keep the diagnostic request deliberately simple.
            #
            # If this works, we can add location/result-count
            # options later.
            # -------------------------------------------------

            payload = {

                "q":
                    query,
            }

            try:

                async with session.post(
                    SERPER_ENDPOINT,
                    json=payload,
                    headers=headers,
                ) as response:

                    body = (
                        await response.text(
                            errors="ignore"
                        )
                    )

                    if response.status != 200:

                        http_errors += 1

                        last_error = (
                            f"HTTP {response.status}: "
                            f"{body[:500]}"
                        )

                        print(
                            (
                                "SERPER ERROR | "
                                f"Query={query} | "
                                f"HTTP={response.status} | "
                                f"Body={body[:500]}"
                            )
                        )

                        continue

                    try:

                        data = (
                            await response.json()
                        )

                    except Exception as error:

                        last_error = (
                            f"JSON decode: "
                            f"{type(error).__name__}: "
                            f"{error}"
                        )

                        print(
                            (
                                "SERPER JSON ERROR | "
                                f"Query={query} | "
                                f"{last_error} | "
                                f"Body={body[:500]}"
                            )
                        )

                        continue

                    queries_run += 1

                    organic = (
                        data.get(
                            "organic",
                            []
                        )
                    )

                    print(
                        (
                            "SERPER QUERY RESULT | "
                            f"Query={query} | "
                            f"OrganicResults="
                            f"{len(organic)}"
                        )
                    )

                    for item in organic:

                        link = item.get(
                            "link"
                        )

                        title = item.get(
                            "title",
                            ""
                        )

                        if not link:

                            continue

                        results_seen += 1

                        print(
                            (
                                "SERPER RESULT | "
                                f"Title={title[:100]} | "
                                f"Link={link}"
                            )
                        )

                        try:

                            clean_url = (
                                normalize_product_url(
                                    link
                                )
                            )

                            accepted += 1

                            product, created = (
                                await add_pokemon_product(

                                    clean_url,

                                    "US",
                                )
                            )

                            # ---------------------------------
                            # Store indexed title immediately.
                            #
                            # This is useful even when Railway
                            # cannot fetch the direct product
                            # page due to Pokémon Center 403.
                            # ---------------------------------

                            if (
                                title
                                and (
                                    not product.title
                                    or product.title.startswith(
                                        "Unknown"
                                    )
                                )
                            ):

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

                                print(
                                    (
                                        "INDEXED PRODUCT ADDED | "
                                        f"Code="
                                        f"{product.product_code} | "
                                        f"URL="
                                        f"{product.url}"
                                    )
                                )

                            else:

                                print(
                                    (
                                        "INDEXED PRODUCT EXISTS | "
                                        f"Code="
                                        f"{product.product_code}"
                                    )
                                )

                        except ValueError as error:

                            rejected += 1

                            print(
                                (
                                    "SERPER RESULT REJECTED | "
                                    f"Link={link} | "
                                    f"Reason={error}"
                                )
                            )

                        except Exception as error:

                            last_error = (
                                f"{type(error).__name__}: "
                                f"{error}"
                            )

                            print(
                                (
                                    "INDEX SAVE ERROR | "
                                    f"{last_error}"
                                )
                            )

            except Exception as error:

                last_error = (
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                print(
                    (
                        "INDEX QUERY ERROR | "
                        f"Query={query} | "
                        f"{last_error}"
                    )
                )

            await asyncio.sleep(
                0.4
            )

    MONITOR_STATUS[
        "last_index_scan"
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

    MONITOR_STATUS[
        "index_results_accepted"
    ] = (
        accepted
    )

    MONITOR_STATUS[
        "index_results_rejected"
    ] = (
        rejected
    )

    MONITOR_STATUS[
        "index_http_errors"
    ] = (
        http_errors
    )

    MONITOR_STATUS[
        "last_index_error"
    ] = (
        last_error
    )

    print(
        (
            "SERPER DISCOVERY COMPLETE | "
            "Enabled=True | "
            f"Queries={queries_run} | "
            f"HTTPFailures={http_errors} | "
            f"Results={results_seen} | "
            f"Accepted={accepted} | "
            f"Rejected={rejected} | "
            f"New={new_count}"
        )
    )

    return {

        "enabled":
            True,

        "queries":
            queries_run,

        "results":
            results_seen,

        "accepted":
            accepted,

        "rejected":
            rejected,

        "new":
            new_count,
    }


# =========================================================
# PUBLIC DISCOVERY
# =========================================================

async def discover_pokemon_products():

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
            "PonDeX-Trackers/0.7.4a",
    }

    pages_checked = 0

    pages_blocked = 0

    public_new = 0

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:

        for (
            region,
            base_url,
        ) in REGIONS.items():

            for path in DISCOVERY_PATHS:

                url = (
                    base_url.rstrip(
                        "/"
                    )
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

                        links = set()

                        links.update(

                            re.findall(
                                (
                                    r'https://'
                                    r'(?:www\.)?'
                                    r'pokemoncenter\.com/'
                                    r'product/'
                                    r'[^"\'<>\s\\]+'
                                ),
                                body,
                                flags=(
                                    re.IGNORECASE
                                ),
                            )
                        )

                        relative_links = (
                            re.findall(
                                (
                                    r'href=["\']'
                                    r'(/product/'
                                    r'[^"\']+)'
                                    r'["\']'
                                ),
                                body,
                                flags=(
                                    re.IGNORECASE
                                ),
                            )
                        )

                        links.update(
                            relative_links
                        )

                        print(
                            (
                                "POKEMON PUBLIC PAGE | "
                                f"Region={region} | "
                                f"HTTP=200 | "
                                f"Links="
                                f"{len(links)}"
                            )
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

                                    public_new += 1

                                    print(
                                        (
                                            "PUBLIC PRODUCT ADDED | "
                                            f"Code="
                                            f"{product.product_code}"
                                        )
                                    )

                            except Exception:

                                continue

                except Exception as error:

                    print(
                        (
                            "PUBLIC DISCOVERY ERROR | "
                            f"Region={region} | "
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
    ] = (
        public_new
    )

    MONITOR_STATUS[
        "discovery_pages_checked"
    ] = (
        pages_checked
    )

    MONITOR_STATUS[
        "discovery_pages_blocked"
    ] = (
        pages_blocked
    )

    indexed_result = (
        await indexed_product_discovery()
    )

    total_new = (
        public_new
        + indexed_result[
            "new"
        ]
    )

    print(
        (
            "POKEMON DISCOVERY COMPLETE | "
            f"PublicNew={public_new} | "
            f"IndexedNew="
            f"{indexed_result['new']} | "
            f"TotalNew={total_new} | "
            f"PublicPages="
            f"{pages_checked} | "
            f"PublicBlocked="
            f"{pages_blocked}"
        )
    )

    return (
        total_new
    )


# =========================================================
# HTML HELPERS
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

    patterns = [

        (
            r'<meta[^>]+'
            r'property=["\']og:title["\']'
            r'[^>]+'
            r'content=["\']([^"\']+)'
        ),

        (
            r"<title[^>]*>"
            r"(.*?)"
            r"</title>"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            flags=(
                re.IGNORECASE
                |
                re.DOTALL
            ),
        )

        if match:

            title = clean_html(
                match.group(
                    1
                )
            )

            if title:

                return title

    return (
        "Unknown Pokémon Center Product"
    )


def extract_price(
    html: str,
):

    patterns = [

        (
            r'"price"\s*:\s*'
            r'"([0-9]+(?:\.[0-9]+)?)"'
        ),

        (
            r'"price"\s*:\s*'
            r'([0-9]+(?:\.[0-9]+)?)'
        ),

        (
            r'\$\s*'
            r'([0-9]+(?:\.[0-9]{2})?)'
        ),
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

    preorder = any(

        phrase in text

        for phrase in (

            "preorder: add to cart",

            "preorder: add to basket",

            "pre-order: add to cart",

            "pre-order: add to basket",
        )
    )

    sold_out = any(

        phrase in text

        for phrase in (

            "sold out",

            "out of stock",

            "currently unavailable",
        )
    )

    add_to_cart = (

        "add to cart"
        in text

        or

        "add to basket"
        in text
    )

    if preorder:

        return (
            "PREORDER_LIVE",
            True,
        )

    if (
        add_to_cart
        and not sold_out
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

    if sold_out:

        return (
            "SOLD_OUT",
            False,
        )

    return (
        "PAGE_LIVE",
        False,
    )


# =========================================================
# EVENTS
# =========================================================

async def emit_product_event(
    product,
    event_type,
    title,
    price,
    available,
):

    event = ProductEvent(

        event_type=(
            event_type
        ),

        game="Pokemon",

        product_name=(
            title
        ),

        store_name=(
            "Pokémon Center"
        ),

        product_url=(
            product.url
        ),

        price=(
            price
        ),

        currency="USD",

        in_stock=(
            available
        ),

        region=(
            product.region
        ),

        language="English",

        product_type=(
            "Pokémon TCG Product"
        ),
    )

    return await process_product_event(
        event
    )


# =========================================================
# SAVE PRODUCT ERROR
# =========================================================

async def save_product_error(
    product_id: int,
    error_text: str,
):

    if SessionLocal is None:

        return

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

        if product:

            product.last_error = (
                error_text[
                    :2000
                ]
            )

            await session.commit()


# =========================================================
# SCAN PRODUCT
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

                "success":
                    False,

                "blocked":
                    True,

                "events":
                    0,

                "error":
                    f"HTTP {response.status}",
            }

        if response.status != 200:

            return {

                "success":
                    False,

                "blocked":
                    False,

                "events":
                    0,

                "error":
                    f"HTTP {response.status}",
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

    events_created = (
        0
    )

    old_state = (
        product.last_state
    )

    old_available = bool(
        product.last_available
    )

    old_price = (
        product.last_price
    )

    # =====================================================
    # FIRST OBSERVATION
    # =====================================================

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

        if result.get(
            "redis_saved"
        ):

            events_created += 1

        initial_map = {

            "PAGE_LIVE":
                ProductEventType.PAGE_LIVE,

            "COMING_SOON":
                ProductEventType.COMING_SOON,

            "PREORDER_LIVE":
                ProductEventType.PREORDER_LIVE,

            "STOCK_AVAILABLE":
                ProductEventType.STOCK_AVAILABLE,

            "SOLD_OUT":
                ProductEventType.SOLD_OUT,
        }

        state_event = (
            initial_map.get(
                state
            )
        )

        if state_event:

            result = (
                await emit_product_event(

                    product,

                    state_event,

                    title,

                    price,

                    available,
                )
            )

            if result.get(
                "redis_saved"
            ):

                events_created += 1

    # =====================================================
    # TRANSITIONS
    # =====================================================

    else:

        if state != old_state:

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

            elif (
                state
                == "COMING_SOON"
            ):

                transition = (
                    ProductEventType.COMING_SOON
                )

            elif (
                state
                == "PAGE_LIVE"
            ):

                transition = (
                    ProductEventType.PAGE_LIVE
                )

            if transition:

                result = (
                    await emit_product_event(

                        product,

                        transition,

                        title,

                        price,

                        available,
                    )
                )

                if result.get(
                    "redis_saved"
                ):

                    events_created += 1

        # =================================================
        # PRICE
        # =================================================

        if (
            old_price is not None
            and price is not None
            and old_price
            != price
        ):

            price_event = (

                ProductEventType.PRICE_DROP

                if price
                < old_price

                else ProductEventType.PRICE_INCREASE
            )

            result = (
                await emit_product_event(

                    product,

                    price_event,

                    title,

                    price,

                    available,
                )
            )

            if result.get(
                "redis_saved"
            ):

                events_created += 1

    # =====================================================
    # SAVE STATE
    # =====================================================

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
                title
            )

            stored.last_state = (
                state
            )

            stored.last_price = (
                price
            )

            stored.last_available = (
                available
            )

            stored.last_seen_at = (
                datetime.utcnow()
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

        "events":
            events_created,

        "error":
            None,
    }


# =========================================================
# SCAN ALL REGISTERED PRODUCTS
# =========================================================

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
            (
                "text/html,"
                "application/xhtml+xml"
            ),

        "Accept-Language":
            "en-US,en;q=0.9",

        "User-Agent":
            "PonDeX-Trackers/0.7.4a",
    }

    checked = 0

    blocked = 0

    events = 0

    MONITOR_STATUS[
        "last_error"
    ] = None

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

                if not result[
                    "success"
                ]:

                    await save_product_error(

                        product.id,

                        result[
                            "error"
                        ],
                    )

            except Exception as error:

                checked += 1

                error_text = (
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                MONITOR_STATUS[
                    "last_error"
                ] = (
                    error_text
                )

                await save_product_error(
                    product.id,
                    error_text,
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
    ] = (
        checked
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

    print(
        (
            "POKEMON PRODUCT SCAN COMPLETE | "
            f"Known={len(products)} | "
            f"Checked={checked} | "
            f"Blocked={blocked} | "
            f"Events={events}"
        )
    )

    return {

        "known":
            len(
                products
            ),

        "checked":
            checked,

        "events":
            events,

        "blocked":
            blocked,
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

        ex=(
            BURST_DURATION_SECONDS
        ),
    )

    print(
        (
            "POKEMON PRODUCT BURST ENABLED | "
            f"Region={region}"
        )
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

        try:

            exists = (
                await redis_client.exists(
                    (
                        BURST_KEY_PREFIX
                        + region
                    )
                )
            )

            if exists:

                count += 1

        except Exception as error:

            print(
                (
                    "BURST REDIS ERROR | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

            return False

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
    ] = True

    print(
        (
            "Pokémon Center Product "
            "Intelligence v0.7.4a started."
        )
    )

    await asyncio.sleep(
        20
    )

    loop_counter = (
        0
    )

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
            ] = False

            print(
                (
                    "Pokémon Center Product "
                    "Monitor stopped."
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
                    "POKEMON PRODUCT MONITOR ERROR | "
                    f"{MONITOR_STATUS['last_error']}"
                )
            )

        burst = (
            await any_burst_active()
        )

        await asyncio.sleep(

            BURST_POLL_SECONDS

            if burst

            else NORMAL_POLL_SECONDS
        )


# =========================================================
# STATUS
# =========================================================

def get_pokemon_product_status():

    return dict(
        MONITOR_STATUS
    )