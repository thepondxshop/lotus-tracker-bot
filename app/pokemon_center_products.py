import asyncio
import html as html_lib
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
# Version 0.7.3
#
# Features:
#
# - Persistent product registry
# - Multi-source public discovery
# - Search/category discovery
# - Known product monitoring
# - Graceful 403 / 429 handling
# - Queue-triggered burst monitoring
# - Public preorder intelligence source
# =========================================================


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
# PUBLIC DISCOVERY PATHS
#
# These are discovery surfaces only.
#
# If Pokémon Center rejects one, Lotus simply moves on
# instead of treating that as a fatal monitor error.
# =========================================================

DISCOVERY_PATHS = [

    "/category/trading-card-game",

    "/search/pokemon-tcg",

    "/search/pokemon-trading-card-game",

    "/search/trading-card-game",

    "/search/tcg",

    "/search/elite-trainer-box",

    "/search/booster-bundle",

    "/search/booster-pack",

    "/search/premium-collection",

    "/search/tin",

    "/search/playmat",
]


# =========================================================
# OFFICIAL PUBLIC RELEASE INTELLIGENCE
# =========================================================

PREORDER_RELEASE_URL = (
    "https://support.pokemoncenter.com/"
    "hc/en-us/articles/4407702295572-"
    "Estimated-Preorder-Release-Dates"
)


# =========================================================
# TCG RELEVANCE
# =========================================================

