"""
Lotus Tracker Bot
PonDeX Trackers

WooCommerce Universal Retailer Adapter
Version: 1.0.4
Step 6J-1G — Native Product Taxonomy Context + Pokemon Single Evidence

Safety:
- Public storefront Store API only
- GET requests only
- No authentication guessing
- No login
- No cart mutation
- No checkout automation
- No CAPTCHA / queue / anti-bot bypass
- Conservative bounded pagination
- Unknown availability never means sold out
"""

from __future__ import annotations

import asyncio
import re

from html import unescape
from urllib.parse import urlparse

import aiohttp

from app.retailer_adapter import (
    RetailerAdapter,
    RetailerProduct,
    normalize_price,
)
from app.retailer_registry import retailer_adapter


VERSION = "1.0.4"

USER_AGENT = (
    "LotusTracker/1.0.4 "
    "(PonDeX Trackers; public retailer monitor)"
)

DEFAULT_TIMEOUT = 15
DEFAULT_REQUEST_DELAY = 0.65
DEFAULT_PER_PAGE = 100

# Lotus does not crawl an entire large WooCommerce catalog every cycle.
# A small general sample is combined with bounded TCG-specific Store API
# searches. Results are deduplicated by WooCommerce product ID/permalink.
MAX_GENERAL_PAGES = 2
MAX_SEARCH_PAGES_PER_QUERY = 2
MAX_PRODUCTS = 1500

TCG_SEARCH_QUERIES = (
    "Pokemon TCG",
    "Pokémon TCG",
    "One Piece",
    "Gundam Card Game",
    "Dragon Ball Fusion World",
    "Riftbound",
    "Palworld",
    "Naruto TCG",
    "Cyberpunk TCG",
    "Azuki TCG",
    "Hellbreak TCG",
)

STORE_API_PRODUCT_PATHS = (
    "/wp-json/wc/store/v1/products",
    "/wp-json/wc/store/products",
)

STORE_API_CATEGORY_PATHS = (
    "/wp-json/wc/store/v1/products/categories",
    "/wp-json/wc/store/products/categories",
)

STORE_API_TAG_PATHS = (
    "/wp-json/wc/store/v1/products/tags",
    "/wp-json/wc/store/products/tags",
)

MAX_TAXONOMY_PAGES = 5
MAX_TAXONOMY_TERMS = 500
MAX_MATCHED_CATEGORIES = 30
MAX_TAXONOMY_REJECTION_LOGS = 40
MAX_MATCHED_TAGS = 30
MAX_TAXONOMY_PRODUCT_PAGES_PER_TERM = 2

TCG_TAXONOMY_TERMS = (
    "pokemon",
    "pokémon",
    "one piece",
    "gundam",
    "dragon ball",
    "fusion world",
    "riftbound",
    "palworld",
    "naruto",
    "cyberpunk",
    "azuki",
    "hellbreak",
)

# Pokémon-era/set taxonomy names are supporting evidence only.
# These are used together with strong single-card title structure.
POKEMON_TAXONOMY_HINT_TERMS = (
    "base",
    "jungle",
    "fossil",
    "team rocket",
    "gym",
    "neo",
    "e-card",
    "ex",
    "diamond & pearl",
    "diamond and pearl",
    "dp",
    "platinum",
    "heartgold & soulsilver",
    "heartgold and soulsilver",
    "hgss",
    "black & white",
    "black and white",
    "bw",
    "xy",
    "sun & moon",
    "sun and moon",
    "sm",
    "sword & shield",
    "sword and shield",
    "swsh",
    "scarlet & violet",
    "scarlet and violet",
    "sv",
    "pokemon go",
    "pokémon go",
)

POKEMON_CARD_TITLE_PATTERN = re.compile(
    r"\(#?\d{1,4}\)|\b[A-Z0-9]{2,6}\s+\d{1,4}\b",
    re.IGNORECASE,
)


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

POKEMON_SINGLE_NUMBER_PATTERN = re.compile(
    r"(?:^|[\s\-–—])#\s*[A-Z0-9]{1,6}(?:\s*/\s*[A-Z0-9]{1,6})?(?:\b|$)",
    re.IGNORECASE,
)

POKEMON_SET_NUMBER_PATTERN = re.compile(
    r"\b\d{1,4}\s*/\s*\d{1,4}\b",
    re.IGNORECASE,
)

POKEMON_CONDITION_PATTERN = re.compile(
    r"(?:^|[\s\-–—])(NM|LP|MP|HP|DMG|MINT|NEAR MINT|LIGHTLY PLAYED|"
    r"MODERATELY PLAYED|HEAVILY PLAYED|DAMAGED)(?:[\s\-–—]|$)",
    re.IGNORECASE,
)


