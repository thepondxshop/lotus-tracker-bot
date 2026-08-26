import asyncio
import re

from datetime import datetime

from urllib.parse import (
    urljoin,
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
# Version 0.7.2
#
# Product Registry
# Public Product Discovery
# Persistent Product Monitoring
# Queue-Triggered Burst Monitoring
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


NORMAL_POLL_SECONDS = 90

BURST_POLL_SECONDS = 15

BURST_DURATION_SECONDS = 300


BURST_KEY_PREFIX = (
    "lotus:pokemon_center:burst:"
)


# =========================================================
# DISCOVERY PAGES
#
# These are public pages only.
#
# The monitor extracts normal /product/... links.
# =========================================================

DISCOVERY_PATHS = [

    "/category/trading-card-game",

    "/search/pokemon-trading-card-game",

    "/search/trading-card-game",

    "/search/tcg",
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

    "known_products":
        0,

    "products_checked":
        0,

    "products_discovered":
        0,

    "events_created":
        0,

    "burst_regions":
        0,

    "last_error":
        None,
}


# =========================================================
# PRODUCT URL NORMALIZATION
# =========================================================

def normalize_product_url(
    url: str,
):

    url = (
        url.strip()
    )

    parsed = urlparse(
        url
    )

    if not parsed.scheme:

        url = (
            "https://www.pokemoncenter.com"
            + (
                url
                if url.startswith("/")
                else "/" + url
            )
        )

        parsed = urlparse(
            url
        )

    if (
        "pokemoncenter.com"
        not in parsed.netloc.lower()
    ):

        raise ValueError(
            (
                "This does not appear to be "
                "a Pokémon Center URL."
            )
        )

    path = (
        parsed.path
    )

    if "/product/" not in path.lower():

        raise ValueError(
            (
                "This does not appear to be "
                "a Pokémon Center product URL."
            )
        )

    return (
        f"https://www.pokemoncenter.com"
        f"{path}"
    )


# =========================================================
# PRODUCT CODE
#
# Example:
#
# /product/BUNDLE1198/...
#
# becomes:
#
# BUNDLE1198
# =========================================================

def extract_product_code(
    url: str,
):

    match = re.search(
        r"/product/([^/]+)/",
        url,
        flags=(
            re.IGNORECASE
        ),
    )

    if not match:

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
# HTML TEXT CLEANING
# =========================================================

def clean_html(
    html: str,
):

    value = re.sub(
        r"<script.*?</script>",
        " ",
        html,
        flags=(
            re.IGNORECASE
            |
            re.DOTALL
        ),
    )

    value = re.sub(
        r"<style.*?</style>",
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

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


# =========================================================
# TITLE
# =========================================================

def extract_title(
    html: str,
):

    patterns = [

        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',

        r"<title[^>]*>(.*?)</title>",
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


# =========================================================
# PRICE
# =========================================================

def extract_price(
    html: str,
):

    patterns = [

        r'"price"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',

        r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)',

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

        except (
            TypeError,
            ValueError,
        ):

            continue

    return None


# =========================================================
# PRODUCT STATE
# =========================================================

def classify_product_state(
    html: str,
):

    text = clean_html(
        html
    ).lower()

    preorder = any(

        phrase in text

        for phrase in [

            "preorder: add to cart",

            "preorder: add to basket",

            "pre-order: add to cart",

            "pre-order: add to basket",

            "preorder now",
        ]
    )

    sold_out = any(

        phrase in text

        for phrase in [

            "sold out",

            "out of stock",

            "currently unavailable",

            "unavailable",
        ]
    )

    coming_soon = any(

        phrase in text

        for phrase in [

            "coming soon",

            "available soon",
        ]
    )

    add_to_cart = any(

        phrase in text

        for phrase in [

            "add to cart",

            "add to basket",
        ]
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

    if coming_soon:

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
# HTTP FETCH
# =========================================================

async def fetch_page(
    session,
    url,
):

    async with session.get(
        url,
        allow_redirects=True,
    ) as response:

        body = (
            await response.text(
                errors="ignore"
            )
        )

        return {
            "status":
                response.status,

            "url":
                str(
                    response.url
                ),

            "body":
                body,
        }


# =========================================================
# PRODUCT REGISTRY
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

    product_code = (
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

            existing.region = (
                region
            )

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

                product_code=product_code,

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
# LIST PRODUCTS
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
            ).order_by(
                PokemonCenterProduct.id.asc()
            )
        )

        if active_only:

            query = query.where(
                PokemonCenterProduct.active
                == True
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
# REMOVE PRODUCT
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


# =========================================================
# RESTORE PRODUCT
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
# DISCOVER PRODUCT LINKS
# =========================================================

def extract_product_links(
    html: str,
):

    links = set()

    patterns = [

        r'href=["\']([^"\']*?/product/[^"\']+)["\']',

        r'["\'](https://www\.pokemoncenter\.com/product/[^"\']+)["\']',
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=(
                re.IGNORECASE
            ),
        )

        for match in matches:

            try:

                clean_url = (
                    normalize_product_url(
                        match
                    )
                )

                links.add(
                    clean_url
                )

            except ValueError:

                continue

    return links


# =========================================================
# DISCOVERY
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

        "User-Agent":
            "PonDeX-Trackers/0.7.2",
    }

    discovered_total = 0

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:

        for (
            region,
            base_url,
        ) in REGIONS.items():

            for path in DISCOVERY_PATHS:

                discovery_url = (
                    urljoin(
                        base_url,
                        path
                    )
                )

                try:

                    response = (
                        await fetch_page(
                            session,
                            discovery_url,
                        )
                    )

                    # -------------------------------------------------
                    # Do not attempt to bypass a block.
                    # -------------------------------------------------

                    if response[
                        "status"
                    ] in (
                        401,
                        403,
                        429,
                    ):

                        continue

                    if response[
                        "status"
                    ] != 200:

                        continue

                    links = (
                        extract_product_links(
                            response[
                                "body"
                            ]
                        )
                    )

                    for link in links:

                        try:

                            _, created = (
                                await add_pokemon_product(
                                    link,
                                    region,
                                )
                            )

                            if created:

                                discovered_total += 1

                        except Exception as error:

                            print(
                                (
                                    "POKEMON DISCOVERY SAVE ERROR: "
                                    f"{type(error).__name__}: "
                                    f"{error}"
                                )
                            )

                except Exception as error:

                    print(
                        (
                            "POKEMON DISCOVERY ERROR: "
                            f"{region} | "
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
        discovered_total
    )

    return discovered_total


# =========================================================
# EVENT BUILDER
# =========================================================

async def emit_product_event(
    product,
    event_type,
    title,
    price,
    available,
):

    event = (
        ProductEvent(

            event_type=event_type,

            game="Pokemon",

            product_name=title,

            store_name=(
                "Pokémon Center"
            ),

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

    return await process_product_event(
        event
    )


# =========================================================
# SCAN ONE REGISTERED PRODUCT
# =========================================================

async def scan_registered_product(
    session,
    product,
):

    response = (
        await fetch_page(
            session,
            product.url,
        )
    )

    status = (
        response[
            "status"
        ]
    )

    # =====================================================
    # ACCESS / BLOCK HANDLING
    # =====================================================

    if status in (
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
                f"HTTP {status}",
        }

    if status == 404:

        return {
            "success":
                False,

            "blocked":
                False,

            "events":
                0,

            "error":
                "HTTP 404",
        }

    if status != 200:

        return {
            "success":
                False,

            "blocked":
                False,

            "events":
                0,

            "error":
                f"HTTP {status}",
        }

    html = (
        response[
            "body"
        ]
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

    # =====================================================
    # FIRST SUCCESSFUL OBSERVATION
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

        if result[
            "redis_saved"
        ]:

            events_created += 1

        first_state_event = {

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

        }.get(
            state
        )

        if first_state_event:

            result = (
                await emit_product_event(

                    product,

                    first_state_event,

                    title,

                    price,

                    available,
                )
            )

            if result[
                "redis_saved"
            ]:

                events_created += 1

    # =====================================================
    # EXISTING PRODUCT
    # =====================================================

    else:

        if state != old_state:

            transition_event = None

            if state == "PREORDER_LIVE":

                transition_event = (
                    ProductEventType.PREORDER_LIVE
                )

            elif (
                not old_available
                and available
            ):

                transition_event = (
                    ProductEventType.RESTOCK
                )

            elif (
                old_available
                and not available
            ):

                transition_event = (
                    ProductEventType.SOLD_OUT
                )

            elif state == "COMING_SOON":

                transition_event = (
                    ProductEventType.COMING_SOON
                )

            elif state == "PAGE_LIVE":

                transition_event = (
                    ProductEventType.PAGE_LIVE
                )

            if transition_event:

                result = (
                    await emit_product_event(

                        product,

                        transition_event,

                        title,

                        price,

                        available,
                    )
                )

                if result[
                    "redis_saved"
                ]:

                    events_created += 1

        # =================================================
        # PRICE
        # =================================================

        if (
            old_price is not None
            and price is not None
            and old_price != price
        ):

            price_event = (

                ProductEventType.PRICE_DROP

                if price < old_price

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

            if result[
                "redis_saved"
            ]:

                events_created += 1

    # =====================================================
    # SAVE NEW PRODUCT STATE
    # =====================================================

    if SessionLocal is not None:

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

                stored.last_error = None

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
# UPDATE PRODUCT ERROR
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
            result.scalar_one_or_none()
        )

        if product:

            product.last_error = (
                error_text[
                    :2000
                ]
            )

            await session.commit()


# =========================================================
# SCAN ALL KNOWN PRODUCTS
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
            "text/html,application/xhtml+xml",

        "User-Agent":
            "PonDeX-Trackers/0.7.2",
    }

    checked = 0

    events = 0

    blocked = 0

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

                await save_product_error(
                    product.id,
                    error_text,
                )

                MONITOR_STATUS[
                    "last_error"
                ] = error_text

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
        "events_created"
    ] = events

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

        exists = await redis_client.exists(
            (
                BURST_KEY_PREFIX
                + region
            )
        )

        if exists:

            count += 1

    MONITOR_STATUS[
        "burst_regions"
    ] = count

    return (
        count > 0
    )


# =========================================================
# BACKGROUND MONITOR
# =========================================================

async def run_pokemon_center_product_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

    print(
        (
            "Pokémon Center Product "
            "Registry Monitor started."
        )
    )

    await asyncio.sleep(
        20
    )

    discovery_counter = 0

    while True:

        try:

            # ---------------------------------------------
            # Discovery periodically feeds the registry.
            # ---------------------------------------------

            if (
                discovery_counter
                % 10
                == 0
            ):

                await discover_pokemon_products()

            discovery_counter += 1

            await scan_pokemon_center_products()

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

            print(
                (
                    "POKEMON PRODUCT MONITOR ERROR: "
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