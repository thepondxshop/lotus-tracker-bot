import asyncio
import json
import re

from html import unescape

from urllib.parse import (
    urljoin,
    urlparse,
)

import aiohttp

from app.retailer_adapter import (
    RetailerAdapter,
    RetailerProduct,
    normalize_price,
)

from app.retailer_registry import (
    retailer_adapter,
)


# =========================================================
# LOTUS SQUARE / WEEBLY RETAILER ADAPTER
# PonDeX Trackers
# Version 1.0.4
#
# Universal Retailer Foundation
#
# SAFETY:
# - public storefront pages only
# - no login
# - no CAPTCHA bypass
# - no queue bypass
# - no checkout automation
# - conservative request rate
# - unknown availability never means sold out
# =========================================================


USER_AGENT = (
    "LotusTracker/1.0.4 "
    "(PonDeX Trackers; public retailer monitor)"
)


DEFAULT_TIMEOUT = 15

DEFAULT_REQUEST_DELAY = 1.0

MAX_DISCOVERY_PAGES = 15

MAX_PRODUCT_PAGES = 150


# =========================================================
# URL / HTML PATTERNS
# =========================================================

PRODUCT_URL_PATTERN = re.compile(
    r"""href=["']([^"']*/product/[^"']+)["']""",
    re.IGNORECASE,
)


TITLE_PATTERN = re.compile(
    r"<title[^>]*>(.*?)</title>",
    re.IGNORECASE | re.DOTALL,
)


OG_TITLE_PATTERN = re.compile(
    r"""<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']""",
    re.IGNORECASE,
)


OG_TITLE_PATTERN_REVERSED = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:title["']""",
    re.IGNORECASE,
)


OG_IMAGE_PATTERN = re.compile(
    r"""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']""",
    re.IGNORECASE,
)


OG_IMAGE_PATTERN_REVERSED = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']""",
    re.IGNORECASE,
)


META_DESCRIPTION_PATTERN = re.compile(
    r"""<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']""",
    re.IGNORECASE,
)


META_DESCRIPTION_PATTERN_REVERSED = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+name=["']description["']""",
    re.IGNORECASE,
)


JSON_LD_PATTERN = re.compile(
    r"""<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.IGNORECASE | re.DOTALL,
)


PRICE_PATTERNS = [

    re.compile(
        r"""itemprop=["']price["'][^>]+content=["']([0-9.,]+)["']""",
        re.IGNORECASE,
    ),

    re.compile(
        r"""content=["']([0-9.,]+)["'][^>]+itemprop=["']price["']""",
        re.IGNORECASE,
    ),

    re.compile(
        r"""["']price["']\s*:\s*["']?([0-9]+(?:\.[0-9]{1,2})?)""",
        re.IGNORECASE,
    ),
]


CURRENCY_PATTERN = re.compile(
    r"""["']priceCurrency["']\s*:\s*["']([A-Z]{3})["']""",
    re.IGNORECASE,
)


SKU_PATTERNS = [

    re.compile(
        r"""["']sku["']\s*:\s*["']([^"']+)["']""",
        re.IGNORECASE,
    ),

    re.compile(
        r"""itemprop=["']sku["'][^>]+content=["']([^"']+)["']""",
        re.IGNORECASE,
    ),
]


# =========================================================
# PRODUCT CATEGORY
# =========================================================

SEALED_KEYWORDS = (

    "booster box",
    "booster pack",
    "booster bundle",
    "display box",
    "elite trainer box",
    "etb",
    "starter deck",
    "structure deck",
    "collection box",
    "collection set",
    "blister",
    "tin",
    "deck box set",
    "premium collection",
    "special collection",
    "case",
)


SINGLE_KEYWORDS = (

    "single card",
    "single",
)


ACCESSORY_KEYWORDS = (

    "sleeves",
    "deck box",
    "binder",
    "playmat",
    "play mat",
    "card sleeves",
    "portfolio",
    "toploader",
    "top loader",
)


