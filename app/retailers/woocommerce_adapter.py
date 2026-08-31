"""
Lotus Tracker Bot
PonDeX Trackers

WooCommerce Universal Retailer Adapter
Version: 1.0.4
Step 6J-1A — WooCommerce Public Store API Foundation

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
MAX_STORE_API_PAGES = 5
MAX_PRODUCTS = DEFAULT_PER_PAGE * MAX_STORE_API_PAGES

STORE_API_PRODUCT_PATHS = (
    "/wp-json/wc/store/v1/products",
    "/wp-json/wc/store/products",
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

    return any(term in lowered for term in SINGLE_KEYWORDS)


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
        max_pages=MAX_STORE_API_PAGES,
    ):
        super().__init__(
            domain=domain,
            region=region,
            store_name=store_name,
        )

        self.domain = normalize_domain(self.domain)
        self.base_url = f"https://{self.domain}"
        self.request_delay = max(float(request_delay), 0.5)
        self.max_pages = max(1, min(int(max_pages), MAX_STORE_API_PAGES))
        self.store_api_path = None
        self.diagnostics = {}
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

    async def fetch_products(self):
        self._reset_diagnostics()

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        connector = aiohttp.TCPConnector(
            limit=4,
            limit_per_host=2,
        )

        products = []

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
                return products

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
                        self.diagnostics["last_error"] = "INVALID_STORE_API_RESPONSE"
                    break

                if response is not None:
                    total = response.headers.get("X-WP-Total")
                    total_pages_header = response.headers.get("X-WP-TotalPages")

                    try:
                        self.diagnostics["store_api_total_products"] = int(total)
                    except (TypeError, ValueError):
                        pass

                    try:
                        parsed_total_pages = int(total_pages_header)
                        self.diagnostics["store_api_total_pages"] = parsed_total_pages
                    except (TypeError, ValueError):
                        parsed_total_pages = None

                products.extend(payload)

                print(
                    "WOOCOMMERCE PRODUCT PAGE | "
                    f"Store={self.store_name} | "
                    f"Page={page} | "
                    f"Products={len(payload)} | "
                    f"Accumulated={len(products)}"
                )

                if len(payload) < DEFAULT_PER_PAGE:
                    break

                if len(products) >= MAX_PRODUCTS:
                    break

                await asyncio.sleep(self.request_delay)

        products = products[:MAX_PRODUCTS]

        self.diagnostics["product_urls_discovered"] = len(products)
        self.diagnostics["product_pages_successful"] = len(products)

        print(
            "WOOCOMMERCE FETCH COMPLETE | "
            f"Store={self.store_name} | "
            f"ProductsFetched={len(products)} | "
            f"StoreTotal={self.diagnostics.get('store_api_total_products')} | "
            f"StorePages={self.diagnostics.get('store_api_total_pages')}"
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

        game = classify_game(title)

        if not game:
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
