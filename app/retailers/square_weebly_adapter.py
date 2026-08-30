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
# Step 6E - Hypno Commerce Intelligence
#
# SAFETY:
# - public storefront pages only
# - no login
# - no CAPTCHA bypass
# - no queue bypass
# - no checkout automation
# - conservative request rate
# - same-domain discovery only
# - unknown availability never means sold out
# =========================================================

USER_AGENT = (
    "LotusTracker/1.0.4 "
    "(PonDeX Trackers; public retailer monitor)"
)

DEFAULT_TIMEOUT = 15
DEFAULT_REQUEST_DELAY = 0.65
MAX_DISCOVERY_PAGES = 30
MAX_PRODUCT_PAGES = 200

# Discover broadly, but only fetch a bounded number of product pages.
# This prevents a large comic/game store from hiding TCG products beyond
# the first alphabetically sorted product URLs.
MAX_DISCOVERED_PRODUCT_URLS = 10000

# Search/catalog seeds are public storefront pages only.
TCG_DISCOVERY_PATHS = (
    "/",
    "/store",
    "/shop",
    "/shop-all",
    "/s/shop",
    "/s/search",
    "/s/search?q=tcg",
    "/s/search?q=trading+card",
    "/s/search?q=one+piece",
    "/s/search?q=pokemon",
    "/s/search?q=gundam",
    "/s/search?q=riftbound",
    "/s/search?q=dragon+ball+fusion+world",
    "/sitemap.xml",
    "/sitemap_index.xml",
)

# These terms are used only to PRIORITIZE which already-discovered public
# product URLs are fetched first. They do not determine the game. Final
# game classification remains strict and title-based in classify_game().
TCG_URL_PRIORITY_TERMS = (
    "one-piece",
    "onepiece",
    "pokemon",
    "pok%C3%A9mon",
    "gundam",
    "riftbound",
    "fusion-world",
    "dragon-ball",
    "palworld",
    "naruto",
    "cyberpunk",
    "azuki",
    "hellbreak",
    "tcg",
    "trading-card",
    "card-game",
    "booster",
    "starter-deck",
    "elite-trainer",
)

TCG_URL_NEGATIVE_TERMS = (
    "comic",
    "graphic-novel",
    "manga",
    "statue",
    "figure",
    "miniature",
    "warhammer",
    "magic-the-gathering",
    "yu-gi-oh",
    "yugioh",
    "lorcana",
)


# =========================================================
# URL / HTML PATTERNS
# =========================================================

HREF_PATTERN = re.compile(
    r'''href\s*=\s*["']([^"']+)["']''',
    re.IGNORECASE,
)

PRODUCT_PATH_PATTERN = re.compile(
    r'''(?:https?://[^"'<>\\\s]+)?/product/[^"'<>\\\s?#]+/\d+''',
    re.IGNORECASE,
)

ESCAPED_PRODUCT_PATH_PATTERN = re.compile(
    r'''\\/product\\/[^"'<>\\\s?#]+\\/\d+''',
    re.IGNORECASE,
)

XML_LOC_PATTERN = re.compile(
    r"<loc>\s*(.*?)\s*</loc>",
    re.IGNORECASE | re.DOTALL,
)

TITLE_PATTERN = re.compile(
    r"<title[^>]*>(.*?)</title>",
    re.IGNORECASE | re.DOTALL,
)

OG_TITLE_PATTERN = re.compile(
    r'''<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']''',
    re.IGNORECASE,
)

OG_TITLE_PATTERN_REVERSED = re.compile(
    r'''<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:title["']''',
    re.IGNORECASE,
)

OG_IMAGE_PATTERN = re.compile(
    r'''<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']''',
    re.IGNORECASE,
)

OG_IMAGE_PATTERN_REVERSED = re.compile(
    r'''<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']''',
    re.IGNORECASE,
)

META_DESCRIPTION_PATTERN = re.compile(
    r'''<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']''',
    re.IGNORECASE,
)

