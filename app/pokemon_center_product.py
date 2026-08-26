import asyncio
import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin
from xml.etree import ElementTree

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
# LOTUS POKEMON CENTER PRODUCT INTELLIGENCE
# PonDeX Trackers
# Version 0.7.1
#
# Public page / sitemap monitoring only.
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


POLL_SECONDS = 90

BURST_POLL_SECONDS = 15

BURST_DURATION_SECONDS = 300


PRODUCT_CACHE_PREFIX = (
    "lotus:pokemon_center:product:"
)

KNOWN_URL_SET_PREFIX = (
    "lotus:pokemon_center:urls:"
)

BURST_KEY_PREFIX = (
    "lotus:pokemon_center:burst:"
)


MONITOR_STATUS = {

    "running":
        False,

    "last_scan":
        None,

    "regions_checked":
        0,

    "products_checked":
        0,

    "events_created":
        0,

    "burst_regions":
        0,

    "last_error":
        None,
}


# =========================================================
# TCG FILTERING
# =========================================================

TCG_KEYWORDS = (

    "trading card",

    "pokemon tcg",

    "pokémon tcg",

    "elite trainer box",

    "booster bundle",

    "booster pack",

    "booster box",

    "collection box",

    "collection",

    "battle deck",

    "trainer toolkit",

    "blister",

    "tin",

    "premium collection",

    "special collection",
)


def looks_like_tcg(
    text: str,
):

    value = (
        text
        .lower()
    )

    return any(
        keyword
        in value
        for keyword
        in TCG_KEYWORDS
    )


# =========================================================
# TEXT HELPERS
# =========================================================

