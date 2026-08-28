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
# Public storefront discovery for Square / Weebly stores.
#
# SAFETY:
# - public pages only
# - no login
# - no CAPTCHA bypass
# - no queue bypass
# - no checkout automation
# - rate limited
# =========================================================


USER_AGENT = (
    "LotusTracker/1.0.4 "
    "(PonDeX Trackers; public retailer monitor)"
)


DEFAULT_TIMEOUT = 15

DEFAULT_REQUEST_DELAY = 1.0

MAX_DISCOVERY_PAGES = 15

MAX_PRODUCT_PAGES = 150


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

    re.compile(
        r"""\$\s*([0-9]+(?:\.[0-9]{1,2})?)""",
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
# PRODUCT CATEGORY CLASSIFICATION
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
# GAME CLASSIFICATION
#
# Keep this strict.
#
# Do NOT classify based on vague words such as:
# "card", "booster", "deck", etc.
# =========================================================

GAME_PATTERNS = {

    "One Piece": (
        "one piece card game",
        "one piece tcg",
    ),

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
        "riftbound",
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


UNSUPPORTED_GAME_TERMS = (
    "magic the gathering",
    "magic: the gathering",
    "mtg ",
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
# LANGUAGE / FAMILY
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
# HELPERS
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

    return value.strip()


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

    # Remove fragments.

    url = parsed._replace(
        fragment=""
    ).geturl()

    return url


def classify_game(
    title,
    body_text="",
):

    combined = (
        f"{title or ''} "
        f"{body_text or ''}"
    ).lower()

    for unsupported in UNSUPPORTED_GAME_TERMS:

        if unsupported in combined:

            return None

    # -----------------------------------------------------
    # ONE PIECE
    #
    # Strong phrases first.
    # -----------------------------------------------------

    if (
        "one piece card game"
        in combined

        or
        "one piece tcg"
        in combined

        or
        re.search(
            r"\bop(?:0?[1-9]|[1-9][0-9])\b",
            combined,
        )

        or
        re.search(
            r"\beb(?:0?[1-9]|[1-9][0-9])\b",
            combined,
        )

        or
        re.search(
            r"\bst(?:0?[1-9]|[1-9][0-9])\b",
            combined,
        )

        or
        re.search(
            r"\bp-\d{1,4}\b",
            combined,
        )
    ):

        return "One Piece"

    # -----------------------------------------------------
    # OTHER SUPPORTED GAMES
    # -----------------------------------------------------

    for (
        game,
        phrases,
    ) in GAME_PATTERNS.items():

        if game == "One Piece":
            continue

        for phrase in phrases:

            if phrase in combined:

                return game

    return None


def classify_product_category(
    title,
):

    text = (
        title
        or ""
    ).lower()

    for keyword in ACCESSORY_KEYWORDS:

        if keyword in text:

            return "ACCESSORY"

    for keyword in SINGLE_KEYWORDS:

        if keyword in text:

            return "SINGLE"

    for keyword in SEALED_KEYWORDS:

        if keyword in text:

            return "SEALED"

    return "UNKNOWN"


def classify_product_family(
    title,
    description="",
):

    combined = (
        f"{title or ''} "
        f"{description or ''}"
    ).lower()

    if any(
        term in combined
        for term in JP_TERMS
    ):

        return "JP"

    if any(
        term in combined
        for term in KR_TERMS
    ):

        return "KR"

    if any(
        term in combined
        for term in CN_TERMS
    ):

        return "CN"

    # Ambiguous import products must NOT automatically
    # become GLOBAL_STANDARD.

    if any(
        term in combined
        for term in IMPORT_TERMS
    ):

        return "UNKNOWN"

    return "GLOBAL_STANDARD"


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

    return mapping.get(
        family,
        "Unknown",
    )


def find_meta_value(
    html,
    pattern_a,
    pattern_b=None,
):

    match = pattern_a.search(
        html
    )

    if match:

        return clean_text(
            match.group(
                1
            )
        )

    if pattern_b is not None:

        match = pattern_b.search(
            html
        )

        if match:

            return clean_text(
                match.group(
                    1
                )
            )

    return None


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

            payload = json.loads(
                raw
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


def find_product_schema(
    html,
):

    objects = extract_json_ld(
        html
    )

    queue = list(
        objects
    )

    while queue:

        item = queue.pop(
            0
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
                for value in item_type
            }

        else:

            item_types = {
                str(
                    item_type
                    or ""
                ).lower()
            }

        if "product" in item_types:

            return item

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

        offers = offers[
            0
        ]

    if not isinstance(
        offers,
        dict,
    ):

        return None

    return offers


def parse_availability(
    offer,
    html,
):

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
            .lower()
        )

        if "instock" in availability:

            return True

        if "outofstock" in availability:

            return False

        if "soldout" in availability:

            return False

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

        return False

    strong_in_terms = (
        "add to cart",
        "add to bag",
    )

    if any(
        term in lowered
        for term in strong_in_terms
    ):

        return True

    return False


def parse_product_id_from_url(
    url,
):

    parsed = urlparse(
        url
    )

    match = re.search(
        r"/product/[^/]+/(\d+)",
        parsed.path,
        re.IGNORECASE,
    )

    if not match:

        return None

    return match.group(
        1
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

        timeout = aiohttp.ClientTimeout(
            total=DEFAULT_TIMEOUT
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

                return await response.text(

                    errors="ignore"
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
                    f"{type(error).__name__}: {error}"
                )
            )

            return None


    # =====================================================
    # DISCOVERY
    # =====================================================

    def _extract_product_urls(
        self,
        html,
        source_url,
    ):

        urls = set()

        if not html:

            return urls

        for match in PRODUCT_URL_PATTERN.finditer(
            html
        ):

            url = normalize_url(

                source_url,

                match.group(
                    1
                ),
            )

            if not url:

                continue

            parsed = urlparse(
                url
            )

            # Only stay on retailer domain.

            if (
                parsed.netloc
                .lower()
                .replace(
                    "www.",
                    "",
                )
                !=
                urlparse(
                    self.base_url
                )
                .netloc
                .lower()
                .replace(
                    "www.",
                    "",
                )
            ):

                continue

            if "/product/" not in parsed.path.lower():

                continue

            urls.add(
                url
            )

        return urls


    async def _discover_product_urls(
        self,
        session,
    ):

        discovered = set()

        # -------------------------------------------------
        # Public entry points.
        #
        # We do not assume that all of these exist.
        # Missing pages simply return no products.
        # -------------------------------------------------

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
                >= MAX_DISCOVERY_PAGES
            ):

                break

            url = urljoin(
                self.base_url,
                path,
            )

            html = await self._fetch_text(

                session,
                url,
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

        return list(
            discovered
        )[
            :
            self.max_product_pages
        ]


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

        connector = aiohttp.TCPConnector(

            limit=4,

            limit_per_host=2,
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

            for index, url in enumerate(
                product_urls
            ):

                html = await self._fetch_text(

                    session,
                    url,
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

            return raw_products


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

            title = clean_text(
                schema.get(
                    "name"
                )
            )

        if not title:

            title = find_meta_value(

                html,

                OG_TITLE_PATTERN,

                OG_TITLE_PATTERN_REVERSED,
            )

        if not title:

            match = TITLE_PATTERN.search(
                html
            )

            if match:

                title = clean_text(
                    match.group(
                        1
                    )
                )

        if not title:

            return None

        # Remove common site suffix.

        title = re.sub(
            r"\s*\|\s*Hypno Comics.*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()


        # =================================================
        # DESCRIPTION
        # =================================================

        description = ""

        if isinstance(
            schema,
            dict,
        ):

            description = clean_text(
                schema.get(
                    "description"
                )
            )

        if not description:

            description = (
                find_meta_value(
                    html,
                    META_DESCRIPTION_PATTERN,
                )
                or ""
            )


        # =================================================
        # STRICT GAME CLASSIFICATION
        # =================================================

        game = classify_game(

            title,

            description,
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

            price = normalize_price(
                offer.get(
                    "price"
                )
            )

        if price is None:

            for pattern in PRICE_PATTERNS:

                match = pattern.search(
                    html
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

                price = normalize_price(
                    raw_price
                )

                if price is not None:

                    break


        # =================================================
        # CURRENCY
        # =================================================

        currency = "USD"

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
                    ).upper()
                )

        else:

            match = CURRENCY_PATTERN.search(
                html
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

        available = parse_availability(

            offer,

            html,
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

                sku = clean_text(
                    schema_sku
                )

        if not sku:

            for pattern in SKU_PATTERNS:

                match = pattern.search(
                    html
                )

                if match:

                    sku = clean_text(
                        match.group(
                            1
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

                    image_url = str(
                        schema_image[
                            0
                        ]
                    )

            elif schema_image:

                image_url = str(
                    schema_image
                )

        if not image_url:

            image_url = find_meta_value(

                html,

                OG_IMAGE_PATTERN,

                OG_IMAGE_PATTERN_REVERSED,
            )


        # =================================================
        # PRODUCT CATEGORY / FAMILY
        # =================================================

        product_category = (
            classify_product_category(
                title
            )
        )

        product_family = (
            classify_product_family(
                title,
                description,
            )
        )

        language = (
            family_language(
                product_family
            )
        )


        # =================================================
        # EVENT STATE
        # =================================================

        product_state = (
            "STOCK_AVAILABLE"
            if available
            else "PAGE_LIVE"
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

            # We do NOT invent a Square offer ID.
            #
            # This remains None until one is publicly
            # and reliably exposed by the storefront.

            offer_id=None,

            # Not Shopify.

            variant_id=None,

            purchase_limit=None,

            # No Quick Cart yet.
            #
            # We need a documented / storefront-supported
            # mechanism before enabling cart links.

            cart_base_url=None,

            platform_data=(
                platform_data
            ),
        )