# =========================================================
# UNSUPPORTED PRODUCTS
# =========================================================

UNSUPPORTED_GAME_TERMS = (

    "magic the gathering",
    "magic: the gathering",
    "yu-gi-oh",
    "yugioh",
    "lorcana",
    "digimon",
    "weiss schwarz",
    "union arena",
    "flesh and blood",
    "star wars unlimited",
    "warhammer",
    "games workshop",
)


# =========================================================
# SUPPORTED GAME PHRASES
# =========================================================

GAME_PATTERNS = {

    "Pokemon": (

        "pokemon tcg",
        "pokémon tcg",
    ),

    "Gundam Card Game": (

        "gundam card game",
        "gundam tcg",
    ),

    "Dragon Ball Fusion World": (

        "dragon ball super card game fusion world",
        "dragon ball fusion world",
        "fusion world tcg",
    ),

    "Riftbound": (

        "riftbound tcg",
        "riftbound trading card game",
        "riftbound league of legends",
    ),

    "Palworld": (

        "palworld tcg",
        "palworld card game",
    ),

    "Naruto TCG": (

        "naruto tcg",
        "naruto card game",
    ),

    "Cyberpunk TCG": (

        "cyberpunk tcg",
        "cyberpunk trading card game",
    ),

    "Azuki TCG": (

        "azuki tcg",
        "azuki trading card game",
    ),

    "Hellbreak TCG": (

        "hellbreak tcg",
        "hellbreak trading card game",
    ),
}


# =========================================================
# PRODUCT FAMILY
# =========================================================

JP_TERMS = (

    "japanese",
    "japan version",
    "japan edition",
    "jp version",
    "jp edition",
)


KR_TERMS = (

    "korean",
    "korea version",
    "korea edition",
    "kr version",
    "kr edition",
)


CN_TERMS = (

    "simplified chinese",
    "chinese version",
    "chinese edition",
    "cn version",
    "cn edition",
)


IMPORT_TERMS = (

    "import",
    "asian version",
    "asia version",
)


# =========================================================
# TEXT
# =========================================================

