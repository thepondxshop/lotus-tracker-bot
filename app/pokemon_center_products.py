import asyncio
import html as html_lib
import json
import os
import re

from datetime import (
    datetime,
    timedelta,
)

from urllib.parse import urlparse

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
# Version 0.7.6
#
# Structured Product Parsing
# Images
# Indexed Discovery
# Scan Diagnostics
# Backoff
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

    "successful_products":
        0,

    "parse_errors":
        0,

    "blocked_products":
        0,

    "products_skipped_backoff":
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

    parsed = (
        urlparse(
            url
        )
    )

    if not parsed.scheme:

        url = (
            "https://www.pokemoncenter.com/"
            + url.lstrip(
                "/"
            )
        )

        parsed = (
            urlparse(
                url
            )
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
        + path.rstrip(
            "/"
        )
    )


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

                scan_status="NOT_SCANNED",

                block_count=0,
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

        result = (
            await session.execute(
                query
            )
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
# SERPER
# =========================================================

async def discover_pokemon_products():

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
    }

    new_count = 0

    queries = 0

    results_seen = 0

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

                    if response.status != 200:

                        continue

                    data = (
                        await response.json()
                    )

                    queries += 1

                    for result_item in data.get(
                        "organic",
                        []
                    ):

                        link = (
                            result_item.get(
                                "link"
                            )
                        )

                        indexed_title = (
                            result_item.get(
                                "title"
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

                            if indexed_title:

                                async with SessionLocal() as db:

                                    db_result = (
                                        await db.execute(

                                            select(
                                                PokemonCenterProduct
                                            ).where(
                                                PokemonCenterProduct.id
                                                == product.id
                                            )
                                        )
                                    )

                                    stored = (
                                        db_result.scalars().first()
                                    )

                                    if stored:

                                        if (
                                            not stored.title
                                            or
                                            stored.title.startswith(
                                                "Unknown"
                                            )
                                        ):

                                            stored.title = (
                                                indexed_title[
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
                        "POKEMON INDEX ERROR | "
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
        "indexed_products_discovered"
    ] = (
        new_count
    )

    MONITOR_STATUS[
        "index_queries_run"
    ] = (
        queries
    )

    MONITOR_STATUS[
        "index_results_seen"
    ] = (
        results_seen
    )

    return (
        new_count
    )


# =========================================================
# HTML CLEANING
# =========================================================

def clean_html(
    value: str,
):

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = (
        html_lib.unescape(
            value
        )
    )

    return (
        re.sub(
            r"\s+",
            " ",
            value,
        ).strip()
    )


# =========================================================
# JSON-LD
# =========================================================

def extract_json_ld(
    html: str,
):

    blocks = re.findall(

        (
            r'<script[^>]+'
            r'type=["\']application/ld\+json["\']'
            r'[^>]*>'
            r'(.*?)'
            r'</script>'
        ),

        html,

        flags=(
            re.IGNORECASE
            |
            re.DOTALL
        ),
    )

    objects = []

    for block in blocks:

        try:

            parsed = (
                json.loads(
                    block.strip()
                )
            )

        except Exception:

            continue

        if isinstance(
            parsed,
            list,
        ):

            objects.extend(
                parsed
            )

        elif isinstance(
            parsed,
            dict,
        ):

            graph = (
                parsed.get(
                    "@graph"
                )
            )

            if isinstance(
                graph,
                list,
            ):

                objects.extend(
                    graph
                )

            objects.append(
                parsed
            )

    return (
        objects
    )


def find_product_json_ld(
    html: str,
):

    for item in extract_json_ld(
        html
    ):

        if not isinstance(
            item,
            dict,
        ):

            continue

        item_type = (
            item.get(
                "@type"
            )
        )

        if isinstance(
            item_type,
            list,
        ):

            if "Product" in item_type:

                return item

        elif (
            str(
                item_type
            ).lower()
            == "product"
        ):

            return item

    return None


# =========================================================
# PRODUCT PARSER
# =========================================================

def parse_product_page(
    html: str,
):

    product_json = (
        find_product_json_ld(
            html
        )
    )


    # =====================================================
    # TITLE
    # =====================================================

    title = None

    if product_json:

        title = (
            product_json.get(
                "name"
            )
        )

    if not title:

        patterns = [

            (
                r'<meta[^>]+'
                r'property=["\']og:title["\']'
                r'[^>]+'
                r'content=["\']([^"\']+)'
            ),

            (
                r'<meta[^>]+'
                r'name=["\']twitter:title["\']'
                r'[^>]+'
                r'content=["\']([^"\']+)'
            ),

            (
                r"<h1[^>]*>"
                r"(.*?)"
                r"</h1>"
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

                candidate = (
                    clean_html(
                        match.group(
                            1
                        )
                    )
                )

                if candidate:

                    title = candidate

                    break


    # =====================================================
    # IMAGE
    # =====================================================

    image_url = None

    if product_json:

        image = (
            product_json.get(
                "image"
            )
        )

        if isinstance(
            image,
            list,
        ):

            if image:

                first = (
                    image[
                        0
                    ]
                )

                if isinstance(
                    first,
                    dict,
                ):

                    image_url = (
                        first.get(
                            "url"
                        )
                    )

                else:

                    image_url = (
                        str(
                            first
                        )
                    )

        elif isinstance(
            image,
            dict,
        ):

            image_url = (
                image.get(
                    "url"
                )
            )

        elif image:

            image_url = (
                str(
                    image
                )
            )

    if not image_url:

        image_match = re.search(

            (
                r'<meta[^>]+'
                r'property=["\']og:image["\']'
                r'[^>]+'
                r'content=["\']([^"\']+)'
            ),

            html,

            flags=(
                re.IGNORECASE
            ),
        )

        if image_match:

            image_url = (
                image_match.group(
                    1
                )
            )


    # =====================================================
    # OFFERS
    # =====================================================

    offers = None

    if product_json:

        offers = (
            product_json.get(
                "offers"
            )
        )

        if isinstance(
            offers,
            list,
        ):

            offers = (

                offers[
                    0
                ]

                if offers

                else None
            )


    # =====================================================
    # PRICE
    # =====================================================

    price = None

    if isinstance(
        offers,
        dict,
    ):

        raw_price = (
            offers.get(
                "price"
            )
        )

        try:

            if raw_price is not None:

                price = float(
                    raw_price
                )

        except (
            TypeError,
            ValueError,
        ):

            pass


    # =====================================================
    # AVAILABILITY
    # =====================================================

    availability = ""

    if isinstance(
        offers,
        dict,
    ):

        availability = (
            str(
                offers.get(
                    "availability",
                    ""
                )
            ).lower()
        )


    text = (
        clean_html(
            html
        ).lower()
    )


    if (
        "preorder"
        in availability
        or
        "preorder: add to cart"
        in text
        or
        "preorder: add to basket"
        in text
    ):

        state = (
            "PREORDER_LIVE"
        )

        available = (
            True
        )

    elif (
        "instock"
        in availability
        or
        (
            (
                "add to cart"
                in text
                or
                "add to basket"
                in text
            )
            and
            "out of stock"
            not in text
            and
            "sold out"
            not in text
        )
    ):

        state = (
            "STOCK_AVAILABLE"
        )

        available = (
            True
        )

    elif (
        "outofstock"
        in availability
        or
        "sold out"
        in text
        or
        "out of stock"
        in text
    ):

        state = (
            "SOLD_OUT"
        )

        available = (
            False
        )

    elif (
        "coming soon"
        in text
    ):

        state = (
            "COMING_SOON"
        )

        available = (
            False
        )

    else:

        state = (
            "PAGE_LIVE"
        )

        available = (
            False
        )


    # =====================================================
    # TRUE PARSE SUCCESS
    # =====================================================

    parsed_title = (

        bool(
            title
        )

        and

        not title.lower().startswith(
            "unknown"
        )
    )


    return {

        "title":
            title,

        "image_url":
            image_url,

        "price":
            price,

        "state":
            state,

        "available":
            available,

        "parsed_title":
            parsed_title,
    }


# =========================================================
# SCAN DIAGNOSTICS
# =========================================================

async def save_scan_status(
    product_id: int,
    *,
    status: str,
    http_status=None,
    error=None,
    blocked_until=None,
    increment_block=False,
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
            status
        )

        stored.last_http_status = (
            http_status
        )

        stored.last_scan_attempt_at = (
            datetime.utcnow()
        )

        stored.last_error = (
            error
        )

        stored.blocked_until = (
            blocked_until
        )

        if increment_block:

            stored.block_count = (
                (
                    stored.block_count
                    or 0
                )
                + 1
            )

        await db.commit()


# =========================================================
# EVENT BUILDER
# =========================================================

async def emit_product_event(
    product,
    event_type,
    title,
    price,
    available,
    image_url=None,
):

    return await process_product_event(

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

            source_type=(
                "pokemon_center"
            ),

            retailer_key=(
                "pokemon_center"
            ),

            image_url=(
                image_url
            ),
        )
    )


# =========================================================
# SCAN ONE PRODUCT
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
        and
        product.blocked_until
        > now
    ):

        return {

            "success":
                False,

            "blocked":
                False,

            "parse_error":
                False,

            "skipped":
                True,

            "events":
                0,
        }


    async with session.get(
        product.url,
        allow_redirects=True,
    ) as response:

        http_status = (
            response.status
        )

        if http_status in (
            401,
            403,
            429,
        ):

            await save_scan_status(

                product.id,

                status="BLOCKED",

                http_status=(
                    http_status
                ),

                error=(
                    f"HTTP {http_status}"
                ),

                blocked_until=(

                    datetime.utcnow()

                    + timedelta(
                        minutes=(
                            BLOCK_COOLDOWN_MINUTES
                        )
                    )
                ),

                increment_block=True,
            )

            return {

                "success":
                    False,

                "blocked":
                    True,

                "parse_error":
                    False,

                "skipped":
                    False,

                "events":
                    0,
            }


        if http_status != 200:

            await save_scan_status(

                product.id,

                status="ERROR",

                http_status=(
                    http_status
                ),

                error=(
                    f"HTTP {http_status}"
                ),
            )

            return {

                "success":
                    False,

                "blocked":
                    False,

                "parse_error":
                    False,

                "skipped":
                    False,

                "events":
                    0,
            }


        html = (
            await response.text(
                errors="ignore"
            )
        )


    parsed = (
        parse_product_page(
            html
        )
    )


    # =====================================================
    # PARSE ERROR
    #
    # HTTP 200 alone is no longer enough for SUCCESS.
    # =====================================================

    if not parsed[
        "parsed_title"
    ]:

        # Preserve indexed title if we already have one.

        await save_scan_status(

            product.id,

            status="PARSE_ERROR",

            http_status=200,

            error=(
                "HTTP 200 but product title "
                "could not be parsed."
            ),
        )

        return {

            "success":
                False,

            "blocked":
                False,

            "parse_error":
                True,

            "skipped":
                False,

            "events":
                0,
        }


    title = (
        parsed[
            "title"
        ]
    )

    image_url = (
        parsed[
            "image_url"
        ]
    )

    price = (
        parsed[
            "price"
        ]
    )

    state = (
        parsed[
            "state"
        ]
    )

    available = (
        parsed[
            "available"
        ]
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

    events_created = (
        0
    )


    # =====================================================
    # FIRST REAL OBSERVATION
    # =====================================================

    if old_state is None:

        result = await emit_product_event(

            product,

            ProductEventType.DISCOVERED,

            title,

            price,

            available,

            image_url,
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

        initial_event = (
            initial_map.get(
                state
            )
        )

        if initial_event:

            result = await emit_product_event(

                product,

                initial_event,

                title,

                price,

                available,

                image_url,
            )

            if result.get(
                "redis_saved"
            ):

                events_created += 1


    # =====================================================
    # TRANSITIONS
    # =====================================================

    else:

        transition = None

        if (
            state
            == "PREORDER_LIVE"
            and
            old_state
            != state
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

                image_url,
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
            and
            price is not None
            and
            old_price
            != price
        ):

            price_event = (

                ProductEventType.PRICE_DROP

                if (
                    price
                    < old_price
                )

                else

                ProductEventType.PRICE_INCREASE
            )

            result = await emit_product_event(

                product,

                price_event,

                title,

                price,

                available,

                image_url,
            )

            if result.get(
                "redis_saved"
            ):

                events_created += 1


    # =====================================================
    # SAVE PRODUCT
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

            stored.scan_status = (
                "SUCCESS"
            )

            stored.last_http_status = (
                200
            )

            stored.last_seen_at = (
                datetime.utcnow()
            )

            stored.last_scan_attempt_at = (
                datetime.utcnow()
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

        "parse_error":
            False,

        "skipped":
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

    parse_errors = 0

    skipped = 0

    events = 0


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
            "PonDeX-Trackers/0.7.6",
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
                    "skipped"
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

                if result[
                    "parse_error"
                ]:

                    parse_errors += 1

                events += (
                    result[
                        "events"
                    ]
                )

            except Exception as error:

                checked += 1

                print(
                    (
                        "POKEMON PRODUCT ERROR | "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )
                )

            await asyncio.sleep(
                0.25
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
        "successful_products"
    ] = (
        successful
    )

    MONITOR_STATUS[
        "parse_errors"
    ] = (
        parse_errors
    )

    MONITOR_STATUS[
        "blocked_products"
    ] = (
        blocked
    )

    MONITOR_STATUS[
        "products_skipped_backoff"
    ] = (
        skipped
    )

    MONITOR_STATUS[
        "events_created"
    ] = (
        events
    )

    MONITOR_STATUS[
        "last_scan"
    ] = (
        datetime.utcnow().isoformat()
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

        "parse_errors":
            parse_errors,

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

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return False

    region = (
        region.upper()
    )

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
# BACKGROUND
# =========================================================

async def run_pokemon_center_product_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

    print(
        (
            "Pokémon Center Product "
            "Intelligence v0.7.6 started."
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
                or
                (
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


def get_pokemon_product_status():

    return dict(
        MONITOR_STATUS
    )