META_DESCRIPTION_PATTERN_REVERSED = re.compile(
    r'''<meta[^>]+content=["']([^"']+)["'][^>]+name=["']description["']''',
    re.IGNORECASE,
)

JSON_LD_PATTERN = re.compile(
    r'''<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>''',
    re.IGNORECASE | re.DOTALL,
)

PRICE_PATTERNS = [
    re.compile(
        r'''itemprop=["']price["'][^>]+content=["']([0-9.,]+)["']''',
        re.IGNORECASE,
    ),
    re.compile(
        r'''content=["']([0-9.,]+)["'][^>]+itemprop=["']price["']''',
        re.IGNORECASE,
    ),
    re.compile(
        r'''["']price["']\s*:\s*["']?([0-9]+(?:\.[0-9]{1,2})?)''',
        re.IGNORECASE,
    ),
]

CURRENCY_PATTERN = re.compile(
    r'''["']priceCurrency["']\s*:\s*["']([A-Z]{3})["']''',
    re.IGNORECASE,
)

SKU_PATTERNS = [
    re.compile(
        r'''["']sku["']\s*:\s*["']([^"']+)["']''',
        re.IGNORECASE,
    ),
    re.compile(
        r'''itemprop=["']sku["'][^>]+content=["']([^"']+)["']''',
        re.IGNORECASE,
    ),
]


# =========================================================
# PRODUCT CATEGORY
# =========================================================

SEALED_KEYWORDS = (
    "booster box",
    "booster display",
    "display box",
    "booster pack",
    "booster bundle",
    "sleeved booster",
    "elite trainer box",
    "etb",
    "starter deck",
    "structure deck",
    "battle deck",
    "v battle deck",
    "vmax battle deck",
    "ex battle deck",
    "deluxe battle deck",
    "league battle deck",
    "collection box",
    "collection set",
    "gift collection",
    "double pack",
    "double-pack",
    "blister",
    "tin",
    "deck box set",
    "premium collection",
    "special collection",
    "case",
)