def clean_text(
    value,
):

    if value is None:

        return ""

    value = unescape(
        str(
            value
        )
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

    return (
        value.strip()
    )


# =========================================================
# URL
# =========================================================

def normalize_url(
    base_url,
    href,
):

    if not href:

        return None

    href = unescape(
        href.strip()
    )

    if href.startswith(
        "#"
    ):

        return None

    if href.startswith(
        "mailto:"
    ):

        return None

    if href.startswith(
        "tel:"
    ):

        return None

    url = urljoin(
        base_url,
        href,
    )

    parsed = urlparse(
        url
    )

    if parsed.scheme not in {
        "http",
        "https",
    }:

        return None

    return (
        parsed
        ._replace(
            fragment=""
        )
        .geturl()
    )


# =========================================================
# STRICT GAME CLASSIFICATION
#
# IMPORTANT:
#
# We intentionally classify from the PRODUCT TITLE only.
#
# Arbitrary page descriptions/body HTML are NOT used for
# game classification.
#
# This prevents unrelated Hypno comics/products from being
# classified because a description mentions another TCG.
# =========================================================

def classify_game(
    title,
):

    text = clean_text(
        title
    ).lower()

    if not text:

        return None


    # =====================================================
    # UNSUPPORTED GAME REJECTION
    # =====================================================

    for unsupported in UNSUPPORTED_GAME_TERMS:

        if unsupported in text:

            return None


    # =====================================================
    # ONE PIECE
    # =====================================================

    if (
        "one piece card game"
        in text

        or
        "one piece tcg"
        in text
    ):

        return (
            "One Piece"
        )


    # OPxx
    #
    # Require a separator or boundary before the set code
    # and allow common forms:
    #
    # OP-13
    # OP13
    # OP 13

    if re.search(
        r"\bop[\s-]?(?:0[1-9]|[1-9][0-9])\b",
        text,
        re.IGNORECASE,
    ):

        return (
            "One Piece"
        )


    # EBxx

    if re.search(
        r"\beb[\s-]?(?:0[1-9]|[1-9][0-9])\b",
        text,
        re.IGNORECASE,
    ):

        return (
            "One Piece"
        )


    # STxx

    if re.search(
        r"\bst[\s-]?(?:0[1-9]|[1-9][0-9])\b",
        text,
        re.IGNORECASE,
    ):

        return (
            "One Piece"
        )


    # One Piece promo code P-xxx is too generic by itself.
    #
    # Require One Piece context if P-xxx is used.

    if (
        "one piece"
        in text

        and
        re.search(
            r"\bp[\s-]?\d{1,4}\b",
            text,
            re.IGNORECASE,
        )
    ):

        return (
            "One Piece"
        )


    # =====================================================
    # OTHER SUPPORTED GAMES
    # =====================================================

    for (
        game,
        phrases,
    ) in GAME_PATTERNS.items():

        for phrase in phrases:

            if phrase in text:

                return (
                    game
                )

    return None


# =========================================================
# PRODUCT CATEGORY
# =========================================================

def classify_product_category(
    title,
):

    text = clean_text(
        title
    ).lower()


    for keyword in ACCESSORY_KEYWORDS:

        if keyword in text:

            return (
                "ACCESSORY"
            )


    for keyword in SINGLE_KEYWORDS:

        if keyword in text:

            return (
                "SINGLE"
            )


    for keyword in SEALED_KEYWORDS:

        if keyword in text:

            return (
                "SEALED"
            )


    return (
        "UNKNOWN"
    )


# =========================================================
# PRODUCT FAMILY
#
# Currency is NEVER used to determine product family.
#
# For this first Square/Weebly implementation we classify
# from the product title only.
# =========================================================

def classify_product_family(
    title,
):

    text = clean_text(
        title
    ).lower()


    if any(
        term in text
        for term in JP_TERMS
    ):

        return (
            "JP"
        )


    if any(
        term in text
        for term in KR_TERMS
    ):

        return (
            "KR"
        )


    if any(
        term in text
        for term in CN_TERMS
    ):

        return (
            "CN"
        )


    if any(
        term in text
        for term in IMPORT_TERMS
    ):

        return (
            "UNKNOWN"
        )


    return (
        "GLOBAL_STANDARD"
    )


# =========================================================
# FAMILY LANGUAGE
# =========================================================

def family_language(
    family,
):

    mapping = {

        "GLOBAL_STANDARD":
            "English",

        "JP":
            "Japanese",

        "KR":
            "Korean",

        "CN":
            "Simplified Chinese",

        "UNKNOWN":
            "Unknown",
    }

    return (
        mapping.get(
            family,
            "Unknown",
        )
    )


# =========================================================
# META
# =========================================================

def find_meta_value(
    html,
    pattern_a,
    pattern_b=None,
):

    match = (
        pattern_a.search(
            html
        )
    )

    if match:

        return (
            clean_text(
                match.group(
                    1
                )
            )
        )

    if pattern_b is not None:

        match = (
            pattern_b.search(
                html
            )
        )

        if match:

            return (
                clean_text(
                    match.group(
                        1
                    )
                )
            )

    return None


# =========================================================
# JSON-LD
# =========================================================

def extract_json_ld(
    html,
):

    objects = []

    for match in JSON_LD_PATTERN.finditer(
        html
    ):

        raw = (
            match.group(
                1
            ).strip()
        )

        if not raw:

            continue

        try:

            payload = (
                json.loads(
                    raw
                )
            )

        except Exception:

            continue


        if isinstance(
            payload,
            list,
        ):

            objects.extend(
                payload
            )

        else:

            objects.append(
                payload
            )

    return objects


# =========================================================
# PRODUCT SCHEMA
# =========================================================

def find_product_schema(
    html,
):

    objects = (
        extract_json_ld(
            html
        )
    )

    queue = list(
        objects
    )

    while queue:

        item = (
            queue.pop(
                0
            )
        )

        if isinstance(
            item,
            list,
        ):

            queue.extend(
                item
            )

            continue


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

            item_types = {

                str(
                    value
                ).lower()

                for value
                in item_type
            }

        else:

            item_types = {

                str(
                    item_type
                    or ""
                ).lower()
            }


        if "product" in item_types:

            return (
                item
            )


        graph = (
            item.get(
                "@graph"
            )
        )

        if isinstance(
            graph,
            list,
        ):

            queue.extend(
                graph
            )

    return None


# =========================================================
# OFFER
# =========================================================

def parse_offer(
    schema,
):

    if not isinstance(
        schema,
        dict,
    ):

        return None


    offers = (
        schema.get(
            "offers"
        )
    )


    if isinstance(
        offers,
        list,
    ):

        if not offers:

            return None

        offers = (
            offers[
                0
            ]
        )


    if not isinstance(
        offers,
        dict,
    ):

        return None


    return (
        offers
    )


# =========================================================
# AVAILABILITY
#
# Returns:
#
# (
#     available,
#     availability_known,
#     availability_state,
# )
#
# Unknown is intentionally NOT treated as False.
# =========================================================

def parse_availability(
    offer,
    html,
):

    # =====================================================
    # STRUCTURED DATA FIRST
    # =====================================================

    if isinstance(
        offer,
        dict,
    ):

        availability = (
            str(
                offer.get(
                    "availability"
                )
                or ""
            )
            .strip()
            .lower()
        )


        if (
            "instock"
            in availability
        ):

            return (
                True,
                True,
                "IN_STOCK",
            )


        if (
            "outofstock"
            in availability

            or
            "soldout"
            in availability
        ):

            return (
                False,
                True,
                "OUT_OF_STOCK",
            )


    # =====================================================
    # STRONG PAGE SIGNALS
    # =====================================================

    lowered = (
        html.lower()
    )


    strong_out_terms = (

        "out of stock",
        "sold out",
        "currently unavailable",
    )


    if any(
        term in lowered
        for term in strong_out_terms
    ):

        return (
            False,
            True,
            "OUT_OF_STOCK",
        )


    strong_in_terms = (

        "add to cart",
        "add to bag",
    )


    if any(
        term in lowered
        for term in strong_in_terms
    ):

        return (
            True,
            True,
            "IN_STOCK",
        )


    # =====================================================
    # UNKNOWN
    # =====================================================

    return (
        False,
        False,
        "UNKNOWN",
    )


# =========================================================
# PRODUCT ID
# =========================================================

def parse_product_id_from_url(
    url,
):

    parsed = (
        urlparse(
            url
        )
    )

    match = (
        re.search(
            r"/product/[^/]+/(\d+)",
            parsed.path,
            re.IGNORECASE,
        )
    )

    if not match:

        return None


    return (
        match.group(
            1
        )
    )


# =========================================================
# ADAPTER
# =========================================================

@retailer_adapter(
    "square_weebly"
)
class SquareWeeblyAdapter(
    RetailerAdapter
):

    platform = (
        "square_weebly"
    )


    def __init__(
        self,
        *,
        domain,
        region="US",
        store_name=None,
        request_delay=DEFAULT_REQUEST_DELAY,
        max_product_pages=MAX_PRODUCT_PAGES,
    ):

        super().__init__(

            domain=domain,

            region=region,

            store_name=store_name,
        )


        domain = (
            self.domain
            .replace(
                "https://",
                "",
            )
            .replace(
                "http://",
                "",
            )
            .strip(
                "/"
            )
        )


        self.base_url = (
            f"https://{domain}"
        )


        self.request_delay = max(

            float(
                request_delay
            ),

            0.5,
        )


        self.max_product_pages = max(

            1,

            min(
                int(
                    max_product_pages
                ),
                500,
            ),
        )


    # =====================================================
    # HTTP
    # =====================================================

    async def _fetch_text(
        self,
        session,
        url,
    ):

        timeout = (
            aiohttp.ClientTimeout(
                total=DEFAULT_TIMEOUT
            )
        )


        try:

            async with session.get(

                url,

                timeout=timeout,

                allow_redirects=True,

            ) as response:


                if response.status == 429:

                    print(
                        (
                            "SQUARE/WEEBLY RATE LIMITED | "
                            f"Store={self.store_name} | "
                            f"URL={url}"
                        )
                    )

                    return None


                if response.status in {
                    401,
                    403,
                }:

                    print(
                        (
                            "SQUARE/WEEBLY ACCESS BLOCKED | "
                            f"Store={self.store_name} | "
                            f"HTTP={response.status} | "
                            f"URL={url}"
                        )
                    )

                    return None


                if response.status >= 400:

                    print(
                        (
                            "SQUARE/WEEBLY HTTP ERROR | "
                            f"Store={self.store_name} | "
                            f"HTTP={response.status} | "
                            f"URL={url}"
                        )
                    )

                    return None


                content_type = (
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                )


                if (
                    "text/html"
                    not in content_type

                    and
                    "application/xhtml"
                    not in content_type

                    and
                    "text/xml"
                    not in content_type

                    and
                    "application/xml"
                    not in content_type
                ):

                    return None


                return (
                    await response.text(
                        errors="ignore"
                    )
                )


        except (
            asyncio.TimeoutError,
            aiohttp.ClientError,
        ) as error:

            print(
                (
                    "SQUARE/WEEBLY REQUEST ERROR | "
                    f"Store={self.store_name} | "
                    f"URL={url} | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

            return None


    # =====================================================
    # EXTRACT PRODUCT URLS
    # =====================================================

    def _extract_product_urls(
        self,
        html,
        source_url,
    ):

        urls = set()


        if not html:

            return (
                urls
            )


        expected_host = (
            urlparse(
                self.base_url
            )
            .netloc
            .lower()
            .replace(
                "www.",
                "",
            )
        )


        for match in PRODUCT_URL_PATTERN.finditer(
            html
        ):

            url = (
                normalize_url(
                    source_url,
                    match.group(
                        1
                    ),
                )
            )


            if not url:

                continue


            parsed = (
                urlparse(
                    url
                )
            )


            actual_host = (
                parsed.netloc
                .lower()
                .replace(
                    "www.",
                    "",
                )
            )


            if actual_host != expected_host:

                continue


            if (
                "/product/"
                not in
                parsed.path.lower()
            ):

                continue


            urls.add(
                url
            )


        return (
            urls
        )


    # =====================================================
    # DISCOVERY
    # =====================================================

    async def _discover_product_urls(
        self,
        session,
    ):

        discovered = set()


        discovery_paths = (

            "/",

            "/store",

            "/shop",

            "/shop-all",

            "/s/shop",

            "/s/search",
        )


        pages_checked = 0


        for path in discovery_paths:

            if (
                pages_checked
                >=
                MAX_DISCOVERY_PAGES
            ):

                break


            url = (
                urljoin(
                    self.base_url,
                    path,
                )
            )


            html = (
                await self._fetch_text(
                    session,
                    url,
                )
            )


            pages_checked += 1


            if not html:

                continue


            urls = (
                self._extract_product_urls(
                    html,
                    url,
                )
            )


            discovered.update(
                urls
            )


            if (
                len(
                    discovered
                )
                >=
                self.max_product_pages
            ):

                break


            await asyncio.sleep(
                self.request_delay
            )


        return (
            sorted(
                discovered
            )[
                :
                self.max_product_pages
            ]
        )


    # =====================================================
    # FETCH PRODUCTS
    # =====================================================

    async def fetch_products(
        self,
    ):

        headers = {

            "User-Agent":
                USER_AGENT,

            "Accept":
                (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),

            "Accept-Language":
                "en-US,en;q=0.9",
        }


        connector = (
            aiohttp.TCPConnector(

                limit=4,

                limit_per_host=2,
            )
        )


        async with aiohttp.ClientSession(

            headers=headers,

            connector=connector,

        ) as session:


            product_urls = (
                await self._discover_product_urls(
                    session
                )
            )


            print(
                (
                    "SQUARE/WEEBLY DISCOVERY | "
                    f"Store={self.store_name} | "
                    f"Products={len(product_urls)}"
                )
            )


            raw_products = []


            for (
                index,
                url,
            ) in enumerate(
                product_urls
            ):


                html = (
                    await self._fetch_text(
                        session,
                        url,
                    )
                )


                if html:

                    raw_products.append(
                        {
                            "url":
                                url,

                            "html":
                                html,
                        }
                    )


                if (
                    index
                    <
                    len(
                        product_urls
                    ) - 1
                ):

                    await asyncio.sleep(
                        self.request_delay
                    )


            return (
                raw_products
            )


    # =====================================================
    # NORMALIZE PRODUCT
    # =====================================================

    def normalize_product(
        self,
        product,
    ):

        if not isinstance(
            product,
            dict,
        ):

            return None


        url = (
            product.get(
                "url"
            )
        )


        html = (
            product.get(
                "html"
            )
            or ""
        )


        if not url or not html:

            return None


        schema = (
            find_product_schema(
                html
            )
        )


        offer = (
            parse_offer(
                schema
            )
        )


        # =================================================
        # TITLE
        # =================================================

        title = None


        if isinstance(
            schema,
            dict,
        ):

            title = (
                clean_text(
                    schema.get(
                        "name"
                    )
                )
            )


        if not title:

            title = (
                find_meta_value(

                    html,

                    OG_TITLE_PATTERN,

                    OG_TITLE_PATTERN_REVERSED,
                )
            )


        if not title:

            match = (
                TITLE_PATTERN.search(
                    html
                )
            )

            if match:

                title = (
                    clean_text(
                        match.group(
                            1
                        )
                    )
                )


        if not title:

            return None


        # Remove common Hypno site suffix without making
        # Hypno-specific assumptions elsewhere.

        title = (
            re.sub(
                r"\s*\|\s*Hypno Comics.*$",
                "",
                title,
                flags=re.IGNORECASE,
            )
            .strip()
        )


        # =================================================
        # DESCRIPTION
        #
        # Retained only as metadata.
        #
        # NOT used for game classification.
        # =================================================

        description = ""


        if isinstance(
            schema,
            dict,
        ):

            description = (
                clean_text(
                    schema.get(
                        "description"
                    )
                )
            )


        if not description:

            description = (
                find_meta_value(

                    html,

                    META_DESCRIPTION_PATTERN,

                    META_DESCRIPTION_PATTERN_REVERSED,

                )
                or ""
            )


        # =================================================
        # STRICT GAME CLASSIFICATION
        #
        # TITLE ONLY.
        # =================================================

        game = (
            classify_game(
                title
            )
        )


        if not game:

            return None


        # =================================================
        # PRICE
        # =================================================

        price = None


        if isinstance(
            offer,
            dict,
        ):

            price = (
                normalize_price(
                    offer.get(
                        "price"
                    )
                )
            )


        if price is None:

            for pattern in PRICE_PATTERNS:

                match = (
                    pattern.search(
                        html
                    )
                )

                if not match:

                    continue


                raw_price = (
                    match.group(
                        1
                    )
                    .replace(
                        ",",
                        "",
                    )
                )


                price = (
                    normalize_price(
                        raw_price
                    )
                )


                if price is not None:

                    break


        # =================================================
        # CURRENCY
        # =================================================

        currency = (
            "USD"
        )


        if isinstance(
            offer,
            dict,
        ):

            offer_currency = (
                offer.get(
                    "priceCurrency"
                )
            )


            if offer_currency:

                currency = (
                    str(
                        offer_currency
                    )
                    .strip()
                    .upper()
                )


        if (
            not isinstance(
                offer,
                dict,
            )

            or
            not offer.get(
                "priceCurrency"
            )
        ):

            match = (
                CURRENCY_PATTERN.search(
                    html
                )
            )


            if match:

                currency = (
                    match.group(
                        1
                    ).upper()
                )


        # =================================================
        # AVAILABILITY
        # =================================================

        (
            available,
            availability_known,
            availability_state,
        ) = (
            parse_availability(
                offer,
                html,
            )
        )


        # =================================================
        # IDENTIFIERS
        # =================================================

        external_product_id = (
            parse_product_id_from_url(
                url
            )
        )


        sku = None


        if isinstance(
            schema,
            dict,
        ):

            schema_sku = (
                schema.get(
                    "sku"
                )
            )


            if schema_sku:

                sku = (
                    clean_text(
                        schema_sku
                    )
                )


        if not sku:

            for pattern in SKU_PATTERNS:

                match = (
                    pattern.search(
                        html
                    )
                )

                if match:

                    sku = (
                        clean_text(
                            match.group(
                                1
                            )
                        )
                    )

                    break


        # =================================================
        # IMAGE
        # =================================================

        image_url = None


        if isinstance(
            schema,
            dict,
        ):

            schema_image = (
                schema.get(
                    "image"
                )
            )


            if isinstance(
                schema_image,
                list,
            ):

                if schema_image:

                    image_url = (
                        str(
                            schema_image[
                                0
                            ]
                        )
                    )


            elif schema_image:

                image_url = (
                    str(
                        schema_image
                    )
                )


        if not image_url:

            image_url = (
                find_meta_value(

                    html,

                    OG_IMAGE_PATTERN,

                    OG_IMAGE_PATTERN_REVERSED,
                )
            )


        # =================================================
        # CATEGORY
        # =================================================

        product_category = (
            classify_product_category(
                title
            )
        )


        # =================================================
        # FAMILY
        #
        # TITLE ONLY.
        # Currency is irrelevant.
        # =================================================

        product_family = (
            classify_product_family(
                title
            )
        )


        language = (
            family_language(
                product_family
            )
        )


        # =================================================
        # PRODUCT STATE
        # =================================================

        if availability_state == "IN_STOCK":

            product_state = (
                "STOCK_AVAILABLE"
            )

        elif availability_state == "OUT_OF_STOCK":

            product_state = (
                "SOLD_OUT"
            )

        else:

            product_state = (
                "PAGE_LIVE"
            )


        # =================================================
        # PLATFORM DATA
        # =================================================

        platform_data = {

            "adapter":
                "square_weebly",

            "external_product_id":
                external_product_id,

            "language":
                language,

            "availability_known":
                availability_known,

            "availability_state":
                availability_state,
        }


        # =================================================
        # NORMALIZED RESULT
        # =================================================

        return RetailerProduct(

            external_id=(
                external_product_id
            ),

            title=(
                title
            ),

            game=(
                game
            ),

            url=(
                url
            ),

            price=(
                price
            ),

            currency=(
                currency
            ),

            # RetailerProduct currently uses a bool.
            #
            # Unknown therefore remains False here, but the
            # availability_known flag in platform_data tells
            # the monitor NOT to interpret it as sold out.

            available=(
                available
            ),

            product_type=(
                "TCG Product"
            ),

            product_category=(
                product_category
            ),

            product_family=(
                product_family
            ),

            product_state=(
                product_state
            ),

            image_url=(
                image_url
            ),

            vendor=(
                self.store_name
            ),

            tags=None,

            sku=(
                sku
            ),

            external_product_id=(
                external_product_id
            ),

            offer_id=None,

            variant_id=None,

            purchase_limit=None,

            cart_base_url=None,

            platform_data=(
                platform_data
            ),
        )