def clean_html(
    html: str,
):

    text = re.sub(
        r"<script.*?</script>",
        " ",
        html,
        flags=(
            re.IGNORECASE
            |
            re.DOTALL
        ),
    )

    text = re.sub(
        r"<style.*?</style>",
        " ",
        text,
        flags=(
            re.IGNORECASE
            |
            re.DOTALL
        ),
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def extract_title(
    html: str,
):

    patterns = [

        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)',

        r"<title>(.*?)</title>",
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

            return clean_html(
                match.group(
                    1
                )
            )

    return "Unknown Pokémon Center Product"


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

            pass

    return None


# =========================================================
# PUBLIC PRODUCT STATE
# =========================================================

def classify_page_state(
    html: str,
):

    text = (
        clean_html(
            html
        ).lower()
    )

    preorder = (
        "preorder: add to cart"
        in text
        or
        "preorder: add to basket"
        in text
        or
        "pre-order: add to cart"
        in text
        or
        "pre-order: add to basket"
        in text
    )

    normal_available = any(
        phrase
        in text
        for phrase
        in (
            "add to cart",
            "add to basket",
        )
    )

    sold_out = any(
        phrase
        in text
        for phrase
        in (
            "sold out",
            "out of stock",
            "currently unavailable",
        )
    )

    coming_soon = any(
        phrase
        in text
        for phrase
        in (
            "coming soon",
            "available soon",
        )
    )

    if preorder:

        return {
            "state":
                "PREORDER_LIVE",

            "available":
                True,
        }

    if (
        normal_available
        and not sold_out
    ):

        return {
            "state":
                "STOCK_AVAILABLE",

            "available":
                True,
        }

    if coming_soon:

        return {
            "state":
                "COMING_SOON",

            "available":
                False,
        }

    if sold_out:

        return {
            "state":
                "SOLD_OUT",

            "available":
                False,
        }

    return {
        "state":
            "PAGE_LIVE",

        "available":
            False,
    }


# =========================================================
# REDIS PRODUCT SNAPSHOT
# =========================================================

def snapshot_key(
    region: str,
    url: str,
):

    digest = hashlib.sha256(
        url.encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        f"{PRODUCT_CACHE_PREFIX}"
        f"{region}:"
        f"{digest}"
    )


async def load_snapshot(
    region: str,
    url: str,
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return None

    key = snapshot_key(
        region,
        url,
    )

    return await redis_client.hgetall(
        key
    )


async def save_snapshot(
    region: str,
    url: str,
    *,
    title: str,
    state: str,
    available: bool,
    price,
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return

    key = snapshot_key(
        region,
        url,
    )

    await redis_client.hset(
        key,
        mapping={
            "title":
                title,

            "state":
                state,

            "available":
                (
                    "1"
                    if available
                    else "0"
                ),

            "price":
                (
                    ""
                    if price is None
                    else str(
                        price
                    )
                ),

            "last_seen":
                datetime.utcnow().isoformat(),
        },
    )


# =========================================================
# BURST MODE
# =========================================================

async def trigger_product_burst(
    region: str,
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return

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


async def is_burst_active(
    region: str,
):

    redis_client = (
        get_redis()
    )

    if redis_client is None:

        return False

    return bool(
        await redis_client.exists(
            (
                BURST_KEY_PREFIX
                + region
            )
        )
    )


# =========================================================
# SITEMAP DISCOVERY
# =========================================================

async def fetch_text(
    session,
    url: str,
):

    async with session.get(
        url,
        allow_redirects=True,
    ) as response:

        if response.status != 200:

            raise RuntimeError(
                (
                    f"HTTP "
                    f"{response.status}"
                    f" for {url}"
                )
            )

        return await response.text(
            errors="ignore"
        )


def extract_sitemap_urls(
    xml_text: str,
):

    urls = []

    try:

        root = (
            ElementTree.fromstring(
                xml_text
            )
        )

        for element in root.iter():

            if (
                element.tag.endswith(
                    "loc"
                )
                and element.text
            ):

                urls.append(
                    element.text.strip()
                )

    except ElementTree.ParseError:

        # Fallback for non-standard sitemap output.

        urls.extend(
            re.findall(
                r"<loc>\s*(.*?)\s*</loc>",
                xml_text,
                flags=(
                    re.IGNORECASE
                ),
            )
        )

    return urls


async def discover_candidate_product_urls(
    session,
    base_url: str,
):

    sitemap_candidates = [

        urljoin(
            base_url,
            "/sitemap.xml",
        ),

        urljoin(
            base_url,
            "/sitemap_index.xml",
        ),
    ]

    discovered = set()

    nested_sitemaps = []

    for sitemap_url in sitemap_candidates:

        try:

            text = await fetch_text(
                session,
                sitemap_url,
            )

        except Exception:

            continue

        urls = (
            extract_sitemap_urls(
                text
            )
        )

        for url in urls:

            if (
                ".xml"
                in url.lower()
            ):

                nested_sitemaps.append(
                    url
                )

            else:

                discovered.add(
                    url
                )

    # Limit nested sitemap expansion so one scan
    # cannot accidentally hammer the site.

    for nested in nested_sitemaps[
        :12
    ]:

        try:

            text = (
                await fetch_text(
                    session,
                    nested
                )
            )

        except Exception:

            continue

        for url in extract_sitemap_urls(
            text
        ):

            if ".xml" not in url.lower():

                discovered.add(
                    url
                )

    candidates = []

    for url in discovered:

        lower = (
            url.lower()
        )

        # Generic product-page pattern filtering.
        # We still confirm TCG relevance from the actual page.

        if any(
            marker
            in lower
            for marker
            in (
                "/product/",
                "/products/",
            )
        ):

            candidates.append(
                url
            )

    return candidates


# =========================================================
# EVENT CREATION
# =========================================================

async def emit_event(
    *,
    event_type,
    region,
    title,
    url,
    price,
    available,
):

    event = ProductEvent(

        event_type=event_type,

        game="Pokemon",

        product_name=title,

        store_name="Pokémon Center",

        product_url=url,

        price=price,

        currency="USD",

        in_stock=available,

        region=region,

        language="