SINGLE_KEYWORDS = (
    "single card",
    "tcg single",
    "card single",
    "singles",
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
    "storage box",
    "card holder",
    "card stand",
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
        "pok\u00e9mon tcg",
        "pokemon trading card",
        "pok\u00e9mon trading card",
        "pokemon card game",
        "pok\u00e9mon card game",
    ),
    "Gundam": (
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
        "riftbound",
    ),
    "Palworld": (
        "palworld tcg",
        "palworld card game",
    ),
    "Naruto": (
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


def clean_text(value):
    if value is None:
        return ""

    value = unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_url(base_url, href):
    if not href:
        return None

    href = unescape(str(href).strip())
    href = href.replace(r"\/", "/").replace("&amp;", "&")

    if href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None

    url = urljoin(base_url, href)
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return None

    return parsed._replace(fragment="").geturl()


def normalized_host(value):
    parsed = urlparse(value)
    host = (parsed.netloc or parsed.path or "").lower()

    if host.startswith("www."):
        host = host[4:]

    return host.split(":", 1)[0]


def is_same_domain(left, right):
    return normalized_host(left) == normalized_host(right)


def canonicalize_product_url(url):
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def is_product_url(url):
    parsed = urlparse(url)
    return (
        re.search(
            r"/product/[^/]+/\d+/?$",
            parsed.path,
            re.IGNORECASE,
        )
        is not None
    )


def is_discovery_candidate(url):
    parsed = urlparse(url)
    path = (parsed.path or "/").lower()

    if is_product_url(url):
        return False

    if path == "/":
        return True

    keywords = (
        "/shop",
        "/store",
        "/search",
        "/category",
        "/categories",
        "/collection",
        "/collections",
        "/s/",
    )

    return any(keyword in path for keyword in keywords)


def classify_game(title):
    text = clean_text(title).lower()

    if not text:
        return None

    for unsupported in UNSUPPORTED_GAME_TERMS:
        if unsupported in text:
            return None

    if (
        "one piece card game" in text
        or "one piece tcg" in text
    ):
        return "One Piece"

    if re.search(r"\bop[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if re.search(r"\beb[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if re.search(r"\bprb[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if re.search(r"\bst[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if (
        "one piece" in text
        and re.search(r"\bp[\s-]?\d{1,4}\b", text)
    ):
        return "One Piece"

    for game, phrases in GAME_PATTERNS.items():
        for phrase in phrases:
            if phrase in text:
                return game

    return None


ONE_PIECE_CARD_NUMBER_PATTERN = re.compile(
    r"\b(?:OP|EB|PRB|ST|EX)\d{1,2}-\d{2,4}\b",
    re.IGNORECASE,
)

ONE_PIECE_PROMO_CARD_PATTERN = re.compile(
    r"\bP-\d{1,4}\b",
    re.IGNORECASE,
)


def has_strong_single_card_evidence(title):
    """
    Strong evidence for an individual card.

    Important distinction:
    - ST-30 / OP-13 can identify a sealed set/deck.
    - ST30-004 / OP13-001 identify an individual card number.

    We intentionally do not classify a product as SINGLE from words such
    as "foil" or "full art" alone because sealed collections may contain
    foil/promotional cards.
    """

    text = clean_text(title)

    if ONE_PIECE_CARD_NUMBER_PATTERN.search(text):
        return True

    lowered = text.lower()

    if (
        "one piece" in lowered
        and ONE_PIECE_PROMO_CARD_PATTERN.search(text)
    ):
        return True

    explicit_single_terms = (
        "single card",
        "tcg single",
        "card single",
        "singles",
        "individual card",
    )

    return any(
        term in lowered
        for term in explicit_single_terms
    )


def classify_product_category(title):
    text = clean_text(title).lower()

    # Strong individual-card evidence must beat contextual sealed wording.
    # Example:
    # "Emporio.Ivankov (Full Art) (ST30-004) - Starter Deck EX..."
    # is a SINGLE even though the source set name contains "Starter Deck".
    if has_strong_single_card_evidence(title):
        return "SINGLE"

    # Sealed still beats ACCESSORY for true products such as "deck box set".
    for keyword in SEALED_KEYWORDS:
        if keyword in text:
            return "SEALED"

    for keyword in ACCESSORY_KEYWORDS:
        if keyword in text:
            return "ACCESSORY"

    for keyword in SINGLE_KEYWORDS:
        if keyword in text:
            return "SINGLE"

    return "UNKNOWN"


def infer_product_type(title):
    text = clean_text(title).lower()

    if has_strong_single_card_evidence(title):
        return "Single Card"

    mappings = (
        (("elite trainer box", " etb"), "Elite Trainer Box"),
        (("booster box", "booster display", "display box"), "Booster Box"),
        (("booster bundle",), "Booster Bundle"),
        (("booster pack", "sleeved booster"), "Booster Pack"),
        (("double pack", "double-pack"), "Double Pack"),
        (("league battle deck",), "League Battle Deck"),
        (("vmax battle deck",), "VMAX Battle Deck"),
        (("v battle deck",), "V Battle Deck"),
        (("ex battle deck",), "EX Battle Deck"),
        (("deluxe battle deck",), "Deluxe Battle Deck"),
        (("battle deck",), "Battle Deck"),
        (("starter deck",), "Starter Deck"),
        (("structure deck",), "Structure Deck"),
        (("premium collection",), "Premium Collection"),
        (("collection box", "collection set"), "Collection"),
        (("case",), "Case"),
        (("tin",), "Tin"),
        (("playmat", "play mat"), "Playmat"),
        (("sleeves",), "Sleeves"),
        (("binder", "portfolio"), "Binder"),
        (("deck box",), "Deck Box"),
    )

    for keywords, label in mappings:
        for keyword in keywords:
            if keyword in text:
                return label

    return "TCG Product"


def classify_product_family(title):
    text = clean_text(title).lower()

    if any(term in text for term in JP_TERMS):
        return "JP"

    if any(term in text for term in KR_TERMS):
        return "KR"

    if any(term in text for term in CN_TERMS):
        return "CN"

    if any(term in text for term in IMPORT_TERMS):
        return "UNKNOWN"

    return "GLOBAL_STANDARD"


def family_language(family):
    mapping = {
        "GLOBAL_STANDARD": "English",
        "JP": "Japanese",
        "KR": "Korean",
        "CN": "Simplified Chinese",
        "UNKNOWN": "Unknown",
    }
    return mapping.get(family, "Unknown")


def find_meta_value(html, pattern_a, pattern_b=None):
    match = pattern_a.search(html)

    if match:
        return clean_text(match.group(1))

    if pattern_b is not None:
        match = pattern_b.search(html)
        if match:
            return clean_text(match.group(1))

    return None


def extract_json_ld(html):
    objects = []

    for match in JSON_LD_PATTERN.finditer(html):
        raw = match.group(1).strip()

        if not raw:
            continue

        try:
            payload = json.loads(raw)
        except Exception:
            continue

        if isinstance(payload, list):
            objects.extend(payload)
        else:
            objects.append(payload)

    return objects


def find_product_schema(html):
    queue = list(extract_json_ld(html))

    while queue:
        item = queue.pop(0)

        if isinstance(item, list):
            queue.extend(item)
            continue

        if not isinstance(item, dict):
            continue

        item_type = item.get("@type")

        if isinstance(item_type, list):
            item_types = {str(value).lower() for value in item_type}
        else:
            item_types = {str(item_type or "").lower()}

        if "product" in item_types:
            return item

        graph = item.get("@graph")
        if isinstance(graph, list):
            queue.extend(graph)

    return None


def parse_offer(schema):
    if not isinstance(schema, dict):
        return None

    offers = schema.get("offers")

    if isinstance(offers, list):
        if not offers:
            return None
        offers = offers[0]

    if not isinstance(offers, dict):
        return None

    return offers


SQUARE_PRICE_MINOR_PATTERN = re.compile(
    r'"amount"\s*:\s*([0-9]+)\s*,\s*"currency"\s*:\s*"([A-Z]{3})"',
    re.IGNORECASE,
)

SQUARE_PRICE_DECIMAL_PATTERNS = (
    re.compile(r'data-price=["\']([0-9]+(?:\.[0-9]{1,2})?)["\']', re.IGNORECASE),
    re.compile(r'\$\s*([0-9]+(?:\.[0-9]{1,2})?)', re.IGNORECASE),
)

SQUARE_CURRENCY_PATTERN = re.compile(
    r'"currency"\s*:\s*"([A-Z]{3})"',
    re.IGNORECASE,
)

def parse_square_weebly_price(html):
    if not html:
        return None, None

    match = SQUARE_PRICE_MINOR_PATTERN.search(html)
    if match:
        try:
            return int(match.group(1)) / 100.0, match.group(2).upper()
        except (TypeError, ValueError):
            pass

    for pattern in SQUARE_PRICE_DECIMAL_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        try:
            amount = float(match.group(1))
        except (TypeError, ValueError):
            continue
        currency = None
        currency_match = SQUARE_CURRENCY_PATTERN.search(html)
        if currency_match:
            currency = currency_match.group(1).upper()
        return amount, currency

    return None, None

def parse_square_weebly_availability(html):
    lowered = (html or "").lower()

    explicit_out = (
        '"sold_out":true',
        '"soldout":true',
        '"out_of_stock":true',
        '"available":false',
        '"is_available":false',
        'data-sold-out="true"',
        "out of stock",
        "sold out",
        "currently unavailable",
    )

    if any(term in lowered for term in explicit_out):
        return False, True, "OUT_OF_STOCK"

    explicit_in = (
        '"available":true',
        '"is_available":true',
        'data-sold-out="false"',
        "add to cart",
        "add to bag",
    )

    if any(term in lowered for term in explicit_in):
        return True, True, "IN_STOCK"

    return False, False, "UNKNOWN"


def parse_availability(offer, html):
    if isinstance(offer, dict):
        availability = str(offer.get("availability") or "").strip().lower()

        if "instock" in availability:
            return True, True, "IN_STOCK"

        if "outofstock" in availability or "soldout" in availability:
            return False, True, "OUT_OF_STOCK"

    return parse_square_weebly_availability(html)

def parse_product_id_from_url(url):
    parsed = urlparse(url)
    match = re.search(
        r"/product/[^/]+/(\d+)",
        parsed.path,
        re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(1)


def product_url_priority_score(url):
    """
    Rank already-discovered public product URLs for fetch order.

    This is discovery prioritization only. It is NOT game classification.
    """

    lowered = str(url or "").lower()

    score = 0

    for term in TCG_URL_PRIORITY_TERMS:
        if term.lower() in lowered:
            score += 20

    for term in TCG_URL_NEGATIVE_TERMS:
        if term.lower() in lowered:
            score -= 10

    # Product slugs that look like sealed TCG inventory get a small boost.
    if any(
        term in lowered
        for term in (
            "booster",
            "starter-deck",
            "collection",
            "deck",
            "pack",
            "box",
            "tin",
        )
    ):
        score += 3

    return score


@retailer_adapter("square_weebly")
class SquareWeeblyAdapter(RetailerAdapter):

    platform = "square_weebly"

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
            .replace("https://", "")
            .replace("http://", "")
            .strip("/")
        )

        self.base_url = f"https://{domain}"
        self.request_delay = max(float(request_delay), 0.5)
        self.max_product_pages = max(1, min(int(max_product_pages), 500))
        self.diagnostics = {}
        self._reset_diagnostics()

    def _reset_diagnostics(self):
        self.diagnostics = {
            "pages_attempted": 0,
            "pages_successful": 0,
            "pages_failed": 0,
            "discovery_pages_visited": 0,
            "product_urls_total_discovered": 0,
            "product_urls_prioritized": 0,
            "product_urls_selected": 0,
            "product_urls_discovered": 0,
            "product_pages_attempted": 0,
            "product_pages_successful": 0,
            "product_pages_failed": 0,
            "products_accepted": 0,
            "products_rejected": 0,
            "unknown_availability": 0,
            "missing_prices": 0,
            "in_stock_products": 0,
            "out_of_stock_products": 0,
            "http_429": 0,
            "http_blocked": 0,
            "last_http_status": None,
            "last_error": None,
            "games": {},
            "categories": {
                "SEALED": 0,
                "SINGLE": 0,
                "ACCESSORY": 0,
                "UNKNOWN": 0,
            },
        }

    def get_diagnostics(self):
        data = dict(self.diagnostics)

        # Compatibility aliases for the current universal monitor.
        # Earlier monitor revisions used these alternate key names.
        data["pages_checked"] = int(
            data.get("discovery_pages_visited", 0) or 0
        )
        data["rejected_products"] = int(
            data.get("products_rejected", 0) or 0
        )
        data["normalized_products"] = int(
            data.get("products_accepted", 0) or 0
        )

        return data

    async def _fetch_text(self, session, url):
        self.diagnostics["pages_attempted"] += 1
        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)

        try:
            async with session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                self.diagnostics["last_http_status"] = response.status

                if response.status == 429:
                    self.diagnostics["http_429"] += 1
                    self.diagnostics["pages_failed"] += 1
                    print(
                        "SQUARE/WEEBLY RATE LIMITED | "
                        f"Store={self.store_name} | URL={url}"
                    )
                    return None

                if response.status in {401, 403}:
                    self.diagnostics["http_blocked"] += 1
                    self.diagnostics["pages_failed"] += 1
                    print(
                        "SQUARE/WEEBLY ACCESS BLOCKED | "
                        f"Store={self.store_name} | "
                        f"HTTP={response.status} | URL={url}"
                    )
                    return None

                if response.status >= 400:
                    self.diagnostics["pages_failed"] += 1
                    print(
                        "SQUARE/WEEBLY HTTP ERROR | "
                        f"Store={self.store_name} | "
                        f"HTTP={response.status} | URL={url}"
                    )
                    return None

                content_type = response.headers.get("Content-Type", "").lower()

                if (
                    "text/html" not in content_type
                    and "application/xhtml" not in content_type
                    and "text/xml" not in content_type
                    and "application/xml" not in content_type
                ):
                    self.diagnostics["pages_failed"] += 1
                    return None

                text = await response.text(errors="ignore")
                self.diagnostics["pages_successful"] += 1
                return text

        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            self.diagnostics["pages_failed"] += 1
            self.diagnostics["last_error"] = (
                f"{type(error).__name__}: {error}"
            )
            print(
                "SQUARE/WEEBLY REQUEST ERROR | "
                f"Store={self.store_name} | URL={url} | "
                f"{type(error).__name__}: {error}"
            )
            return None

    def _extract_product_urls(self, html, source_url):
        urls = set()

        if not html:
            return urls

        for match in HREF_PATTERN.finditer(html):
            candidate = normalize_url(source_url, match.group(1))

            if not candidate:
                continue

            if not is_same_domain(candidate, self.base_url):
                continue

            if not is_product_url(candidate):
                continue

            urls.add(canonicalize_product_url(candidate))

        for match in PRODUCT_PATH_PATTERN.finditer(html):
            candidate = normalize_url(source_url, match.group(0))

            if (
                candidate
                and is_same_domain(candidate, self.base_url)
                and is_product_url(candidate)
            ):
                urls.add(canonicalize_product_url(candidate))

        for match in ESCAPED_PRODUCT_PATH_PATTERN.finditer(html):
            candidate = normalize_url(source_url, match.group(0))

            if (
                candidate
                and is_same_domain(candidate, self.base_url)
                and is_product_url(candidate)
            ):
                urls.add(canonicalize_product_url(candidate))

        for match in XML_LOC_PATTERN.finditer(html):
            candidate = normalize_url(
                source_url,
                clean_text(match.group(1)),
            )

            if (
                candidate
                and is_same_domain(candidate, self.base_url)
                and is_product_url(candidate)
            ):
                urls.add(canonicalize_product_url(candidate))

        return urls

    def _extract_discovery_links(self, html, source_url):
        links = set()

        if not html:
            return links

        for match in HREF_PATTERN.finditer(html):
            candidate = normalize_url(source_url, match.group(1))

            if not candidate:
                continue

            if not is_same_domain(candidate, self.base_url):
                continue

            if is_discovery_candidate(candidate):
                parsed = urlparse(candidate)
                links.add(parsed._replace(fragment="").geturl())

        return links

    async def _discover_product_urls(self, session):
        discovered = set()

        seed_urls = [
            urljoin(self.base_url, path)
            for path in TCG_DISCOVERY_PATHS
        ]

        queue = list(seed_urls)
        queued = set(seed_urls)
        visited = set()

        while (
            queue
            and len(visited) < MAX_DISCOVERY_PAGES
            and len(discovered) < MAX_DISCOVERED_PRODUCT_URLS
        ):
            url = queue.pop(0)

            if url in visited:
                continue

            visited.add(url)
            html = await self._fetch_text(session, url)

            if not html:
                continue

            self.diagnostics["discovery_pages_visited"] += 1

            newly_found = self._extract_product_urls(
                html,
                url,
            )

            discovered.update(newly_found)

            if len(discovered) >= MAX_DISCOVERED_PRODUCT_URLS:
                break

            for candidate in self._extract_discovery_links(
                html,
                url,
            ):
                if candidate in visited or candidate in queued:
                    continue

                if len(queue) + len(visited) >= MAX_DISCOVERY_PAGES:
                    break

                queued.add(candidate)
                queue.append(candidate)

            if queue:
                await asyncio.sleep(self.request_delay)

        ranked = sorted(
            discovered,
            key=lambda url: (
                -product_url_priority_score(url),
                url.lower(),
            ),
        )

        prioritized_count = sum(
            1
            for url in ranked
            if product_url_priority_score(url) > 0
        )

        priority_urls = [
            url for url in ranked
            if product_url_priority_score(url) > 0
        ]
        fallback_urls = [
            url for url in ranked
            if product_url_priority_score(url) <= 0
        ]

        selected = list(priority_urls[: self.max_product_pages])
        if len(selected) < self.max_product_pages:
            selected.extend(
                fallback_urls[: self.max_product_pages - len(selected)]
            )

        self.diagnostics[
            "product_urls_total_discovered"
        ] = len(discovered)

        self.diagnostics[
            "product_urls_prioritized"
        ] = prioritized_count

        self.diagnostics[
            "product_urls_selected"
        ] = len(selected)

        # Keep this legacy key so the universal monitor continues to work.
        self.diagnostics[
            "product_urls_discovered"
        ] = len(discovered)

        print(
            "SQUARE/WEEBLY TCG-AWARE DISCOVERY | "
            f"Store={self.store_name} | "
            f"DiscoveryPages={self.diagnostics['discovery_pages_visited']} | "
            f"TotalProductURLs={len(discovered)} | "
            f"PriorityCandidates={prioritized_count} | "
            f"SelectedForFetch={len(selected)}"
        )

        return selected

    async def fetch_products(self):
        self._reset_diagnostics()

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        connector = aiohttp.TCPConnector(
            limit=4,
            limit_per_host=2,
        )

        async with aiohttp.ClientSession(
            headers=headers,
            connector=connector,
        ) as session:
            product_urls = await self._discover_product_urls(session)

            print(
                "SQUARE/WEEBLY FETCH PLAN | "
                f"Store={self.store_name} | "
                f"SelectedProductURLs={len(product_urls)} | "
                f"TotalDiscovered="
                f"{self.diagnostics['product_urls_total_discovered']} | "
                f"PriorityCandidates="
                f"{self.diagnostics['product_urls_prioritized']}"
            )

            raw_products = []

            for index, url in enumerate(product_urls):
                self.diagnostics["product_pages_attempted"] += 1
                html = await self._fetch_text(session, url)

                if html:
                    self.diagnostics["product_pages_successful"] += 1
                    raw_products.append({"url": url, "html": html})
                else:
                    self.diagnostics["product_pages_failed"] += 1

                if index < len(product_urls) - 1:
                    await asyncio.sleep(self.request_delay)

            print(
                "SQUARE/WEEBLY PRODUCT FETCH COMPLETE | "
                f"Store={self.store_name} | "
                f"Attempted={self.diagnostics['product_pages_attempted']} | "
                f"Successful={self.diagnostics['product_pages_successful']} | "
                f"Failed={self.diagnostics['product_pages_failed']}"
            )

            return raw_products

    def normalize_product(self, product):
        if not isinstance(product, dict):
            self.diagnostics["products_rejected"] += 1
            return None

        url = product.get("url")
        html = product.get("html") or ""

        if not url or not html:
            self.diagnostics["products_rejected"] += 1
            return None

        schema = find_product_schema(html)
        offer = parse_offer(schema)

        title = None

        if isinstance(schema, dict):
            title = clean_text(schema.get("name"))

        if not title:
            title = find_meta_value(
                html,
                OG_TITLE_PATTERN,
                OG_TITLE_PATTERN_REVERSED,
            )

        if not title:
            match = TITLE_PATTERN.search(html)
            if match:
                title = clean_text(match.group(1))

        if not title:
            self.diagnostics["products_rejected"] += 1
            return None

        title = re.sub(
            r"\s*\|\s*Hypno Comics.*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

        description = ""

        if isinstance(schema, dict):
            description = clean_text(schema.get("description"))

        if not description:
            description = (
                find_meta_value(
                    html,
                    META_DESCRIPTION_PATTERN,
                    META_DESCRIPTION_PATTERN_REVERSED,
                )
                or ""
            )

        game = classify_game(title)

        if not game:
            self.diagnostics["products_rejected"] += 1
            return None

        price = None

        if isinstance(offer, dict):
            price = normalize_price(offer.get("price"))

        if price is None:
            for pattern in PRICE_PATTERNS:
                match = pattern.search(html)

                if not match:
                    continue

                raw_price = match.group(1).replace(",", "")
                price = normalize_price(raw_price)

                if price is not None:
                    break

        square_currency = None

        if price is None:
            price, square_currency = parse_square_weebly_price(html)

        currency = "USD"

        if isinstance(offer, dict):
            offer_currency = offer.get("priceCurrency")
            if offer_currency:
                currency = str(offer_currency).strip().upper()

        if not isinstance(offer, dict) or not offer.get("priceCurrency"):
            match = CURRENCY_PATTERN.search(html)
            if match:
                currency = match.group(1).upper()
            elif square_currency:
                currency = square_currency

        if price is None:
            self.diagnostics["missing_prices"] += 1

        available, availability_known, availability_state = parse_availability(
            offer,
            html,
        )

        if not availability_known:
            self.diagnostics["unknown_availability"] += 1

        external_product_id = parse_product_id_from_url(url)
        sku = None

        if isinstance(schema, dict):
            schema_sku = schema.get("sku")
            if schema_sku:
                sku = clean_text(schema_sku)

        if not sku:
            for pattern in SKU_PATTERNS:
                match = pattern.search(html)
                if match:
                    sku = clean_text(match.group(1))
                    break

        image_url = None

        if isinstance(schema, dict):
            schema_image = schema.get("image")

            if isinstance(schema_image, list):
                if schema_image:
                    image_url = str(schema_image[0])
            elif schema_image:
                image_url = str(schema_image)

        if not image_url:
            image_url = find_meta_value(
                html,
                OG_IMAGE_PATTERN,
                OG_IMAGE_PATTERN_REVERSED,
            )

        product_category = classify_product_category(title)
        product_type = infer_product_type(title)
        product_family = classify_product_family(title)
        language = family_language(product_family)

        if availability_state == "IN_STOCK":
            self.diagnostics["in_stock_products"] += 1
            product_state = "STOCK_AVAILABLE"
        elif availability_state == "OUT_OF_STOCK":
            self.diagnostics["out_of_stock_products"] += 1
            product_state = "SOLD_OUT"
        else:
            product_state = "PAGE_LIVE"

        platform_data = {
            "adapter": "square_weebly",
            "external_product_id": external_product_id,
            "language": language,
            "availability_known": availability_known,
            "availability_state": availability_state,
            "description_present": bool(description),
        }

        self.diagnostics["products_accepted"] += 1

        games = self.diagnostics.setdefault("games", {})
        games[game] = int(games.get(game, 0) or 0) + 1

        categories = self.diagnostics.setdefault("categories", {})
        categories[product_category] = (
            int(categories.get(product_category, 0) or 0)
            + 1
        )

        print(
            "SQUARE/WEEBLY TCG ACCEPTED | "
            f"Store={self.store_name} | "
            f"Game={game} | "
            f"Category={product_category} | "
            f"Family={product_family} | "
            f"Price={price} {currency} | "
            f"Availability={availability_state} | "
            f"Title={title}"
        )

        return RetailerProduct(
            external_id=external_product_id,
            title=title,
            game=game,
            url=url,
            price=price,
            currency=currency,
            available=available,
            product_type=product_type,
            product_category=product_category,
            product_family=product_family,
            product_state=product_state,
            image_url=image_url,
            vendor=self.store_name,
            tags=None,
            sku=sku,
            external_product_id=external_product_id,
            offer_id=None,
            variant_id=None,
            purchase_limit=None,
            cart_base_url=None,
            platform_data=platform_data,
        )
