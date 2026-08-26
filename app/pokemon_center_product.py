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

        language="English",

        product_type=(

            "Pokémon TCG Product"

        ),

    )

    return await process_product_event(

        event

    )

# =========================================================

# PRODUCT COMPARISON

# =========================================================

async def process_product_page(

    session,

    region: str,

    url: str,

):

    html = await fetch_text(

        session,

        url,

    )

    title = extract_title(

        html

    )

    text = clean_html(

        html

    )

    if not looks_like_tcg(

        (

            title

            + " "

            + text[

                :10000

            ]

        )

    ):

        return {

            "tracked":

                False,

            "events":

                0,

        }

    state_data = (

        classify_page_state(

            html

        )

    )

    current_state = (

        state_data[

            "state"

        ]

    )

    current_available = (

        state_data[

            "available"

        ]

    )

    current_price = (

        extract_price(

            html

        )

    )

    previous = (

        await load_snapshot(

            region,

            url,

        )

    )

    events = 0

    # =====================================================

    # FIRST OBSERVATION

    # =====================================================

    if not previous:

        result = await emit_event(

            event_type=(

                ProductEventType.DISCOVERED

            ),

            region=region,

            title=title,

            url=url,

            price=current_price,

            available=current_available,

        )

        if result[

            "redis_saved"

        ]:

            events += 1

        state_event = {

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

            current_state

        )

        if state_event:

            result = (

                await emit_event(

                    event_type=(

                        state_event

                    ),

                    region=region,

                    title=title,

                    url=url,

                    price=current_price,

                    available=current_available,

                )

            )

            if result[

                "redis_saved"

            ]:

                events += 1

    # =====================================================

    # EXISTING PRODUCT

    # =====================================================

    else:

        previous_state = (

            previous.get(

                "state",

                "",

            )

        )

        previous_available = (

            previous.get(

                "available"

            )

            == "1"

        )

        previous_price_raw = (

            previous.get(

                "price",

                "",

            )

        )

        try:

            previous_price = (

                float(

                    previous_price_raw

                )

                if previous_price_raw

                else None

            )

        except ValueError:

            previous_price = None

        # -------------------------------------------------

        # State transitions

        # -------------------------------------------------

        if (

            current_state

            != previous_state

        ):

            transition_event = None

            if (

                current_state

                == "PREORDER_LIVE"

            ):

                transition_event = (

                    ProductEventType.PREORDER_LIVE

                )

            elif (

                not previous_available

                and current_available

            ):

                transition_event = (

                    ProductEventType.RESTOCK

                )

            elif (

                previous_available

                and not current_available

            ):

                transition_event = (

                    ProductEventType.SOLD_OUT

                )

            elif (

                current_state

                == "COMING_SOON"

            ):

                transition_event = (

                    ProductEventType.COMING_SOON

                )

            elif (

                current_state

                == "PAGE_LIVE"

            ):

                transition_event = (

                    ProductEventType.PAGE_LIVE

                )

            if transition_event:

                result = (

                    await emit_event(

                        event_type=(

                            transition_event

                        ),

                        region=region,

                        title=title,

                        url=url,

                        price=current_price,

                        available=current_available,

                    )

                )

                if result[

                    "redis_saved"

                ]:

                    events += 1

        # -------------------------------------------------

        # Price changes

        # -------------------------------------------------

        if (

            previous_price is not None

            and current_price is not None

            and previous_price

            != current_price

        ):

            if (

                current_price

                < previous_price

            ):

                price_event = (

                    ProductEventType.PRICE_DROP

                )

            else:

                price_event = (

                    ProductEventType.PRICE_INCREASE

                )

            result = await emit_event(

                event_type=(

                    price_event

                ),

                region=region,

                title=title,

                url=url,

                price=current_price,

                available=current_available,

            )

            if result[

                "redis_saved"

            ]:

                events += 1

    await save_snapshot(

        region,

        url,

        title=title,

        state=current_state,

        available=current_available,

        price=current_price,

    )

    return {

        "tracked":

            True,

        "events":

            events,

    }

# =========================================================

# REGION SCAN

# =========================================================

async def scan_region_products(

    region: str,

    base_url: str,

):

    timeout = (

        aiohttp.ClientTimeout(

            total=25

        )

    )

    headers = {

        "Accept":

            "text/html,application/xhtml+xml,application/xml",

        "User-Agent":

            "PonDeX-Trackers/0.7.1",

    }

    checked = 0

    tracked = 0

    events = 0

    async with aiohttp.ClientSession(

        timeout=timeout,

        headers=headers,

    ) as session:

        candidates = (

            await discover_candidate_product_urls(

                session,

                base_url,

            )

        )

        # Keep first version conservative.

        for url in candidates[

            :150

        ]:

            try:

                result = (

                    await process_product_page(

                        session,

                        region,

                        url,

                    )

                )

                checked += 1

                if result[

                    "tracked"

                ]:

                    tracked += 1

                    events += (

                        result[

                            "events"

                        ]

                    )

            except Exception as error:

                print(

                    (

                        "POKEMON PRODUCT PAGE ERROR: "

                        f"{region} | "

                        f"{url} | "

                        f"{type(error).__name__}: "

                        f"{error}"

                    )

                )

            # Respectful delay between page requests.

            await asyncio.sleep(

                0.15

            )

    return {

        "region":

            region,

        "checked":

            checked,

        "tracked":

            tracked,

        "events":

            events,

    }

# =========================================================

# ALL REGIONS

# =========================================================

async def scan_pokemon_center_products():

    results = []

    total_checked = 0

    total_events = 0

    MONITOR_STATUS[

        "last_error"

    ] = None

    for (

        region,

        base_url,

    ) in REGIONS.items():

        try:

            result = (

                await scan_region_products(

                    region,

                    base_url,

                )

            )

            results.append(

                result

            )

            total_checked += (

                result[

                    "checked"

                ]

            )

            total_events += (

                result[

                    "events"

                ]

            )

        except Exception as error:

            error_text = (

                f"{region}: "

                f"{type(error).__name__}: "

                f"{error}"

            )

            MONITOR_STATUS[

                "last_error"

            ] = error_text

            print(

                (

                    "POKEMON PRODUCT REGION ERROR: "

                    f"{error_text}"

                )

            )

    burst_regions = 0

    for region in REGIONS:

        if await is_burst_active(

            region

        ):

            burst_regions += 1

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

        "products_checked"

    ] = total_checked

    MONITOR_STATUS[

        "events_created"

    ] = total_events

    MONITOR_STATUS[

        "burst_regions"

    ] = burst_regions

    return results

# =========================================================

# BACKGROUND PRODUCT MONITOR

# =========================================================

async def run_pokemon_center_product_monitor():

    MONITOR_STATUS[

        "running"

    ] = True

    print(

        "Pokémon Center Product Monitor started."

    )

    await asyncio.sleep(

        20

    )

    while True:

        try:

            await scan_pokemon_center_products()

        except asyncio.CancelledError:

            MONITOR_STATUS[

                "running"

            ] = False

            print(

                "Pokémon Center Product Monitor stopped."

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

        burst_active = False

        for region in REGIONS:

            if await is_burst_active(

                region

            ):

                burst_active = True

                break

        await asyncio.sleep(

            (

                BURST_POLL_SECONDS

                if burst_active

                else POLL_SECONDS

            )

        )

def get_pokemon_product_status():

    return dict(

        MONITOR_STATUS

    )