TCG_KEYWORDS = [

    "pokemon tcg",

    "pokémon tcg",

    "trading card game",

    "elite trainer box",

    "booster bundle",

    "booster pack",

    "booster box",

    "premium collection",

    "special collection",

    "collection box",

    "battle deck",

    "trainer toolkit",

    "three-pack blister",

    "3-pack blister",

    "blister",

    "mini tin",

    "collector chest",

    "playmat",

    "deck box",

    "card sleeves",
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

    "last_preorder_scan":
        None,

    "known_products":
        0,

    "products_checked":
        0,

    "products_discovered":
        0,

    "discovery_pages_checked":
        0,

    "discovery_pages_blocked":
        0,

    "preorders_detected":
        0,

    "events_created":
        0,

    "blocked_products":
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

    # ---------------------------------------------
    # Handle relative product URLs.
    # ---------------------------------------------

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

    if (
        hostname != "pokemoncenter.com"
        and hostname != "www.pokemoncenter.com"
    ):

        raise ValueError(
            (
                "This does not appear to be "
                "a Pokémon Center product URL."
            )
        )

    path = (
        parsed.path
        or ""
    )

    if "/product/" not in path.lower():

        raise ValueError(
            (
                "This does not appear to be "
                "a Pokémon Center product URL."
            )
        )

    # ---------------------------------------------
    # Remove query strings / tracking parameters.
    # ---------------------------------------------

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
# HTML CLEANING
# =========================================================

def clean_html(
    html: str,
):

    value = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        html,
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


# =========================================================
# TCG FILTER
# =========================================================

def looks_like_tcg(
    value: str,
):

    lower = (
        value.lower()
    )

    return any(
        keyword in lower
        for keyword in TCG_KEYWORDS
    )


# =========================================================
# TITLE EXTRACTION
# =========================================================

def extract_title(
    html: str,
):

    patterns = [

        (
            r'<meta[^>]+property=["\']og:title["\']'
            r'[^>]+content=["\']([^"\']+)'
        ),

        (
            r'<meta[^>]+content=["\']([^"\']+)["\']'
            r'[^>]+property=["\']og:title["\']'
        ),

        r"<h1[^>]*>(.*?)</h1>",

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

        if not match:

            continue

        title = (
            clean_html(
                match.group(
                    1
                )
            )
        )

        if title:

            return title

    return (
        "Unknown Pokémon Center Product"
    )


# =========================================================
# PRICE EXTRACTION
# =========================================================

def extract_price(
    html: str,
):

    patterns = [

        r'"price"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',

        r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)',

        r'"currentPrice"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',

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

    text = (
        clean_html(
            html
        ).lower()
    )

    preorder = any(

        phrase in text

        for phrase in [

            "preorder: add to cart",

            "preorder: add to basket",

            "pre-order: add to cart",

            "pre-order: add to basket",

            "preorder now",

            "pre-order now",
        ]
    )

    sold_out = any(

        phrase in text

        for phrase in [

            "sold out",

            "out of stock",

            "currently unavailable",
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
# HTTP
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
# PRODUCT LINK EXTRACTION
# =========================================================

def extract_product_links(
    html: str,
):

    links = set()

    patterns = [

        (
            r'href=["\']'
            r'([^"\']*?/product/[^"\']+)'
            r'["\']'
        ),

        (
            r'["\']'
            r'(https://(?:www\.)?pokemoncenter\.com/'
            r'product/[^"\']+)'
            r'["\']'
        ),

        (
            r'["\']'
            r'(\/product\/[^"\']+)'
            r'["\']'
        ),
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        )

        for match in matches:

            # ---------------------------------------------
            # Remove escaped JSON slashes.
            # ---------------------------------------------

            match = (
                match
                .replace(
                    "\\/",
                    "/"
                )
                .replace(
                    "\\u002F",
                    "/"
                )
            )

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
            (
                "text/html,"
                "application/xhtml+xml,"
                "application/json"
            ),

        "Accept-Language":
            "en-US,en;q=0.9",

        "User-Agent":
            "PonDeX-Trackers/0.7.3",
    }

    discovered_total = 0

    pages_checked = 0

    pages_blocked = 0

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
                        path.lstrip(
                            "/"
                        )
                    )
                )

                try:

                    response = (
                        await fetch_page(
                            session,
                            discovery_url,
                        )
                    )

                    pages_checked += 1

                    status = (
                        response[
                            "status"
                        ]
                    )

                    # -------------------------------------
                    # Do NOT try to work around blocks.
                    # -------------------------------------

                    if status in (
                        401,
                        403,
                        429,
                    ):

                        pages_blocked += 1

                        continue

                    if status != 200:

                        continue

                    links = (
                        extract_product_links(
                            response[
                                "body"
                            ]
                        )
                    )

                    for link in links:

                        # ---------------------------------
                        # Try to use discovery-page text
                        # as a basic TCG relevance filter.
                        #
                        # Search/category pages can contain
                        # accessories too, which is okay
                        # because those are still useful
                        # Pokémon Center signals.
                        # ---------------------------------

                        try:

                            product, created = (
                                await add_pokemon_product(
                                    link,
                                    region,
                                )
                            )

                            if created:

                                discovered_total += 1

                                print(
                                    (
                                        "POKEMON PRODUCT DISCOVERED: "
                                        f"{region} | "
                                        f"{product.product_code} | "
                                        f"{product.url}"
                                    )
                                )

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
                            f"{discovery_url} | "
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
        "products_discovered"
    ] = (
        discovered_total
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

    return discovered_total


# =========================================================
# OFFICIAL PREORDER RELEASE INTELLIGENCE
# =========================================================

async def scan_preorder_release_intelligence():

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
            "PonDeX-Trackers/0.7.3",
    }

    preorder_count = 0

    try:

        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
        ) as session:

            response = await fetch_page(
                session,
                PREORDER_RELEASE_URL,
            )

            if response[
                "status"
            ] != 200:

                MONITOR_STATUS[
                    "last_preorder_scan"
                ] = (
                    datetime.utcnow().isoformat()
                )

                return 0

            text = (
                clean_html(
                    response[
                        "body"
                    ]
                )
            )

            # ---------------------------------------------
            # This is intelligence only.
            #
            # We don't automatically invent product URLs
            # from item names.
            # ---------------------------------------------

            lower = (
                text.lower()
            )

            for keyword in TCG_KEYWORDS:

                if keyword in lower:

                    preorder_count += 1

    except Exception as error:

        print(
            (
                "POKEMON PREORDER INTELLIGENCE ERROR: "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

    MONITOR_STATUS[
        "last_preorder_scan"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "preorders_detected"
    ] = (
        preorder_count
    )

    return preorder_count


# =========================================================
# EVENT CREATION
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
# SCAN ONE KNOWN PRODUCT
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
    # BLOCKED
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

    # =====================================================
    # PAGE MISSING
    # =====================================================

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
    # FIRST SUCCESSFUL SCAN
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

        initial_event = {

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

        if initial_event:

            result = (
                await emit_product_event(

                    product,

                    initial_event,

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
        # PRICE CHANGE
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
    # SAVE CURRENT STATE
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
# SCAN ALL KNOWN PRODUCTS
# =========================================================

async def scan_pokemon_center_products():

    products = (
        await list_pokemon_products(
            active_only=True
        )
    )

    known_count = len(
        products
    )

    MONITOR_STATUS[
        "known_products"
    ] = known_count

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
            "PonDeX-Trackers/0.7.3",
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
                ] = (
                    error_text
                )

            await asyncio.sleep(
                0.3
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

    MONITOR_STATUS[
        "blocked_products"
    ] = blocked

    return {

        "known":
            known_count,

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
            (
                "Unsupported Pokémon Center region."
            )
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
            "POKEMON PRODUCT BURST ENABLED: "
            f"{region}"
        )
    )

    return True


async def trigger_all_product_bursts():

    success_count = 0

    for region in REGIONS:

        try:

            success = (
                await trigger_product_burst(
                    region
                )
            )

            if success:

                success_count += 1

        except Exception as error:

            print(
                (
                    "POKEMON BURST ERROR: "
                    f"{region} | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

    return success_count


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
            "Intelligence v0.7.3 started."
        )
    )

    await asyncio.sleep(
        20
    )

    loop_counter = 0

    while True:

        try:

            burst_active = (
                await any_burst_active()
            )

            # =================================================
            # During burst mode we rediscover every loop.
            #
            # Under normal operation discovery is less
            # frequent.
            # =================================================

            if (
                burst_active
                or loop_counter
                % DISCOVERY_EVERY_LOOPS
                == 0
            ):

                await discover_pokemon_products()

            # =================================================
            # Official preorder/release intelligence.
            # =================================================

            if (
                loop_counter
                % DISCOVERY_EVERY_LOOPS
                == 0
            ):

                await scan_preorder_release_intelligence()

            # =================================================
            # Known product state monitoring.
            # =================================================

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
                    "POKEMON PRODUCT MONITOR ERROR: "
                    f"{MONITOR_STATUS['last_error']}"
                )
            )

        burst_active = (
            await any_burst_active()
        )

        await asyncio.sleep(

            BURST_POLL_SECONDS

            if burst_active

            else NORMAL_POLL_SECONDS
        )


# =========================================================
# STATUS
# =========================================================

def get_pokemon_product_status():

    return dict(
        MONITOR_STATUS
    )