GAME_PATTERNS = {
    "Pokemon": (
        "pokemon tcg",
        "pokémon tcg",
        "pokemon trading card",
        "pokémon trading card",
        "pokemon card game",
        "pokémon card game",
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
    "premium collection",
    "special collection",
    "case",
)

SINGLE_KEYWORDS = (
    "single card",
    "tcg single",
    "card single",
    "singles",
    "individual card",
    "black star promo",
    "promo card",
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

ONE_PIECE_CARD_NUMBER_PATTERN = re.compile(
    r"\b(?:OP|EB|PRB|ST|EX)\d{1,2}-\d{2,4}\b",
    re.IGNORECASE,
)
ONE_PIECE_PROMO_CARD_PATTERN = re.compile(
    r"\bP-\d{1,4}\b",
    re.IGNORECASE,
)


def clean_text(value):
    if value is None:
        return ""

    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_domain(domain):
    value = str(domain or "").strip()

    if value.startswith("https://"):
        value = value[8:]
    elif value.startswith("http://"):
        value = value[7:]

    return value.strip("/")


def product_identity_key(product):
    if not isinstance(product, dict):
        return None
    product_id = product.get("id")
    if product_id is not None:
        return f"id:{product_id}"
    permalink = clean_text(product.get("permalink"))
    return f"url:{permalink}" if permalink else None


def taxonomy_game_hint(term_names):
    names = [
        clean_text(x).lower()
        for x in (term_names or [])
        if clean_text(x)
    ]
    text = " ".join(names)

    if "pokemon" in text or "pokémon" in text:
        return "Pokemon"

    if any(
        hint == name
        or hint in name
        for name in names
        for hint in POKEMON_TAXONOMY_HINT_TERMS
    ):
        return "Pokemon"
    if "one piece" in text:
        return "One Piece"
    if "gundam" in text:
        return "Gundam"
    if "dragon ball fusion world" in text or "fusion world" in text:
        return "Dragon Ball Fusion World"
    if "riftbound" in text:
        return "Riftbound"
    if "palworld" in text:
        return "Palworld"
    if "naruto" in text:
        return "Naruto"
    if "cyberpunk" in text:
        return "Cyberpunk TCG"
    if "azuki" in text:
        return "Azuki TCG"
    if "hellbreak" in text:
        return "Hellbreak TCG"
    return None


def strong_card_listing_structure(title):
    text = clean_text(title)
    lowered = text.lower()

    if ONE_PIECE_CARD_NUMBER_PATTERN.search(text):
        return True

    if POKEMON_SET_NUMBER_PATTERN.search(text):
        return True

    if (
        POKEMON_SINGLE_NUMBER_PATTERN.search(text)
        and POKEMON_CONDITION_PATTERN.search(text)
    ):
        return True

    if any(term in lowered for term in SINGLE_KEYWORDS):
        return True

    # Evolved and similar single-card stores commonly use:
    #   Card Name (#117) ... ASC 117
    #   M Mewtwo EX (#63) ... BKT 63
    # The title must contain an explicit collector/card number structure.
    if POKEMON_CARD_TITLE_PATTERN.search(text):
        return True

    return False


def classify_game_with_taxonomy(title, taxonomy_terms):
    direct = classify_game(title)
    if direct:
        return direct, "TITLE"
    hint = taxonomy_game_hint(taxonomy_terms)
    if hint and strong_card_listing_structure(title):
        return hint, "TAXONOMY_PLUS_CARD_STRUCTURE"
    return None, "TAXONOMY_INSUFFICIENT" if hint else "NONE"


def classify_game(title):
    text = clean_text(title).lower()

    if not text:
        return None

    for unsupported in UNSUPPORTED_GAME_TERMS:
        if unsupported in text:
            return None

    if "one piece card game" in text or "one piece tcg" in text:
        return "One Piece"

    if re.search(r"\bop[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if re.search(r"\beb[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if re.search(r"\bprb[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if re.search(r"\bst[\s-]?(?:0[1-9]|[1-9][0-9])\b", text):
        return "One Piece"

    if "one piece" in text and re.search(r"\bp[\s-]?\d{1,4}\b", text):
        return "One Piece"

    for game, phrases in GAME_PATTERNS.items():
        if any(phrase in text for phrase in phrases):
            return game

    return None


def has_strong_single_card_evidence(title):
    text = clean_text(title)

    if ONE_PIECE_CARD_NUMBER_PATTERN.search(text):
        return True

    lowered = text.lower()

    if (
        "one piece" in lowered
        and ONE_PIECE_PROMO_CARD_PATTERN.search(text)
    ):
        return True

    if any(term in lowered for term in SINGLE_KEYWORDS):
        return True

    # Strict Pokémon single-card evidence:
    # require Pokémon TCG context plus card-listing structure.
    # This intentionally does not classify sealed products from a bare
    # number or condition abbreviation alone.
    pokemon_context = (
        "pokemon tcg" in lowered
        or "pokémon tcg" in lowered
        or "pokemon trading card" in lowered
        or "pokémon trading card" in lowered
    )

    if pokemon_context:
        has_number = bool(
            POKEMON_SINGLE_NUMBER_PATTERN.search(text)
            or POKEMON_SET_NUMBER_PATTERN.search(text)
        )
        has_condition = bool(
            POKEMON_CONDITION_PATTERN.search(text)
        )

        if has_number and has_condition:
            return True

        # Evolved TCG and similar singles catalogs commonly use several
        # dash-separated card metadata fields ending in a collector number.
        dash_parts = [
            part.strip()
            for part in re.split(r"\s+[\-–—]\s+", text)
            if part.strip()
        ]

        if (
            len(dash_parts) >= 4
            and has_number
        ):
            return True

    return False


def classify_product_category(title):
    text = clean_text(title).lower()

    if has_strong_single_card_evidence(title):
        return "SINGLE"

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
        if any(keyword in text for keyword in keywords):
            return label

    return "TCG Product"


def classify_product_family(title, product=None):
    pieces = [clean_text(title)]

    # Family detection may use public product metadata, but never currency.
    if isinstance(product, dict):
        for tag in product.get("tags") or []:
            if isinstance(tag, dict):
                pieces.append(clean_text(tag.get("name")))
        for attribute in product.get("attributes") or []:
            if not isinstance(attribute, dict):
                continue
            pieces.append(clean_text(attribute.get("name")))
            for term in attribute.get("terms") or []:
                if isinstance(term, dict):
                    pieces.append(clean_text(term.get("name")))

    text = " ".join(pieces).lower()

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
    return {
        "GLOBAL_STANDARD": "English",
        "JP": "Japanese",
        "KR": "Korean",
        "CN": "Simplified Chinese",
        "UNKNOWN": "Unknown",
    }.get(family, "Unknown")


def parse_wc_price(product):
    prices = product.get("prices")

    if not isinstance(prices, dict):
        return None, "USD"

    currency = clean_text(prices.get("currency_code") or "USD").upper()

    minor_unit = prices.get("currency_minor_unit")
    try:
        minor_unit = int(minor_unit)
    except (TypeError, ValueError):
        minor_unit = 2

    raw = prices.get("price")

    if raw in (None, ""):
        return None, currency

    try:
        integer_value = int(str(raw))
        price = integer_value / (10 ** max(0, minor_unit))
        return normalize_price(price), currency
    except (TypeError, ValueError):
        return normalize_price(raw), currency


def parse_wc_availability(product):
    value = product.get("is_in_stock")

    if isinstance(value, bool):
        return (
            value,
            True,
            "IN_STOCK" if value else "OUT_OF_STOCK",
            "WC_STORE_API_IS_IN_STOCK",
        )

    return False, False, "UNKNOWN", "UNKNOWN"


def first_image_url(product):
    images = product.get("images")

    if not isinstance(images, list):
        return None

    for image in images:
        if not isinstance(image, dict):
            continue
        src = clean_text(image.get("src"))
        if src:
            return src

    return None


@retailer_adapter("woocommerce")
class WooCommerceAdapter(RetailerAdapter):

    platform = "woocommerce"

    def __init__(
        self,
        *,
        domain,
        region="US",
        store_name=None,
        request_delay=DEFAULT_REQUEST_DELAY,
        max_pages=MAX_GENERAL_PAGES,
    ):
        super().__init__(
            domain=domain,
            region=region,
            store_name=store_name,
        )

        self.domain = normalize_domain(self.domain)
        self.base_url = f"https://{self.domain}"
        self.request_delay = max(float(request_delay), 0.5)
        self.max_pages = max(1, min(int(max_pages), MAX_GENERAL_PAGES))
        self.store_api_path = None
        self.diagnostics = {}
        self.product_taxonomy_context = {}
        self.category_terms_by_id = {}
        self._reset_diagnostics()

    def _reset_diagnostics(self):
        self.diagnostics = {
            "pages_checked": 0,
            "pages_successful": 0,
            "pages_failed": 0,
            "product_urls_discovered": 0,
            "product_pages_successful": 0,
            "products_accepted": 0,
            "products_rejected": 0,
            "normalized_products": 0,
            "unknown_availability": 0,
            "missing_prices": 0,
            "in_stock_products": 0,
            "out_of_stock_products": 0,
            "store_api_endpoint": None,
            "store_api_total_products": None,
            "store_api_total_pages": None,
            "search_queries_attempted": 0,
            "search_queries_successful": 0,
            "search_products_returned": 0,
            "unique_products_collected": 0,
            "taxonomy_category_terms_seen": 0,
            "taxonomy_tag_terms_seen": 0,
            "taxonomy_categories_matched": 0,
            "taxonomy_tags_matched": 0,
            "taxonomy_hierarchy_roots": 0,
            "taxonomy_category_descendants_matched": 0,
            "taxonomy_assisted_candidates": 0,
            "taxonomy_rejections_logged": 0,
            "taxonomy_rejections_card_structure": 0,
            "taxonomy_products_returned": 0,
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
        return dict(self.diagnostics)

    async def _fetch_json(self, session, url):
        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
        self.diagnostics["pages_checked"] += 1

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
                    return None, response

                if response.status in {401, 403}:
                    self.diagnostics["http_blocked"] += 1
                    self.diagnostics["pages_failed"] += 1
                    return None, response

                if response.status >= 400:
                    self.diagnostics["pages_failed"] += 1
                    return None, response

                try:
                    payload = await response.json(content_type=None)
                except Exception as error:
                    self.diagnostics["pages_failed"] += 1
                    self.diagnostics["last_error"] = (
                        f"JSON_DECODE:{type(error).__name__}:{error}"
                    )
                    return None, response

                self.diagnostics["pages_successful"] += 1
                return payload, response

        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            self.diagnostics["pages_failed"] += 1
            self.diagnostics["last_error"] = (
                f"{type(error).__name__}: {error}"
            )
            return None, None

    async def _select_store_api_path(self, session):
        for path in STORE_API_PRODUCT_PATHS:
            url = (
                f"{self.base_url}{path}"
                f"?per_page=1&page=1"
            )

            payload, response = await self._fetch_json(session, url)

            if isinstance(payload, list):
                self.store_api_path = path
                self.diagnostics["store_api_endpoint"] = path

                if response is not None:
                    total = response.headers.get("X-WP-Total")
                    total_pages = response.headers.get("X-WP-TotalPages")

                    try:
                        self.diagnostics["store_api_total_products"] = int(total)
                    except (TypeError, ValueError):
                        pass

                    try:
                        self.diagnostics["store_api_total_pages"] = int(total_pages)
                    except (TypeError, ValueError):
                        pass

                print(
                    "WOOCOMMERCE STORE API DETECTED | "
                    f"Store={self.store_name} | "
                    f"Endpoint={path}"
                )
                return path

        return None

    async def _fetch_taxonomy_terms(self, session, paths, diagnostic_key):
        selected_path = None
        terms = []
        for path in paths:
            payload, _ = await self._fetch_json(
                session, f"{self.base_url}{path}?per_page=1&page=1"
            )
            if isinstance(payload, list):
                selected_path = path
                break
        if not selected_path:
            return []
        for page in range(1, MAX_TAXONOMY_PAGES + 1):
            payload, _ = await self._fetch_json(
                session,
                f"{self.base_url}{selected_path}?per_page={DEFAULT_PER_PAGE}&page={page}",
            )
            if not isinstance(payload, list):
                break
            terms.extend(payload)
            if len(terms) >= MAX_TAXONOMY_TERMS:
                terms = terms[:MAX_TAXONOMY_TERMS]
                break
            if len(payload) < DEFAULT_PER_PAGE:
                break
            await asyncio.sleep(self.request_delay)
        self.diagnostics[diagnostic_key] = len(terms)
        return terms

    def _build_category_hierarchy(self, terms):
        by_id = {}
        children = {}
        for term in terms or []:
            if not isinstance(term, dict) or term.get("id") is None:
                continue
            by_id[str(term["id"])] = term
        for key, term in by_id.items():
            try:
                parent_key = str(int(term.get("parent") or 0))
            except (TypeError, ValueError):
                parent_key = "0"
            children.setdefault(parent_key, []).append(key)
        return by_id, children

    def _category_ancestry_names(self, term_id, by_id):
        names, visited = [], set()
        current = str(term_id)
        for _ in range(12):
            if current in visited:
                break
            visited.add(current)
            term = by_id.get(current)
            if not term:
                break
            name = clean_text(term.get("name"))
            if name:
                names.append(name)
            try:
                parent_id = int(term.get("parent") or 0)
            except (TypeError, ValueError):
                break
            if parent_id <= 0:
                break
            current = str(parent_id)
        return names

    def _matching_hierarchical_categories(self, terms, limit):
        by_id, children = self._build_category_hierarchy(terms)
        roots = []
        for term_id, term in by_id.items():
            name = clean_text(term.get("name")).lower()
            if any(marker in name for marker in TCG_TAXONOMY_TERMS):
                roots.append(term_id)

        selected, seen, queue = [], set(), list(roots)
        while queue and len(selected) < limit:
            term_id = queue.pop(0)
            if term_id in seen:
                continue
            seen.add(term_id)
            selected.append(term_id)
            queue.extend(
                child for child in children.get(term_id, [])
                if child not in seen
            )

        matched = []
        for term_id in selected:
            term = by_id.get(term_id)
            if term:
                matched.append({
                    "id": term_id,
                    "name": clean_text(term.get("name")),
                    "ancestry": self._category_ancestry_names(term_id, by_id),
                    "is_direct_root": term_id in roots,
                })

        self.diagnostics["taxonomy_hierarchy_roots"] = len(roots)
        self.diagnostics["taxonomy_category_descendants_matched"] = sum(
            1 for item in matched if not item["is_direct_root"]
        )
        return matched

    def _matching_taxonomy_terms(self, terms, limit):
        matched = []
        seen = set()
        for term in terms or []:
            if not isinstance(term, dict):
                continue
            term_id = term.get("id")
            name = clean_text(term.get("name"))
            if term_id is None or not name:
                continue
            lowered = name.lower()
            if not any(marker in lowered for marker in TCG_TAXONOMY_TERMS):
                continue
            key = str(term_id)
            if key in seen:
                continue
            seen.add(key)
            matched.append({"id": key, "name": name})
            if len(matched) >= limit:
                break
        return matched

    async def fetch_products(self):
        self._reset_diagnostics()
        self.product_taxonomy_context = {}
        self.category_terms_by_id = {}

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        connector = aiohttp.TCPConnector(
            limit=4,
            limit_per_host=2,
        )

        products_by_key = {}

        def add_products(items):
            if not isinstance(items, list):
                return 0

            added = 0

            for item in items:
                if not isinstance(item, dict):
                    continue

                product_id = item.get("id")
                permalink = clean_text(item.get("permalink"))

                if product_id is not None:
                    key = f"id:{product_id}"
                elif permalink:
                    key = f"url:{permalink}"
                else:
                    continue

                if key in products_by_key:
                    continue

                products_by_key[key] = item
                added += 1

                if len(products_by_key) >= MAX_PRODUCTS:
                    break

            return added

        async with aiohttp.ClientSession(
            headers=headers,
            connector=connector,
        ) as session:
            path = await self._select_store_api_path(session)

            if not path:
                self.diagnostics["last_error"] = "PUBLIC_STORE_API_NOT_FOUND"
                print(
                    "WOOCOMMERCE STORE API UNAVAILABLE | "
                    f"Store={self.store_name} | "
                    "Reason=PUBLIC_STORE_API_NOT_FOUND"
                )
                return []

            # -------------------------------------------------
            # General bounded sample.
            # -------------------------------------------------

            total_pages = self.diagnostics.get("store_api_total_pages")
            pages_to_fetch = self.max_pages

            if isinstance(total_pages, int) and total_pages > 0:
                pages_to_fetch = min(pages_to_fetch, total_pages)

            for page in range(1, pages_to_fetch + 1):
                url = (
                    f"{self.base_url}{path}"
                    f"?per_page={DEFAULT_PER_PAGE}&page={page}"
                )

                payload, response = await self._fetch_json(session, url)

                if not isinstance(payload, list):
                    if page == 1:
                        self.diagnostics["last_error"] = (
                            "INVALID_STORE_API_RESPONSE"
                        )
                    break

                if response is not None:
                    total = response.headers.get("X-WP-Total")
                    total_pages_header = response.headers.get(
                        "X-WP-TotalPages"
                    )

                    try:
                        self.diagnostics["store_api_total_products"] = int(total)
                    except (TypeError, ValueError):
                        pass

                    try:
                        parsed_total_pages = int(total_pages_header)
                        self.diagnostics["store_api_total_pages"] = (
                            parsed_total_pages
                        )
                    except (TypeError, ValueError):
                        pass

                added = add_products(payload)

                print(
                    "WOOCOMMERCE GENERAL PAGE | "
                    f"Store={self.store_name} | "
                    f"Page={page} | "
                    f"Returned={len(payload)} | "
                    f"NewUnique={added} | "
                    f"UniqueTotal={len(products_by_key)}"
                )

                if len(payload) < DEFAULT_PER_PAGE:
                    break

                if len(products_by_key) >= MAX_PRODUCTS:
                    break

                await asyncio.sleep(self.request_delay)

            # -------------------------------------------------
            # TCG-aware public Store API searches.
            #
            # WooCommerce Store API supports a public `search`
            # collection parameter. We use bounded searches rather
            # than crawling all 27k+ products from a large store.
            # Final game acceptance remains strict title-based.
            # -------------------------------------------------

            from urllib.parse import urlencode

            for query in TCG_SEARCH_QUERIES:
                if len(products_by_key) >= MAX_PRODUCTS:
                    break

                self.diagnostics["search_queries_attempted"] += 1
                query_returned = 0
                query_added = 0
                query_success = False

                for page in range(1, MAX_SEARCH_PAGES_PER_QUERY + 1):
                    params = urlencode(
                        {
                            "per_page": DEFAULT_PER_PAGE,
                            "page": page,
                            "search": query,
                        }
                    )
                    url = f"{self.base_url}{path}?{params}"

                    payload, _ = await self._fetch_json(session, url)

                    if not isinstance(payload, list):
                        break

                    query_success = True
                    query_returned += len(payload)
                    query_added += add_products(payload)

                    if len(payload) < DEFAULT_PER_PAGE:
                        break

                    if len(products_by_key) >= MAX_PRODUCTS:
                        break

                    await asyncio.sleep(self.request_delay)

                if query_success:
                    self.diagnostics["search_queries_successful"] += 1

                self.diagnostics["search_products_returned"] += query_returned

                print(
                    "WOOCOMMERCE TCG SEARCH | "
                    f"Store={self.store_name} | "
                    f"Query={query} | "
                    f"Returned={query_returned} | "
                    f"NewUnique={query_added} | "
                    f"UniqueTotal={len(products_by_key)}"
                )

                await asyncio.sleep(self.request_delay)

            # Taxonomy is discovery-only. Strict title classification remains final.
            category_terms = await self._fetch_taxonomy_terms(
                session, STORE_API_CATEGORY_PATHS, "taxonomy_category_terms_seen"
            )
            tag_terms = await self._fetch_taxonomy_terms(
                session, STORE_API_TAG_PATHS, "taxonomy_tag_terms_seen"
            )
            self.category_terms_by_id = {
                str(term.get("id")): term
                for term in (category_terms or [])
                if isinstance(term, dict)
                and term.get("id") is not None
            }

            matched_categories = self._matching_hierarchical_categories(
                category_terms, MAX_MATCHED_CATEGORIES
            )
            matched_tags = self._matching_taxonomy_terms(
                tag_terms, MAX_MATCHED_TAGS
            )
            self.diagnostics["taxonomy_categories_matched"] = len(matched_categories)
            self.diagnostics["taxonomy_tags_matched"] = len(matched_tags)
            print(
                "WOOCOMMERCE TAXONOMY DISCOVERY | "
                f"Store={self.store_name} | CategoriesSeen={len(category_terms)} | "
                f"HierarchyRoots={self.diagnostics.get('taxonomy_hierarchy_roots')} | "
                f"CategoriesMatched={len(matched_categories)} | "
                f"DescendantsMatched={self.diagnostics.get('taxonomy_category_descendants_matched')} | "
                f"TagsSeen={len(tag_terms)} | TagsMatched={len(matched_tags)}"
            )
            from urllib.parse import urlencode
            for kind, parameter, term in (
                [("CATEGORY", "category", x) for x in matched_categories]
                + [("TAG", "tag", x) for x in matched_tags]
            ):
                if len(products_by_key) >= MAX_PRODUCTS:
                    break
                returned = added_total = 0
                for page in range(1, MAX_TAXONOMY_PRODUCT_PAGES_PER_TERM + 1):
                    params = urlencode({"per_page": DEFAULT_PER_PAGE, "page": page, parameter: term["id"]})
                    payload, _ = await self._fetch_json(session, f"{self.base_url}{path}?{params}")
                    if not isinstance(payload, list):
                        break
                    returned += len(payload)

                    for taxonomy_product in payload:
                        key = product_identity_key(taxonomy_product)
                        if not key:
                            continue
                        context = self.product_taxonomy_context.setdefault(
                            key, {"categories": [], "tags": []}
                        )
                        bucket = "categories" if kind == "CATEGORY" else "tags"
                        evidence_names = (
                            (term.get("ancestry") or [term["name"]])
                            if kind == "CATEGORY"
                            else [term["name"]]
                        )
                        for evidence_name in evidence_names:
                            if evidence_name not in context[bucket]:
                                context[bucket].append(evidence_name)

                    added_total += add_products(payload)
                    if len(payload) < DEFAULT_PER_PAGE or len(products_by_key) >= MAX_PRODUCTS:
                        break
                    await asyncio.sleep(self.request_delay)
                self.diagnostics["taxonomy_products_returned"] += returned
                print(
                    "WOOCOMMERCE TAXONOMY PRODUCTS | "
                    f"Store={self.store_name} | Type={kind} | Term={term['name']} | "
                    f"TermID={term['id']} | Returned={returned} | NewUnique={added_total} | "
                    f"UniqueTotal={len(products_by_key)}"
                )
                await asyncio.sleep(self.request_delay)

        products = list(products_by_key.values())[:MAX_PRODUCTS]

        self.diagnostics["product_urls_discovered"] = len(products)
        self.diagnostics["product_pages_successful"] = len(products)
        self.diagnostics["unique_products_collected"] = len(products)

        print(
            "WOOCOMMERCE TCG-AWARE DISCOVERY | "
            f"Store={self.store_name} | "
            f"StoreTotal={self.diagnostics.get('store_api_total_products')} | "
            f"StorePages={self.diagnostics.get('store_api_total_pages')} | "
            f"GeneralPages={self.max_pages} | "
            f"SearchQueries="
            f"{self.diagnostics.get('search_queries_attempted')} | "
            f"SearchProductsReturned="
            f"{self.diagnostics.get('search_products_returned')} | "
            f"CategoriesMatched={self.diagnostics.get('taxonomy_categories_matched')} | "
            f"TagsMatched={self.diagnostics.get('taxonomy_tags_matched')} | "
            f"TaxonomyProductsReturned={self.diagnostics.get('taxonomy_products_returned')} | "
            f"UniqueProducts={len(products)}"
        )

        print(
            "WOOCOMMERCE FETCH COMPLETE | "
            f"Store={self.store_name} | "
            f"ProductsFetched={len(products)} | "
            f"StoreTotal={self.diagnostics.get('store_api_total_products')} | "
            f"StorePages={self.diagnostics.get('store_api_total_pages')}"
        )

        return products

    def _native_product_taxonomy_context(self, product):
        context = {
            "categories": [],
            "tags": [],
        }

        if not isinstance(product, dict):
            return context

        for category in product.get("categories") or []:
            if not isinstance(category, dict):
                continue

            category_id = category.get("id")
            category_name = clean_text(category.get("name"))

            names = []

            if category_id is not None and self.category_terms_by_id:
                names = self._category_ancestry_names(
                    str(category_id),
                    self.category_terms_by_id,
                )

            if not names and category_name:
                names = [category_name]

            for name in names:
                if name and name not in context["categories"]:
                    context["categories"].append(name)

        for tag in product.get("tags") or []:
            if not isinstance(tag, dict):
                continue

            tag_name = clean_text(tag.get("name"))
            if tag_name and tag_name not in context["tags"]:
                context["tags"].append(tag_name)

        return context

    def _log_taxonomy_rejection(
        self,
        *,
        title,
        taxonomy_context,
        game_hint,
        card_structure,
        reason,
    ):
        categories = list(taxonomy_context.get("categories") or [])
        tags = list(taxonomy_context.get("tags") or [])

        if not categories and not tags:
            return

        self.diagnostics["taxonomy_assisted_candidates"] += 1

        if card_structure:
            self.diagnostics["taxonomy_rejections_card_structure"] += 1

        if self.diagnostics["taxonomy_rejections_logged"] >= MAX_TAXONOMY_REJECTION_LOGS:
            return

        self.diagnostics["taxonomy_rejections_logged"] += 1

        print(
            "WOOCOMMERCE TAXONOMY REJECTED | "
            f"Store={self.store_name} | "
            f"Title={title} | "
            f"GameHint={game_hint or 'none'} | "
            f"CardStructure={card_structure} | "
            f"Categories={','.join(categories) or 'none'} | "
            f"Tags={','.join(tags) or 'none'} | "
            f"Reason={reason}"
        )

    async def get_normalized_products(self):
        products = await super().get_normalized_products()

        print(
            "WOOCOMMERCE TAXONOMY REJECTION SUMMARY | "
            f"Store={self.store_name} | "
            f"Candidates={self.diagnostics.get('taxonomy_assisted_candidates')} | "
            f"Logged={self.diagnostics.get('taxonomy_rejections_logged')} | "
            f"CardStructureRejects="
            f"{self.diagnostics.get('taxonomy_rejections_card_structure')} | "
            f"Accepted={self.diagnostics.get('products_accepted')}"
        )

        return products

    def normalize_product(self, product):
        if not isinstance(product, dict):
            self.diagnostics["products_rejected"] += 1
            return None

        title = clean_text(product.get("name"))
        url = clean_text(product.get("permalink"))

        if not title or not url:
            self.diagnostics["products_rejected"] += 1
            return None

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            self.diagnostics["products_rejected"] += 1
            return None

        product_key = product_identity_key(product)
        taxonomy_context = self.product_taxonomy_context.get(
            product_key, {"categories": [], "tags": []}
        ) if product_key else {"categories": [], "tags": []}

        native_taxonomy = self._native_product_taxonomy_context(
            product
        )

        for bucket in ("categories", "tags"):
            for value in native_taxonomy.get(bucket) or []:
                if value not in taxonomy_context[bucket]:
                    taxonomy_context[bucket].append(value)

        taxonomy_terms = (
            list(taxonomy_context.get("categories") or [])
            + list(taxonomy_context.get("tags") or [])
        )

        game, game_classification_source = classify_game_with_taxonomy(
            title, taxonomy_terms
        )

        if not game:
            game_hint = taxonomy_game_hint(taxonomy_terms)
            card_structure = strong_card_listing_structure(title)

            if taxonomy_terms:
                if not game_hint:
                    rejection_reason = "NO_SUPPORTED_GAME_HINT"
                elif not card_structure:
                    rejection_reason = "GAME_HINT_PRESENT_BUT_NO_STRONG_CARD_STRUCTURE"
                else:
                    rejection_reason = "CLASSIFIER_REJECTED_DESPITE_SUPPORTING_EVIDENCE"

                self._log_taxonomy_rejection(
                    title=title,
                    taxonomy_context=taxonomy_context,
                    game_hint=game_hint,
                    card_structure=card_structure,
                    reason=rejection_reason,
                )

            self.diagnostics["products_rejected"] += 1
            return None

        price, currency = parse_wc_price(product)

        if price is None:
            self.diagnostics["missing_prices"] += 1

        (
            available,
            availability_known,
            availability_state,
            availability_source,
        ) = parse_wc_availability(product)

        if not availability_known:
            self.diagnostics["unknown_availability"] += 1
        elif available:
            self.diagnostics["in_stock_products"] += 1
        else:
            self.diagnostics["out_of_stock_products"] += 1

        product_category = classify_product_category(title)
        product_type = infer_product_type(title)
        product_family = classify_product_family(title, product)
        language = family_language(product_family)

        if availability_state == "IN_STOCK":
            product_state = "STOCK_AVAILABLE"
        elif availability_state == "OUT_OF_STOCK":
            product_state = "SOLD_OUT"
        else:
            product_state = "PAGE_LIVE"

        product_id = product.get("id")
        external_product_id = (
            str(product_id)
            if product_id is not None
            else None
        )

        sku = clean_text(product.get("sku")) or None
        image_url = first_image_url(product)

        platform_data = {
            "adapter": "woocommerce",
            "store_api_endpoint": self.store_api_path,
            "availability_known": availability_known,
            "availability_state": availability_state,
            "availability_source": availability_source,
            "availability_capability": (
                "FULL_AVAILABILITY"
                if availability_known
                else (
                    "DISCOVERY_PRICE_ONLY"
                    if price is not None
                    else "DISCOVERY_ONLY"
                )
            ),
            "language": language,
            "is_purchasable": product.get("is_purchasable"),
            "low_stock_remaining": product.get("low_stock_remaining"),
            "woo_product_type": product.get("type"),
            "game_classification_source": game_classification_source,
            "taxonomy_categories": taxonomy_context.get("categories") or [],
            "taxonomy_tags": taxonomy_context.get("tags") or [],
        }

        self.diagnostics["products_accepted"] += 1
        self.diagnostics["normalized_products"] += 1

        games = self.diagnostics.setdefault("games", {})
        games[game] = int(games.get(game, 0) or 0) + 1

        categories = self.diagnostics.setdefault("categories", {})
        categories[product_category] = (
            int(categories.get(product_category, 0) or 0) + 1
        )

        print(
            "WOOCOMMERCE TCG ACCEPTED | "
            f"Store={self.store_name} | "
            f"Game={game} | "
            f"Category={product_category} | "
            f"Family={product_family} | "
            f"Price={price} {currency} | "
            f"Availability={availability_state} | "
            f"AvailabilitySource={availability_source} | "
            f"AvailabilityCapability="
            f"{platform_data['availability_capability']} | "
            f"GameSource={game_classification_source} | "
            f"TaxonomyCategories={','.join(taxonomy_context.get('categories') or []) or 'none'} | "
            f"TaxonomyTags={','.join(taxonomy_context.get('tags') or []) or 'none'} | "
            f"Title={title}"
        )

        print(
            "WOOCOMMERCE AVAILABILITY INTEGRITY | "
            f"Store={self.store_name} | ProductID={external_product_id} | "
            f"AdapterAvailable={available} | AvailabilityKnown={availability_known} | "
            f"AvailabilityState={availability_state} | "
            f"AvailabilityCapability={platform_data['availability_capability']} | "
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