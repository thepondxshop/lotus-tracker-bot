"""
Lotus Tracker Bot / PonDeX Trackers
Shopware 6 Universal Retailer Adapter
Version 1.0.4

Step 6J-3F7 — Browser-Parity Storefront Retrieval + Loose Anchor Discovery
Initial production target: Miniature Market

Safety:
- Public storefront GET requests only.
- No Shopware administration API access or credential guessing.
- No cart mutation, checkout automation, CAPTCHA/queue bypass, or login automation.
- Conservative bounded discovery, request pacing, and per-run limits.
- Availability is trusted only when a public product/listing page exposes an
  explicit signal. Unknown availability never means sold out.
- Missing/non-positive prices are treated as unknown and never as a price drop.

Design:
- Browser-parity retrieval uses an ordinary desktop browser User-Agent because some
  Shopware/CDN combinations serve a reduced navigation shell to non-browser UAs.
  This does not bypass authentication, CAPTCHA, queues, or access controls.
- Deep discovery scans public Shopware category/listing pages and extracts
  supported TCG products directly from product cards. This avoids crawling an
  entire large catalog product-by-product.
- Known products are refreshed from their public product pages through
  get_normalized_products_from_urls(), allowing the universal monitor's
  sharded fast-refresh engine to watch stock/price changes efficiently.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import aiohttp

from app.retailer_adapter import RetailerAdapter, RetailerProduct, normalize_price
from app.retailer_registry import retailer_adapter


VERSION = "1.0.4"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

BROWSER_NAV_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

DEFAULT_TIMEOUT = 18
DEFAULT_REQUEST_DELAY = 0.35
MAX_BODY_BYTES = 12_000_000
MAX_LISTING_PAGES = 36
MAX_PREORDER_PAGES = 14
MAX_PRODUCT_PAGES = 350
MAX_CONCURRENT_PRODUCT_REQUESTS = 6
MAX_FRAGMENT_URLS_PER_ROOT = 4
MAX_PRODUCT_SITEMAP_PAGES = 30
PRODUCT_SITEMAP_TARGET = 140
MAX_SITEMAP_PRODUCT_PAGE_FETCHES = 120
MAX_XML_SITEMAP_DOCUMENTS = 24
XML_SITEMAP_TARGET = 180
XML_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
)

# Miniature Market exposes the canonical Shopware category at the first path.
# The additional paths keep the adapter useful for other public Shopware shops.
DEFAULT_LISTING_PATHS = (
    "/trading-card-games.html",
    "/trading-card-games",
    "/tcg.html",
    "/tcg",
    "/cards.html",
    "/cards",
)

# Miniature Market has a very large all-TCG listing.  Smaller game-specific
# Shopware category pages are deliberately attempted first so initial
# onboarding can discover supported products without depending on one huge
# category response.  These paths are only injected for miniaturemarket.com.
MINIATURE_MARKET_PRIORITY_PATHS = (
    "/trading-card-games/pokemon.html",
    "/trading-card-games/one-piece.html",
    "/trading-card-games/gundam-card-game",
    "/trading-card-games/riftbound",
    "/trading-card-games/preorders.html",
    "/trading-card-games/new-releases.html",
)

DEFAULT_PREORDER_PATHS = (
    "/preorders",
    "/preorders.html",
    "/pre-order",
    "/pre-order.html",
)

CATEGORY_DISCOVERY_PATHS = (
    "/",
    "/category-sitemap",
    "/sitemap",
)

PRODUCT_SITEMAP_PATH = "/product-sitemap"

SHOPWARE_PLATFORM_PROBE_PATHS = (
    "/account/login",
    "/trading-card-games.html",
    "/",
)

SHOPWARE_STRONG_MARKERS = (
    "full range of shopware 6",
    "data-shopware-plugin",
    "/bundles/storefront/",
    "shopware.storefront",
)

SHOPWARE_STRUCTURAL_MARKERS = (
    "cms-listing-col",
    "product-box",
    "product-detail-buy",
    "product-detail-price",
    "account-login",
)

SUPPORTED_GAME_TERMS: dict[str, tuple[str, ...]] = {
    "One Piece": (
        "one piece tcg",
        "one piece card game",
        "one-piece tcg",
        "one-piece card game",
    ),
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
        "dragon ball fusion world",
        "dragon ball super card game fusion world",
        "dragon ball super card game: fusion world",
        "fusion world tcg",
    ),
    "Riftbound": (
        "riftbound",
    ),
    "Palworld": (
        "palworld tcg",
        "palworld card game",
        "palworld official card game",
    ),
    "Naruto": (
        "naruto tcg",
        "naruto card game",
    ),
    "Cyberpunk TCG": (
        "cyberpunk tcg",
        "cyberpunk trading card game",
        "cyberpunk 2077 tcg",
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

# Strong product-structure terms are used only as a guard for a few abbreviated
# game labels. They keep category navigation links such as just "Pokemon" from
# being mistaken for product pages.
PRODUCT_STRUCTURE_TERMS = (
    "booster",
    "starter deck",
    "structure deck",
    "battle deck",
    "showdown deck",
    "deck",
    "elite trainer box",
    "etb",
    "collection",
    "bundle",
    "display",
    "box",
    "pack",
    "tin",
    "case",
    "promo",
    "sleeves",
    "binder",
    "playmat",
    "play mat",
    "portfolio",
    "single",
)

SEALED_TERMS = (
    "booster box",
    "booster display",
    "display box",
    "booster pack",
    "booster bundle",
    "sleeved booster",
    "elite trainer box",
    " etb",
    "starter deck",
    "structure deck",
    "battle deck",
    "showdown deck",
    "collection box",
    "collection set",
    "premium collection",
    "special collection",
    "double pack",
    "double-pack",
    "blister",
    " tin",
    "case",
)

SINGLE_TERMS = (
    "single card",
    "tcg single",
    "card single",
    " singles",
    "individual card",
    "promo card",
)

ACCESSORY_TERMS = (
    "sleeves",
    "deck box",
    "binder",
    "playmat",
    "play mat",
    "portfolio",
    "toploader",
    "top loader",
    "storage box",
    "card holder",
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

ONE_PIECE_CODE = re.compile(
    r"\b(?:OP|EB|PRB|ST|EX)\d{1,2}-\d{2,4}\b",
    re.IGNORECASE,
)
ONE_PIECE_PROMO = re.compile(r"\bP-\d{1,4}\b", re.IGNORECASE)

PRICE_DOLLAR_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
LIMIT_RE = re.compile(
    r"\blimit\s+(\d{1,3})\s+(?:per\s+(?:customer|person|household)|each)\b",
    re.IGNORECASE,
)
SKU_TEXT_RE = re.compile(
    r"\bSKU\s*:\s*([A-Za-z0-9._\-/]+)",
    re.IGNORECASE,
)

OUT_OF_STOCK_TERMS = (
    "out of stock",
    "sold out",
    "currently unavailable",
    "not available",
    "temporarily unavailable",
    "notify me when available",
)

IN_STOCK_TERMS = (
    "add to cart",
    "add to basket",
)

PREORDER_TERMS = (
    "preorder",
    "pre-order",
    "pre order",
)

BACKORDER_TERMS = (
    "backorder",
    "back-order",
    "back order",
)


# =========================================================
# GENERIC HELPERS
# =========================================================


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = html_lib.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_domain(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path).lower().strip()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host.strip("./")


def canonical_url(base_url: str, value: Any) -> str | None:
    raw = clean_text(value)
    if not raw:
        return None
    absolute = urljoin(base_url.rstrip("/") + "/", raw)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    # Tracking/query parameters are not part of Lotus's product identity.
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def canonical_request_url(base_url: str, value: Any) -> str | None:
    """Canonicalize a public request URL while preserving query parameters."""
    raw = clean_text(value)
    if not raw:
        return None
    absolute = urljoin(base_url.rstrip("/") + "/", raw)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def same_store_host(domain: str, url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host == normalize_domain(domain)


def classify_game(title: str) -> str | None:
    lowered = clean_text(title).lower()
    if not lowered:
        return None

    for game, terms in SUPPORTED_GAME_TERMS.items():
        if any(term in lowered for term in terms):
            return game

    # Product-page fallback for stores that omit "TCG" from a title. Require
    # strong product structure so plain category links never become products.
    structured = any(term in lowered for term in PRODUCT_STRUCTURE_TERMS)
    if not structured:
        return None

    if "pokemon" in lowered or "pokémon" in lowered:
        return "Pokemon"
    if "one piece" in lowered and (
        ONE_PIECE_CODE.search(title)
        or ONE_PIECE_PROMO.search(title)
        or structured
    ):
        return "One Piece"
    if "gundam" in lowered:
        return "Gundam"
    if "fusion world" in lowered and "dragon ball" in lowered:
        return "Dragon Ball Fusion World"
    if "riftbound" in lowered:
        return "Riftbound"
    if "palworld" in lowered:
        return "Palworld"
    if "naruto" in lowered:
        return "Naruto"
    if "cyberpunk" in lowered:
        return "Cyberpunk TCG"
    if "azuki" in lowered:
        return "Azuki TCG"
    if "hellbreak" in lowered:
        return "Hellbreak TCG"

    return None


def classify_product_category(title: str) -> str:
    lowered = f" {clean_text(title).lower()} "
    if any(term in lowered for term in SINGLE_TERMS):
        return "SINGLE"
    if any(term in lowered for term in ACCESSORY_TERMS):
        return "ACCESSORY"
    if any(term in lowered for term in SEALED_TERMS):
        return "SEALED"
    return "UNKNOWN"


def infer_product_type(title: str) -> str:
    lowered = clean_text(title).lower()
    checks = (
        ("booster box", "Booster Box"),
        ("booster display", "Booster Display"),
        ("booster bundle", "Booster Bundle"),
        ("sleeved booster", "Sleeved Booster Pack"),
        ("booster pack", "Booster Pack"),
        ("elite trainer box", "Elite Trainer Box"),
        ("starter deck", "Starter Deck"),
        ("structure deck", "Structure Deck"),
        ("battle deck", "Battle Deck"),
        ("showdown deck", "Showdown Deck"),
        ("premium collection", "Premium Collection"),
        ("special collection", "Special Collection"),
        ("collection", "Collection"),
        ("bundle", "Bundle"),
        ("double pack", "Double Pack"),
        ("tin", "Tin"),
        ("blister", "Blister"),
        ("case", "Case"),
        ("single", "Single Card"),
        ("sleeves", "Sleeves"),
        ("binder", "Binder"),
        ("playmat", "Playmat"),
    )
    for marker, label in checks:
        if marker in lowered:
            return label
    return "TCG Product"


def classify_product_family(title: str) -> str:
    lowered = clean_text(title).lower()
    if any(term in lowered for term in JP_TERMS):
        return "JP"
    if any(term in lowered for term in KR_TERMS):
        return "KR"
    if any(term in lowered for term in CN_TERMS):
        return "CN"
    return "GLOBAL_STANDARD"


def parse_price_from_text(text: str) -> float | None:
    cleaned = clean_text(text)
    if not cleaned:
        return None

    # Prefer an explicitly labelled Shopware/current-store price.
    labelled_patterns = (
        r"Our\s+Price\s*:\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"Sale\s+Price\s*:\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"Current\s+Price\s*:\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    )
    for pattern in labelled_patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1).replace(",", ""))
                return value if value > 0 else None
            except (TypeError, ValueError):
                pass

    values: list[float] = []
    for match in PRICE_DOLLAR_RE.finditer(cleaned):
        try:
            value = float(match.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)

    if not values:
        return None

    # Shopware sale cards commonly display current price + crossed-out MSRP.
    # The current price is the lower positive amount.
    return min(values)


def parse_purchase_limit(text: str) -> int | None:
    match = LIMIT_RE.search(clean_text(text))
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 100 else None


def availability_from_text(
    text: str,
    *,
    preorder_context: bool = False,
) -> tuple[bool, bool, str, str]:
    lowered = clean_text(text).lower()

    if any(term in lowered for term in BACKORDER_TERMS):
        return False, True, "BACKORDER", "SHOPWARE_PUBLIC_BACKORDER_TEXT"

    if any(term in lowered for term in OUT_OF_STOCK_TERMS):
        return False, True, "OUT_OF_STOCK", "SHOPWARE_PUBLIC_STOCK_TEXT"

    preorder = preorder_context or any(
        term in lowered for term in PREORDER_TERMS
    )

    if any(term in lowered for term in IN_STOCK_TERMS):
        if preorder:
            return True, True, "PREORDER", "SHOPWARE_PUBLIC_PREORDER_BUY_BUTTON"
        return True, True, "IN_STOCK", "SHOPWARE_PUBLIC_BUY_BUTTON"

    if preorder:
        # A public preorder label without a purchase control confirms lifecycle
        # state but not necessarily current orderability. Keep availability
        # unknown rather than assuming it can be purchased.
        return False, False, "UNKNOWN", "SHOPWARE_PREORDER_LABEL_ONLY"

    return False, False, "UNKNOWN", "UNKNOWN"


def availability_from_schema(value: Any) -> tuple[bool, bool, str, str] | None:
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if not lowered:
        return None

    if lowered.endswith("/instock") or lowered.endswith("instock"):
        return True, True, "IN_STOCK", "SHOPWARE_JSONLD_AVAILABILITY"
    if lowered.endswith("/outofstock") or lowered.endswith("outofstock"):
        return False, True, "OUT_OF_STOCK", "SHOPWARE_JSONLD_AVAILABILITY"
    if lowered.endswith("/preorder") or lowered.endswith("preorder"):
        return True, True, "PREORDER", "SHOPWARE_JSONLD_AVAILABILITY"
    if lowered.endswith("/backorder") or lowered.endswith("backorder"):
        return False, True, "BACKORDER", "SHOPWARE_JSONLD_AVAILABILITY"
    if lowered.endswith("/discontinued") or lowered.endswith("discontinued"):
        return False, True, "OUT_OF_STOCK", "SHOPWARE_JSONLD_AVAILABILITY"
    return None


def find_jsonld_product(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        raw_type = value.get("@type")
        types: list[str] = []
        if isinstance(raw_type, list):
            types = [str(item).lower() for item in raw_type]
        elif raw_type is not None:
            types = [str(raw_type).lower()]

        if "product" in types:
            return value

        graph = value.get("@graph")
        if isinstance(graph, list):
            for child in graph:
                found = find_jsonld_product(child)
                if found:
                    return found

        for child in value.values():
            if isinstance(child, (dict, list)):
                found = find_jsonld_product(child)
                if found:
                    return found

    elif isinstance(value, list):
        for child in value:
            found = find_jsonld_product(child)
            if found:
                return found

    return None


def parse_jsonld_product(html: str) -> dict[str, Any] | None:
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html or "",
        re.IGNORECASE | re.DOTALL,
    ):
        raw = html_lib.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        found = find_jsonld_product(payload)
        if found:
            return found
    return None


def schema_offer(product: dict[str, Any]) -> dict[str, Any]:
    offers = product.get("offers") if isinstance(product, dict) else None
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for item in offers:
            if isinstance(item, dict):
                return item
    return {}


def schema_price(product: dict[str, Any]) -> tuple[float | None, str | None]:
    offer = schema_offer(product)
    candidates = (
        offer.get("price"),
        offer.get("lowPrice"),
        product.get("price"),
    )
    for candidate in candidates:
        price = normalize_price(candidate)
        if price is not None and price > 0:
            currency = clean_text(
                offer.get("priceCurrency")
                or product.get("priceCurrency")
            ).upper() or None
            return float(price), currency
    return None, None


def schema_image(product: dict[str, Any]) -> str | None:
    image = product.get("image") if isinstance(product, dict) else None
    if isinstance(image, str):
        return clean_text(image) or None
    if isinstance(image, list):
        for item in image:
            if isinstance(item, str) and clean_text(item):
                return clean_text(item)
            if isinstance(item, dict):
                url = clean_text(item.get("url") or item.get("contentUrl"))
                if url:
                    return url
    if isinstance(image, dict):
        url = clean_text(image.get("url") or image.get("contentUrl"))
        if url:
            return url
    return None


# =========================================================
# SHOPWARE LISTING CARD PARSER
# =========================================================


class ShopwareListingParser(HTMLParser):
    """Extract product cards from ordinary Shopware 6 server-rendered HTML."""

    def __init__(self, *, base_url: str, domain: str, preorder_page: bool = False):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.domain = domain
        self.preorder_page = preorder_page
        self.cards: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._card_depth = 0
        self._anchor_depth = 0
        self._anchor_text: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_class = ""

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {
            str(key).lower(): str(value or "")
            for key, value in attrs
        }

    def _begin_card(self, attrs: dict[str, str]) -> None:
        self._current = {
            "url": None,
            "title": None,
            "image_url": None,
            "text_parts": [],
            "product_id": (
                attrs.get("data-product-id")
                or attrs.get("data-product-number")
                or attrs.get("data-product")
                or None
            ),
            "preorder_page": self.preorder_page,
        }
        self._card_depth = 1

    def handle_starttag(self, tag: str, attrs_raw: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs = self._attrs(attrs_raw)
        classes = attrs.get("class", "").lower()

        if self._current is None:
            if tag in {"div", "article", "li"} and "product-box" in classes:
                self._begin_card(attrs)
                return
        else:
            if tag in {"div", "article", "li"}:
                self._card_depth += 1

            product_id = (
                attrs.get("data-product-id")
                or attrs.get("data-product-number")
            )
            if product_id and not self._current.get("product_id"):
                self._current["product_id"] = product_id

            if tag == "img" and not self._current.get("image_url"):
                image = (
                    attrs.get("src")
                    or attrs.get("data-src")
                    or attrs.get("data-srcset")
                    or attrs.get("srcset")
                )
                if image:
                    image = image.split(",", 1)[0].strip().split(" ", 1)[0]
                    self._current["image_url"] = canonical_url(self.base_url, image)

            if tag in {"button", "input"}:
                value = clean_text(
                    attrs.get("value")
                    or attrs.get("title")
                    or attrs.get("aria-label")
                )
                if value:
                    self._current["text_parts"].append(value)

        if tag == "a":
            self._anchor_depth += 1
            self._anchor_href = attrs.get("href")
            self._anchor_class = classes
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "a" and self._anchor_depth:
            text = clean_text(" ".join(self._anchor_text))
            href = canonical_url(self.base_url, self._anchor_href)

            if self._current is not None and href and same_store_host(self.domain, href):
                if (
                    "product-name" in self._anchor_class
                    or "product-image" in self._anchor_class
                    or "product-box" in self._anchor_class
                ):
                    if not self._current.get("url"):
                        self._current["url"] = href
                    if text and not self._current.get("title"):
                        self._current["title"] = text

                # Some custom Shopware themes remove the default product-name
                # class. A supported-game product title is still safe evidence.
                if text and classify_game(text):
                    if not self._current.get("url"):
                        self._current["url"] = href
                    if not self._current.get("title"):
                        self._current["title"] = text

            self._anchor_depth = max(self._anchor_depth - 1, 0)
            self._anchor_href = None
            self._anchor_class = ""
            self._anchor_text = []

        if self._current is not None and tag in {"div", "article", "li"}:
            self._card_depth -= 1
            if self._card_depth <= 0:
                self._finish_card()

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return
        if self._anchor_depth:
            self._anchor_text.append(text)
        if self._current is not None:
            self._current["text_parts"].append(text)

    def _finish_card(self) -> None:
        if self._current is None:
            return

        card = self._current
        self._current = None
        self._card_depth = 0

        text = clean_text(" ".join(card.pop("text_parts", [])))
        title = clean_text(card.get("title"))
        url = clean_text(card.get("url"))

        if title and url and classify_game(title):
            card["title"] = title
            card["url"] = url
            card["text"] = text
            self.cards.append(card)



# =========================================================
# SHOPWARE PRODUCT-SITEMAP ANCHOR PARSER
# Step 6J-3F5
# =========================================================


class ShopwareSitemapAnchorParser(HTMLParser):
    """
    Tolerant anchor extractor for public Shopware sitemap pages.

    The earlier F3/F4 fallback used one paired-anchor regex. That is too
    brittle for customized/minified HTML because attributes may be reordered,
    whitespace may appear around '=', and the product label may live in a
    nested span/image attribute instead of direct anchor text.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._text_parts: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {
            str(key).lower(): str(value or "")
            for key, value in attrs
        }

    def _finish_anchor(self) -> None:
        if self._current is None:
            return

        href = clean_text(self._current.get("href"))
        visible = clean_text(" ".join(self._text_parts))
        title_attr = clean_text(self._current.get("title"))
        aria_label = clean_text(self._current.get("aria_label"))
        image_alt = clean_text(self._current.get("image_alt"))

        if href:
            self.anchors.append({
                "href": href,
                "text": visible,
                "title": title_attr,
                "aria_label": aria_label,
                "image_alt": image_alt,
            })

        self._current = None
        self._text_parts = []

    def handle_starttag(
        self,
        tag: str,
        attrs_raw: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        attrs = self._attrs(attrs_raw)

        if tag == "a":
            # Malformed markup occasionally begins a new anchor without
            # closing the previous one. Preserve what we already captured.
            if self._current is not None:
                self._finish_anchor()

            self._current = {
                "href": attrs.get("href"),
                "title": attrs.get("title"),
                "aria_label": attrs.get("aria-label"),
                "image_alt": "",
            }
            self._text_parts = []
            return

        if self._current is not None and tag == "img":
            alt = clean_text(attrs.get("alt"))
            if alt and not clean_text(self._current.get("image_alt")):
                self._current["image_alt"] = alt

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = clean_text(data)
        if text:
            self._text_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current is not None:
            self._finish_anchor()

    def close(self) -> None:
        super().close()
        if self._current is not None:
            self._finish_anchor()


def sitemap_slug_title(url: str) -> str:
    """Derive a readable product title from a Miniature Market-style URL."""
    try:
        path = unquote(urlparse(url).path or "").strip("/")
    except Exception:
        return ""

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return ""

    # Miniature Market product URLs normally end in a product number such as
    # /GUNDAM-Card-Game-Clan-Unity-ST06-Starter-Deck/BAN2810959.
    slug = segments[-1]
    if len(segments) >= 2 and re.fullmatch(
        r"(?=.*\d)[A-Za-z0-9][A-Za-z0-9._-]{3,}",
        segments[-1],
    ):
        slug = segments[-2]

    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug)
    return clean_text(slug)


def sitemap_href_looks_productish(url: str) -> bool:
    """Conservative product-URL shape check for slug-based classification."""
    try:
        path = unquote(urlparse(url).path or "").strip("/")
    except Exception:
        return False

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return False

    product_number = segments[-1]
    if not re.fullmatch(
        r"(?=.*\d)[A-Za-z0-9][A-Za-z0-9._-]{3,}",
        product_number,
    ):
        return False

    return True

# =========================================================
# SHOPWARE ADAPTER
# =========================================================


@retailer_adapter("shopware")
class ShopwareAdapter(RetailerAdapter):
    platform = "shopware"

    def __init__(
        self,
        *,
        domain,
        region="US",
        store_name=None,
        request_delay=DEFAULT_REQUEST_DELAY,
        max_listing_pages=MAX_LISTING_PAGES,
        max_product_pages=MAX_PRODUCT_PAGES,
    ):
        super().__init__(
            domain=domain,
            region=region,
            store_name=store_name,
        )
        self.domain = normalize_domain(self.domain)
        self.base_url = (
            "https://www.miniaturemarket.com"
            if self.domain == "miniaturemarket.com"
            else f"https://{self.domain}"
        )
        self.request_delay = max(float(request_delay), 0.25)
        self.max_listing_pages = max(1, min(int(max_listing_pages), MAX_LISTING_PAGES))
        self.max_product_pages = max(1, min(int(max_product_pages), MAX_PRODUCT_PAGES))
        self.known_product_urls: set[str] = set()
        self.diagnostics: dict[str, Any] = {}
        self._reset_diagnostics()

    def _reset_diagnostics(self) -> None:
        self.diagnostics = {
            "pages_checked": 0,
            "pages_successful": 0,
            "pages_failed": 0,
            "body_too_large": 0,
            "largest_body_bytes": 0,
            "listing_roots_found": 0,
            "fallback_anchors_seen": 0,
            "fallback_supported_anchors": 0,
            "rejected_products": 0,
            "listing_pages_checked": 0,
            "listing_pages_successful": 0,
            "listing_cards_seen": 0,
            "listing_fragment_urls_found": 0,
            "listing_fragment_pages_checked": 0,
            "listing_fragment_pages_successful": 0,
            "listing_fragment_cards_seen": 0,
            "supported_listing_products": 0,
            "product_urls_discovered": 0,
            "sitemap_pages_checked": 0,
            "sitemap_pages_successful": 0,
            "sitemap_anchors_seen": 0,
            "sitemap_href_candidates": 0,
            "sitemap_title_game_hits": 0,
            "sitemap_slug_game_hits": 0,
            "sitemap_parser_errors": 0,
            "sitemap_supported_products": 0,
            "sitemap_product_pages_requested": 0,
            "sitemap_product_pages_successful": 0,
            "sitemap_body_game_pages": 0,
            "xml_sitemap_docs_checked": 0,
            "xml_sitemap_docs_successful": 0,
            "xml_sitemap_locs_seen": 0,
            "xml_sitemap_child_docs": 0,
            "xml_sitemap_product_candidates": 0,
            "xml_sitemap_tcg_hits": 0,
            "xml_sitemap_parse_errors": 0,
            "product_pages_successful": 0,
            "products_accepted": 0,
            "products_rejected": 0,
            "normalized_products": 0,
            "unknown_availability": 0,
            "missing_prices": 0,
            "in_stock_products": 0,
            "out_of_stock_products": 0,
            "preorders": 0,
            "backorders": 0,
            "http_429": 0,
            "http_blocked": 0,
            "browser_profile_requests": 0,
            "browser_profile_pages_successful": 0,
            "listing_pages_with_game_text": 0,
            "listing_pages_with_add_to_cart": 0,
            "loose_anchor_candidates": 0,
            "loose_anchor_products": 0,
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

    def get_diagnostics(self) -> dict[str, Any]:
        return dict(self.diagnostics)

    def set_known_product_urls(self, urls: list[str] | tuple[str, ...] | set[str]) -> None:
        cleaned: set[str] = set()
        for value in urls or []:
            url = canonical_url(self.base_url, value)
            if url:
                cleaned.add(url)
        self.known_product_urls = cleaned

    async def platform_probe(self) -> dict[str, Any]:
        """
        Lightweight public Shopware storefront fingerprint using the same
        HTTP behavior as the production adapter. This avoids detector drift.
        No authentication, cart mutation, or checkout actions are performed.
        """
        headers = dict(BROWSER_NAV_HEADERS)
        connector = aiohttp.TCPConnector(limit=3, limit_per_host=2)
        notes: list[str] = []

        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            for path in SHOPWARE_PLATFORM_PROBE_PATHS:
                url = f"{self.base_url}{path}"
                html, response = await self._fetch_text(session, url)
                if response is None:
                    notes.append(f"{path}:NO_RESPONSE")
                    continue
                if not html:
                    notes.append(f"{path}:HTTP_{response.status}:NO_HTML")
                    continue

                lowered = html.lower()
                strong = [m for m in SHOPWARE_STRONG_MARKERS if m in lowered]
                structural = [m for m in SHOPWARE_STRUCTURAL_MARKERS if m in lowered]

                if strong:
                    return {
                        "detected": True,
                        "path": path,
                        "status": int(response.status),
                        "strength": "STRONG",
                        "markers": strong[:4],
                    }

                if len(structural) >= 2:
                    return {
                        "detected": True,
                        "path": path,
                        "status": int(response.status),
                        "strength": "STRUCTURAL",
                        "markers": structural[:5],
                    }

                notes.append(
                    f"{path}:HTTP_{response.status}:BYTES_{len(html.encode('utf-8', errors='ignore'))}"
                )
                await asyncio.sleep(self.request_delay)

        return {
            "detected": False,
            "reason": self.diagnostics.get("last_error") or "NO_SHOPWARE_MARKERS",
            "notes": notes[:6],
        }

    async def _fetch_text(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        request_headers: dict[str, str] | None = None,
    ) -> tuple[str | None, aiohttp.ClientResponse | None]:
        self.diagnostics["pages_checked"] += 1
        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)

        effective_user_agent = (
            (request_headers or {}).get("User-Agent")
            or session.headers.get("User-Agent")
            or ""
        )
        if effective_user_agent == USER_AGENT:
            self.diagnostics["browser_profile_requests"] += 1

        try:
            async with session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                headers=request_headers,
            ) as response:
                self.diagnostics["last_http_status"] = int(response.status)

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

                # Shopware category pages can be several megabytes because
                # storefront filters, plugin configuration, and product cards
                # are server-rendered together.  Step 6J-3F used a 4 MB cap,
                # which was too small for Miniature Market's TCG catalog and
                # caused perfectly valid HTTP 200 pages to be discarded before
                # product links could be parsed.  Keep a bounded cap, but make
                # it large enough for real Shopware catalog pages.
                raw = await response.content.read(MAX_BODY_BYTES + 1)
                body_bytes = len(raw)
                self.diagnostics["largest_body_bytes"] = max(
                    int(self.diagnostics.get("largest_body_bytes", 0) or 0),
                    body_bytes,
                )
                if body_bytes > MAX_BODY_BYTES:
                    self.diagnostics["body_too_large"] += 1
                    self.diagnostics["pages_failed"] += 1
                    self.diagnostics["last_error"] = (
                        f"HTML_BODY_TOO_LARGE:{body_bytes}>{MAX_BODY_BYTES}"
                    )
                    return None, response

                charset = response.charset or "utf-8"
                try:
                    text = raw.decode(charset, errors="replace")
                except (LookupError, UnicodeError):
                    text = raw.decode("utf-8", errors="replace")

                self.diagnostics["pages_successful"] += 1
                if effective_user_agent == USER_AGENT:
                    self.diagnostics["browser_profile_pages_successful"] += 1
                return text, response

        except asyncio.CancelledError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            self.diagnostics["pages_failed"] += 1
            self.diagnostics["last_error"] = f"{type(error).__name__}:{error}"
            return None, None

    def _extract_root_links(self, html: str) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        for match in re.finditer(
            r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            html or "",
            re.IGNORECASE | re.DOTALL,
        ):
            href = canonical_url(self.base_url, match.group(1))
            label = clean_text(match.group(2)).lower()
            href_lower = (href or "").lower()
            if not href or not same_store_host(self.domain, href):
                continue

            if any(
                marker in f"{label} {href_lower}"
                for marker in (
                    "trading card",
                    "trading-card",
                    "tcg",
                    "pokemon",
                    "one-piece",
                    "one piece",
                    "gundam",
                    "riftbound",
                )
            ):
                if href not in seen:
                    seen.add(href)
                    candidates.append(href)

        return candidates

    async def _discover_listing_roots(self, session: aiohttp.ClientSession) -> list[tuple[str, bool]]:
        roots: list[tuple[str, bool]] = []
        seen: set[str] = set()

        def add(url: str | None, preorder: bool = False) -> None:
            if not url:
                return
            canonical = canonical_url(self.base_url, url)
            if not canonical or not same_store_host(self.domain, canonical):
                return
            key = canonical.lower()
            if key in seen:
                return
            seen.add(key)
            roots.append((canonical, preorder))

        # Store-specific high-value roots first.  This is intentionally
        # bounded and public; no private Shopware API is used.
        if self.domain == "miniaturemarket.com":
            for path in MINIATURE_MARKET_PRIORITY_PATHS:
                add(
                    f"{self.base_url}{path}",
                    "preorder" in path.lower(),
                )

        for path in DEFAULT_LISTING_PATHS:
            add(f"{self.base_url}{path}", False)
        for path in DEFAULT_PREORDER_PATHS:
            add(f"{self.base_url}{path}", True)

        # Public homepage/category sitemap discovery makes the adapter useful
        # beyond Miniature Market without requiring any private Store API key.
        for path in CATEGORY_DISCOVERY_PATHS:
            html, response = await self._fetch_text(session, f"{self.base_url}{path}")
            if not html or response is None or response.status >= 400:
                continue
            for href in self._extract_root_links(html):
                lowered = href.lower()
                add(
                    href,
                    any(marker in lowered for marker in PREORDER_TERMS),
                )
            await asyncio.sleep(self.request_delay)

        self.diagnostics["listing_roots_found"] = len(roots)
        return roots

    @staticmethod
    def _page_url(root: str, page: int) -> str:
        if page <= 1:
            return root
        separator = "&" if "?" in root else "?"
        return f"{root}{separator}p={page}"

    def _extract_listing_fragment_urls(self, html: str) -> list[str]:
        """
        Discover public Shopware listing-fragment endpoints embedded in a
        category shell. Some Shopware storefronts return filter/navigation
        chrome in the category response and load the actual product grid from
        /widgets/cms/navigation/... via an XHR request.
        """
        decoded = html_lib.unescape(html or "")
        candidates: list[str] = []
        seen: set[str] = set()

        raw_values: list[str] = []

        # Explicit data-url / data-listing-url style attributes.
        for match in re.finditer(
            r"\b(?:data-url|data-listing-url|data-load-url)\s*=\s*[\"']([^\"']+)[\"']",
            decoded,
            re.IGNORECASE,
        ):
            raw_values.append(match.group(1))

        # JSON embedded in data-listing-options or script configuration.
        for match in re.finditer(
            r"[\"'](?:dataUrl|data-url|listingUrl|listing-url)[\"']\s*:\s*[\"']([^\"']+)[\"']",
            decoded,
            re.IGNORECASE,
        ):
            raw_values.append(match.group(1))

        # Last-resort direct Shopware widget path discovery.
        for match in re.finditer(
            r"(?:https?://[^\"'<>\s]+)?/widgets/cms/navigation/[^\"'<>\s\\]+",
            decoded,
            re.IGNORECASE,
        ):
            raw_values.append(match.group(0))

        for raw in raw_values:
            raw = raw.replace("\\/", "/")
            request_url = canonical_request_url(self.base_url, raw)
            if not request_url or not same_store_host(self.domain, request_url):
                continue
            if "/widgets/cms/navigation/" not in request_url.lower():
                continue
            key = request_url.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(request_url)
            if len(candidates) >= MAX_FRAGMENT_URLS_PER_ROOT:
                break

        return candidates

    def _extract_supported_sitemap_anchors(self, html: str) -> list[dict[str, Any]]:
        """
        Extract supported TCG product links from a public Shopware product
        sitemap using a tolerant HTML parser plus a conservative href/slug
        fallback.

        F3/F4 proved the sitemap route itself is reachable on Railway, but a
        paired-anchor regex returned zero TCG links. F5 therefore treats the
        href as primary evidence and can classify from a product URL slug when
        the visible anchor label is nested, empty, or customized.
        """
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        anchors: list[dict[str, Any]] = []

        parser = ShopwareSitemapAnchorParser()
        try:
            parser.feed(html or "")
            parser.close()
            anchors.extend(parser.anchors)
        except Exception:
            self.diagnostics["sitemap_parser_errors"] += 1

        # Malformed/minified fallback: extract href values without requiring a
        # matching </a>. This also tolerates whitespace around '='.
        parser_hrefs = {
            clean_text(item.get("href"))
            for item in anchors
            if clean_text(item.get("href"))
        }
        for match in re.finditer(
            r"\bhref\s*=\s*(?:[\"']([^\"']+)[\"']|([^\s>]+))",
            html or "",
            re.IGNORECASE,
        ):
            href = clean_text(match.group(1) or match.group(2))
            if not href or href in parser_hrefs:
                continue
            parser_hrefs.add(href)
            anchors.append({
                "href": href,
                "text": "",
                "title": "",
                "aria_label": "",
                "image_alt": "",
            })

        for anchor in anchors:
            self.diagnostics["sitemap_anchors_seen"] += 1

            raw_href = clean_text(anchor.get("href"))
            url = canonical_url(self.base_url, raw_href)
            if not url or not same_store_host(self.domain, url):
                continue

            path = urlparse(url).path.rstrip("/").lower()
            if path in {
                "/product-sitemap",
                "/category-sitemap",
                "/sitemap",
            }:
                continue

            self.diagnostics["sitemap_href_candidates"] += 1

            label_candidates = (
                clean_text(anchor.get("text")),
                clean_text(anchor.get("title")),
                clean_text(anchor.get("aria_label")),
                clean_text(anchor.get("image_alt")),
            )

            title = ""
            game = None
            for candidate in label_candidates:
                if not candidate:
                    continue
                candidate_game = classify_game(candidate)
                if candidate_game:
                    title = candidate
                    game = candidate_game
                    self.diagnostics["sitemap_title_game_hits"] += 1
                    break

            # If the visible label is absent or too generic, Miniature Market's
            # canonical product URL itself contains the product title followed
            # by a SKU/product number. Only use this fallback when the URL has
            # that conservative product shape.
            if game is None and sitemap_href_looks_productish(url):
                slug_title = sitemap_slug_title(url)
                slug_game = classify_game(slug_title)
                if slug_game:
                    title = slug_title
                    game = slug_game
                    self.diagnostics["sitemap_slug_game_hits"] += 1

            if game is None or not title:
                continue

            if url in seen:
                continue

            seen.add(url)
            entries.append({
                "title": title,
                "url": url,
                "text": title,
                "image_url": None,
                "product_id": None,
                "preorder_page": any(
                    term in f"{title} {url}".lower()
                    for term in PREORDER_TERMS
                ),
                "source": "PRODUCT_SITEMAP",
            })

        return entries

    @staticmethod
    def _extract_xml_locs(document: str) -> list[str]:
        """
        Extract <loc> values from an XML sitemap or sitemap index.

        Namespace prefixes are tolerated because some Shopware/CDN sitemap
        generators emit namespaced tags. Regex is intentionally used here
        instead of a strict XML parser so a harmless malformed entity does not
        discard an otherwise usable public sitemap document.
        """
        values: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(
            r"<(?:[A-Za-z0-9_-]+:)?loc\b[^>]*>(.*?)</(?:[A-Za-z0-9_-]+:)?loc\s*>",
            document or "",
            re.IGNORECASE | re.DOTALL,
        ):
            value = clean_text(match.group(1))
            if not value:
                continue
            value = html_lib.unescape(value).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        return values

    @staticmethod
    def _looks_like_sitemap_document(url: str) -> bool:
        lowered = str(url or "").lower()
        path = urlparse(lowered).path
        basename = path.rsplit("/", 1)[-1]
        return (
            basename.endswith(".xml")
            or basename.endswith(".xml.gz")
            or "sitemap" in basename
        )

    def _xml_url_to_supported_entry(self, raw_url: str) -> dict[str, Any] | None:
        """Convert a public XML-sitemap URL into a supported TCG candidate."""
        url = canonical_url(self.base_url, raw_url)
        if not url or not same_store_host(self.domain, url):
            return None

        # Do not treat navigation/sitemap routes as products.
        path = urlparse(url).path.rstrip("/").lower()
        if not path or path in {
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/product-sitemap",
            "/category-sitemap",
            "/sitemap",
        }:
            return None

        # Miniature Market embeds the useful product title in the canonical URL
        # slug. Other Shopware stores frequently do the same. The classifier
        # still requires a supported game plus product structure, so unrelated
        # Gundam model kits or generic Pokemon category roots are rejected.
        title = sitemap_slug_title(url)
        game = classify_game(title)

        if game is None:
            readable_path = clean_text(
                re.sub(r"[-_/]+", " ", unquote(urlparse(url).path))
            )
            game = classify_game(readable_path)
            if game:
                title = readable_path

        if game is None or not title:
            return None

        return {
            "title": title,
            "url": url,
            "text": title,
            "image_url": None,
            "product_id": None,
            "preorder_page": any(
                term in f"{title} {url}".lower()
                for term in PREORDER_TERMS
            ),
            "source": "XML_SITEMAP",
        }

    async def _discover_xml_sitemap_entries(
        self,
        session: aiohttp.ClientSession,
    ) -> list[dict[str, Any]]:
        """
        Bounded standards-based XML sitemap discovery.

        F5 proved Miniature Market's HTML product-sitemap endpoint returns a
        much thinner response to Railway than to normal web crawlers. The site
        also publicly exposes /sitemap.xml, so F6 prefers the standard XML
        sitemap graph and follows only same-host public sitemap documents.
        """
        discovered: dict[str, dict[str, Any]] = {}
        queue: list[str] = [
            f"{self.base_url}{path}"
            for path in XML_SITEMAP_PATHS
        ]
        queued = {item.lower() for item in queue}
        visited: set[str] = set()

        while queue and len(visited) < MAX_XML_SITEMAP_DOCUMENTS:
            sitemap_url = queue.pop(0)
            key = sitemap_url.lower()
            if key in visited:
                continue
            visited.add(key)

            self.diagnostics["xml_sitemap_docs_checked"] += 1
            document, response = await self._fetch_text(session, sitemap_url)
            if not document or response is None or response.status >= 400:
                continue

            self.diagnostics["xml_sitemap_docs_successful"] += 1
            locs = self._extract_xml_locs(document)
            if not locs:
                self.diagnostics["xml_sitemap_parse_errors"] += 1
                await asyncio.sleep(self.request_delay)
                continue

            self.diagnostics["xml_sitemap_locs_seen"] += len(locs)

            # Put likely product sitemap documents first so the bounded crawl
            # does not spend its entire budget on image/category/news sitemaps.
            child_docs: list[str] = []
            product_urls: list[str] = []
            for raw_loc in locs:
                request_url = canonical_request_url(self.base_url, raw_loc)
                if not request_url or not same_store_host(self.domain, request_url):
                    continue
                if self._looks_like_sitemap_document(request_url):
                    child_docs.append(request_url)
                else:
                    product_urls.append(request_url)

            child_docs.sort(
                key=lambda value: (
                    0 if "product" in value.lower() else 1,
                    value.lower(),
                )
            )

            for child in child_docs:
                child_key = child.lower()
                if child_key in visited or child_key in queued:
                    continue
                if len(visited) + len(queue) >= MAX_XML_SITEMAP_DOCUMENTS:
                    break
                queued.add(child_key)
                queue.append(child)
                self.diagnostics["xml_sitemap_child_docs"] += 1

            for raw_product_url in product_urls:
                self.diagnostics["xml_sitemap_product_candidates"] += 1
                entry = self._xml_url_to_supported_entry(raw_product_url)
                if not entry:
                    continue
                product_url = canonical_url(self.base_url, entry.get("url"))
                if not product_url or product_url in discovered:
                    continue
                discovered[product_url] = entry
                self.diagnostics["xml_sitemap_tcg_hits"] += 1
                if len(discovered) >= XML_SITEMAP_TARGET:
                    break

            if len(discovered) >= XML_SITEMAP_TARGET:
                break

            await asyncio.sleep(self.request_delay)

        return list(discovered.values())

    async def _discover_product_sitemap_entries(
        self,
        session: aiohttp.ClientSession,
    ) -> list[dict[str, Any]]:
        """Bounded public product-sitemap fallback for Shopware stores."""
        discovered: dict[str, dict[str, Any]] = {}

        for page in range(1, MAX_PRODUCT_SITEMAP_PAGES + 1):
            separator = "&" if "?" in PRODUCT_SITEMAP_PATH else "?"
            url = (
                f"{self.base_url}{PRODUCT_SITEMAP_PATH}"
                f"{separator}limit=50&p={page}"
            )
            self.diagnostics["sitemap_pages_checked"] += 1
            html, response = await self._fetch_text(session, url)

            if not html or response is None or response.status >= 400:
                if page == 1:
                    break
                continue

            self.diagnostics["sitemap_pages_successful"] += 1

            # F6 diagnostic: distinguish "parser missed a product" from
            # "Railway received a sitemap shell with no supported-game text".
            lowered_html = clean_text(html).lower()
            if any(
                term in lowered_html
                for terms in SUPPORTED_GAME_TERMS.values()
                for term in terms
            ):
                self.diagnostics["sitemap_body_game_pages"] += 1

            entries = self._extract_supported_sitemap_anchors(html)

            page_new = 0
            for entry in entries:
                product_url = canonical_url(self.base_url, entry.get("url"))
                if not product_url or product_url in discovered:
                    continue
                discovered[product_url] = entry
                page_new += 1

            if len(discovered) >= PRODUCT_SITEMAP_TARGET:
                break

            # A normal sitemap page contains 50 product links. If the route
            # stops returning any product-ish anchors for several pages, the
            # later pages are unlikely to help. Keep the loop bounded anyway.
            await asyncio.sleep(self.request_delay)

        self.diagnostics["sitemap_supported_products"] = len(discovered)
        return list(discovered.values())

    async def _enrich_sitemap_entries(
        self,
        session: aiohttp.ClientSession,
        entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Fetch a bounded set of public product pages so onboarding receives
        real price/availability data instead of merely sitemap URLs.
        """
        selected = entries[:MAX_SITEMAP_PRODUCT_PAGE_FETCHES]
        self.diagnostics["sitemap_product_pages_requested"] = len(selected)
        if not selected:
            return []

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PRODUCT_REQUESTS)

        async def fetch_one(entry: dict[str, Any]) -> dict[str, Any] | None:
            url = canonical_url(self.base_url, entry.get("url"))
            if not url:
                return None
            async with semaphore:
                html, response = await self._fetch_text(session, url)
                await asyncio.sleep(self.request_delay)
            if not html or response is None or response.status >= 400:
                return None
            raw = self._product_page_to_raw(url, html)
            if not raw:
                return None
            if not clean_text(raw.get("title")):
                raw["title"] = clean_text(entry.get("title"))
            raw["preorder_page"] = bool(entry.get("preorder_page"))
            raw["source"] = "PRODUCT_SITEMAP_PRODUCT_PAGE"
            if not classify_game(clean_text(raw.get("title"))):
                return None
            return raw

        results = await asyncio.gather(
            *(fetch_one(entry) for entry in selected),
            return_exceptions=False,
        )
        enriched = [item for item in results if isinstance(item, dict)]
        self.diagnostics["sitemap_product_pages_successful"] = len(enriched)

        # If product-page fetching is partially filtered, preserve the sitemap
        # discoveries that could not be enriched. Their availability remains
        # UNKNOWN, which Lotus treats conservatively and never as sold out.
        enriched_urls = {
            canonical_url(self.base_url, item.get("url"))
            for item in enriched
            if item.get("url")
        }
        for entry in selected:
            url = canonical_url(self.base_url, entry.get("url"))
            if url and url not in enriched_urls:
                enriched.append(dict(entry))

        return enriched

    def _fallback_supported_anchors(
        self,
        html: str,
        *,
        preorder_page: bool,
    ) -> list[dict[str, Any]]:
        """
        Theme-independent product-link fallback.

        Some Shopware themes heavily customize the normal ``product-box``
        markup.  Miniature Market is one such storefront.  We therefore scan
        ordinary same-host anchors and accept only anchors whose visible text,
        title/aria-label, or nested image alt text classifies as a supported
        TCG product.  The strict game classifier prevents navigation/category
        links from being accepted as products.
        """
        products: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        anchor_re = re.compile(
            r"<a\b([^>]*)href=[\"']([^\"']+)[\"']([^>]*)>(.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )

        def attr_value(attrs: str, name: str) -> str:
            match = re.search(
                rf"\b{re.escape(name)}\s*=\s*[\"']([^\"']+)[\"']",
                attrs or "",
                re.IGNORECASE,
            )
            return clean_text(match.group(1)) if match else ""

        for match in anchor_re.finditer(html or ""):
            self.diagnostics["fallback_anchors_seen"] += 1

            attrs = f"{match.group(1)} {match.group(3)}"
            inner = match.group(4) or ""
            visible = clean_text(inner)
            title_attr = attr_value(attrs, "title")
            aria_label = attr_value(attrs, "aria-label")

            img_alt = ""
            img_match = re.search(
                r"<img\b[^>]*\balt=[\"']([^\"']+)[\"']",
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            if img_match:
                img_alt = clean_text(img_match.group(1))

            candidates = [visible, title_attr, aria_label, img_alt]
            title = next(
                (candidate for candidate in candidates if classify_game(candidate)),
                "",
            )
            if not title:
                continue

            url = canonical_url(self.base_url, match.group(2))
            if not url or not same_store_host(self.domain, url):
                continue
            if url in seen_urls:
                continue

            # Reject obvious category/navigation roots even if a theme gives
            # them a product-like label.
            path = urlparse(url).path.rstrip("/").lower()
            if path in {
                "/trading-card-games",
                "/trading-card-games.html",
                "/tcg",
                "/tcg.html",
                "/cards",
                "/cards.html",
            }:
                continue

            start = max(0, match.start() - 1800)
            end = min(len(html), match.end() + 2800)
            context = clean_text(html[start:end])

            image_url = None
            img_src_match = re.search(
                r"<img\b[^>]*(?:src|data-src)=[\"']([^\"']+)[\"']",
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            if img_src_match:
                image_url = canonical_url(self.base_url, img_src_match.group(1))

            seen_urls.add(url)
            self.diagnostics["fallback_supported_anchors"] += 1
            products.append({
                "title": title,
                "url": url,
                "text": context,
                "image_url": image_url,
                "product_id": None,
                "preorder_page": preorder_page,
            })

        # F7 secondary parser: HTMLParser is more tolerant than the regex path
        # above when a customized Shopware theme reorders attributes, nests the
        # product label deeply, or emits unusual whitespace.  This path is used
        # only for same-host anchors whose label itself identifies a supported
        # game, so navigation/category links remain excluded.
        if not products:
            parser = ShopwareSitemapAnchorParser()
            try:
                parser.feed(html or "")
                parser.close()
            except Exception:
                parser.anchors = []

            for anchor in parser.anchors:
                raw_href = clean_text(anchor.get("href"))
                url = canonical_url(self.base_url, raw_href)
                if not url or not same_store_host(self.domain, url):
                    continue

                self.diagnostics["loose_anchor_candidates"] += 1

                candidates = (
                    clean_text(anchor.get("text")),
                    clean_text(anchor.get("title")),
                    clean_text(anchor.get("aria_label")),
                    clean_text(anchor.get("image_alt")),
                )
                title = next(
                    (value for value in candidates if value and classify_game(value)),
                    "",
                )
                if not title:
                    continue

                path = urlparse(url).path.rstrip("/").lower()
                if path in {
                    "", "/trading-card-games", "/trading-card-games.html",
                    "/category-sitemap", "/product-sitemap", "/sitemap",
                }:
                    continue
                if url in seen_urls:
                    continue

                seen_urls.add(url)
                self.diagnostics["loose_anchor_products"] += 1
                products.append({
                    "title": title,
                    "url": url,
                    "text": " ".join(value for value in candidates if value),
                    "image_url": None,
                    "product_id": None,
                    "preorder_page": preorder_page,
                    "source": "LOOSE_LISTING_ANCHOR",
                })

        return products

    def _parse_listing_page(
        self,
        html: str,
        *,
        preorder_page: bool,
    ) -> list[dict[str, Any]]:
        parser = ShopwareListingParser(
            base_url=self.base_url,
            domain=self.domain,
            preorder_page=preorder_page,
        )
        try:
            parser.feed(html or "")
            parser.close()
        except Exception:
            parser.cards = []

        cards = parser.cards
        if not cards:
            cards = self._fallback_supported_anchors(
                html,
                preorder_page=preorder_page,
            )

        self.diagnostics["listing_cards_seen"] += len(cards)
        return cards

    async def fetch_products(self) -> list[dict[str, Any]]:
        self._reset_diagnostics()

        headers = dict(BROWSER_NAV_HEADERS)

        connector = aiohttp.TCPConnector(limit=6, limit_per_host=4)
        discovered_by_url: dict[str, dict[str, Any]] = {}

        async with aiohttp.ClientSession(
            headers=headers,
            connector=connector,
        ) as session:
            roots = await self._discover_listing_roots(session)

            for root, preorder_page in roots:
                max_pages = (
                    MAX_PREORDER_PAGES
                    if preorder_page
                    else self.max_listing_pages
                )
                no_new_streak = 0

                for page in range(1, max_pages + 1):
                    url = self._page_url(root, page)
                    self.diagnostics["listing_pages_checked"] += 1
                    html, response = await self._fetch_text(session, url)

                    if not html or response is None or response.status >= 400:
                        if page == 1:
                            break
                        no_new_streak += 1
                        if no_new_streak >= 2:
                            break
                        continue

                    self.diagnostics["listing_pages_successful"] += 1

                    listing_lower = html.lower()
                    if any(
                        marker in listing_lower
                        for marker in (
                            "pokemon tcg", "pokémon tcg", "one piece tcg",
                            "gundam card game", "riftbound", "fusion world",
                            "palworld", "cyberpunk tcg", "azuki tcg",
                            "hellbreak tcg",
                        )
                    ):
                        self.diagnostics["listing_pages_with_game_text"] += 1
                    if "add to cart" in listing_lower or "add to basket" in listing_lower:
                        self.diagnostics["listing_pages_with_add_to_cart"] += 1

                    cards = self._parse_listing_page(
                        html,
                        preorder_page=preorder_page,
                    )

                    # Step 6J-3F3: some Shopware storefronts return only the
                    # category/filter shell to ordinary HTTP clients and load
                    # the real product grid from /widgets/cms/navigation/... .
                    # Follow only public, same-host fragment URLs embedded in
                    # that shell. No private Store/Admin API is used.
                    if not cards:
                        fragment_urls = self._extract_listing_fragment_urls(html)
                        self.diagnostics["listing_fragment_urls_found"] += len(fragment_urls)
                        fragment_cards: list[dict[str, Any]] = []

                        for fragment_url in fragment_urls:
                            request_url = self._page_url(fragment_url, page)
                            self.diagnostics["listing_fragment_pages_checked"] += 1
                            fragment_html, fragment_response = await self._fetch_text(
                                session,
                                request_url,
                                request_headers={
                                    "X-Requested-With": "XMLHttpRequest",
                                    "Accept": "text/html,*/*;q=0.8",
                                },
                            )
                            if (
                                not fragment_html
                                or fragment_response is None
                                or fragment_response.status >= 400
                            ):
                                continue

                            self.diagnostics["listing_fragment_pages_successful"] += 1
                            parsed_fragment_cards = self._parse_listing_page(
                                fragment_html,
                                preorder_page=preorder_page,
                            )
                            self.diagnostics["listing_fragment_cards_seen"] += len(
                                parsed_fragment_cards
                            )
                            fragment_cards.extend(parsed_fragment_cards)

                        if fragment_cards:
                            cards = fragment_cards

                    page_new = 0
                    for card in cards:
                        title = clean_text(card.get("title"))
                        product_url = canonical_url(self.base_url, card.get("url"))
                        if not title or not product_url or not classify_game(title):
                            continue
                        if product_url in discovered_by_url:
                            # Prefer preorder-page context if either copy says so.
                            if preorder_page:
                                discovered_by_url[product_url]["preorder_page"] = True
                            continue

                        discovered_by_url[product_url] = card
                        page_new += 1

                    if page_new <= 0:
                        no_new_streak += 1
                    else:
                        no_new_streak = 0

                    # Repeated/empty pagination pages are a common Shopware SEO
                    # behavior after the last valid page.
                    if no_new_streak >= 2:
                        break

                    await asyncio.sleep(self.request_delay)

            # Step 6J-3F5: IMPORTANT — sitemap discovery must stay inside
            # this ClientSession context. F3 accidentally ran the sitemap
            # fallback after the `async with ClientSession(...)` block exited,
            # which produced RuntimeError: Session is closed before the first
            # sitemap request could run.
            #
            # Step 6J-3F3: if customized category rendering still yields too few
            # products, fall back to Miniature Market's public Product Sitemap.
            # The sitemap gives us canonical product URLs and titles; a bounded
            # product-page enrichment pass then supplies price/availability.
            if len(discovered_by_url) < 40:
                # F6: standards-based XML sitemap discovery comes first.
                # Miniature Market's HTML product-sitemap is intentionally kept
                # as a secondary fallback because Railway receives a much thinner
                # HTML representation than normal web crawlers.
                xml_entries = await self._discover_xml_sitemap_entries(session)
                unseen_xml_entries = [
                    entry
                    for entry in xml_entries
                    if canonical_url(self.base_url, entry.get("url")) not in discovered_by_url
                ]
                enriched_xml_entries = await self._enrich_sitemap_entries(
                    session,
                    unseen_xml_entries,
                )

                for entry in enriched_xml_entries:
                    title = clean_text(entry.get("title"))
                    product_url = canonical_url(self.base_url, entry.get("url"))
                    if not title or not product_url or not classify_game(title):
                        continue
                    if product_url not in discovered_by_url:
                        discovered_by_url[product_url] = entry

            if len(discovered_by_url) < 40:
                sitemap_entries = await self._discover_product_sitemap_entries(session)
                unseen_sitemap_entries = [
                    entry
                    for entry in sitemap_entries
                    if canonical_url(self.base_url, entry.get("url")) not in discovered_by_url
                ]
                enriched_sitemap_entries = await self._enrich_sitemap_entries(
                    session,
                    unseen_sitemap_entries,
                )

                for entry in enriched_sitemap_entries:
                    title = clean_text(entry.get("title"))
                    product_url = canonical_url(self.base_url, entry.get("url"))
                    if not title or not product_url or not classify_game(title):
                        continue
                    if product_url not in discovered_by_url:
                        discovered_by_url[product_url] = entry

        self.diagnostics["supported_listing_products"] = len(discovered_by_url)
        self.diagnostics["product_urls_discovered"] = len(discovered_by_url)

        entries = list(discovered_by_url.values())

        # During background deep discovery, known URLs are supplied by the
        # universal monitor. Put unseen products first so a 40-product discovery
        # budget can still surface new catalog pages from anywhere in the TCG
        # category rather than reprocessing only the first page.
        if self.known_product_urls:
            entries.sort(
                key=lambda item: (
                    canonical_url(self.base_url, item.get("url")) in self.known_product_urls,
                    clean_text(item.get("title")).lower(),
                )
            )

        if len(entries) > self.max_product_pages:
            entries = entries[: self.max_product_pages]

        print(
            "SHOPWARE DISCOVERY COMPLETE | "
            f"Store={self.store_name} | Roots={self.diagnostics['listing_roots_found']} | "
            f"ListingPages={self.diagnostics['listing_pages_successful']} | "
            f"BrowserPages={self.diagnostics['browser_profile_pages_successful']} | "
            f"GameTextPages={self.diagnostics['listing_pages_with_game_text']} | "
            f"CartTextPages={self.diagnostics['listing_pages_with_add_to_cart']} | "
            f"SupportedDiscovered={self.diagnostics['product_urls_discovered']} | "
            f"FallbackAnchors={self.diagnostics['fallback_supported_anchors']} | "
            f"FragmentURLs={self.diagnostics['listing_fragment_urls_found']} | "
            f"FragmentCards={self.diagnostics['listing_fragment_cards_seen']} | "
            f"XMLSitemapDocs={self.diagnostics['xml_sitemap_docs_successful']} | "
            f"XMLSitemapHits={self.diagnostics['xml_sitemap_tcg_hits']} | "
            f"SitemapProducts={self.diagnostics['sitemap_supported_products']} | "
            f"SitemapProductPagesOK={self.diagnostics['sitemap_product_pages_successful']} | "
            f"BodyTooLarge={self.diagnostics['body_too_large']} | "
            f"LargestBodyBytes={self.diagnostics['largest_body_bytes']} | "
            f"LastError={self.diagnostics.get('last_error')} | "
            f"Returned={len(entries)} | Known={len(self.known_product_urls)}"
        )

        return entries

    def _product_page_to_raw(self, url: str, html: str) -> dict[str, Any] | None:
        schema = parse_jsonld_product(html)
        full_text = clean_text(html)

        title = ""
        sku = None
        external_id = None
        image_url = None
        price = None
        currency = None
        schema_availability = None

        if schema:
            title = clean_text(schema.get("name"))
            sku = clean_text(schema.get("sku")) or None
            external_id = clean_text(
                schema.get("productID")
                or schema.get("mpn")
                or sku
            ) or None
            image_url = schema_image(schema)
            price, currency = schema_price(schema)
            offer = schema_offer(schema)
            schema_availability = availability_from_schema(
                offer.get("availability")
            )

        if not title:
            match = re.search(
                r"<h1\b[^>]*>(.*?)</h1>",
                html or "",
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                title = clean_text(match.group(1))

        if not title:
            match = re.search(
                r"<meta\b[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)[\"']",
                html or "",
                re.IGNORECASE,
            )
            if match:
                title = clean_text(match.group(1))

        if not sku:
            match = SKU_TEXT_RE.search(full_text)
            if match:
                sku = clean_text(match.group(1)) or None

        if not external_id:
            external_id = sku

        if not external_id:
            slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            external_id = slug[:-5] if slug.lower().endswith(".html") else slug
            external_id = clean_text(external_id) or None

        if price is None:
            price = parse_price_from_text(full_text)

        if not currency:
            currency_match = re.search(
                r"(?:priceCurrency|currency)[\"']?\s*[:=]\s*[\"']([A-Z]{3})[\"']",
                html or "",
                re.IGNORECASE,
            )
            currency = (
                currency_match.group(1).upper()
                if currency_match
                else "USD"
            )

        if not image_url:
            image_match = re.search(
                r"<meta\b[^>]+property=[\"']og:image[\"'][^>]+content=[\"']([^\"']+)[\"']",
                html or "",
                re.IGNORECASE,
            )
            if image_match:
                image_url = canonical_url(self.base_url, image_match.group(1))

        if schema_availability:
            available, availability_known, availability_state, availability_source = (
                schema_availability
            )
        else:
            available, availability_known, availability_state, availability_source = (
                availability_from_text(full_text)
            )

        return {
            "title": title,
            "url": url,
            "price": price,
            "currency": currency or "USD",
            "available": available,
            "availability_known": availability_known,
            "availability_state": availability_state,
            "availability_source": availability_source,
            "image_url": image_url,
            "sku": sku,
            "external_product_id": external_id,
            "purchase_limit": parse_purchase_limit(full_text),
            "text": full_text,
            "source": "PRODUCT_PAGE",
        }

    async def get_normalized_products_from_urls(self, urls: list[str]) -> list[dict[str, Any]]:
        requested: list[str] = []
        seen: set[str] = set()

        for raw_url in urls or []:
            url = canonical_url(self.base_url, raw_url)
            if not url or not same_store_host(self.domain, url):
                continue
            if url in seen:
                continue
            seen.add(url)
            requested.append(url)

        if not requested:
            return []

        headers = dict(BROWSER_NAV_HEADERS)
        connector = aiohttp.TCPConnector(
            limit=MAX_CONCURRENT_PRODUCT_REQUESTS,
            limit_per_host=MAX_CONCURRENT_PRODUCT_REQUESTS,
        )
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PRODUCT_REQUESTS)

        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:

            async def fetch_one(url: str) -> dict[str, Any] | None:
                async with semaphore:
                    html, response = await self._fetch_text(session, url)
                    await asyncio.sleep(self.request_delay)

                if not html or response is None or response.status >= 400:
                    return None

                raw = self._product_page_to_raw(url, html)
                if not raw:
                    return None

                normalized = self.normalize_product(raw)
                if normalized is None:
                    return None
                if isinstance(normalized, RetailerProduct):
                    return normalized.to_dict()
                if isinstance(normalized, dict):
                    return dict(normalized)
                return None

            results = await asyncio.gather(
                *(fetch_one(url) for url in requested),
                return_exceptions=False,
            )

        normalized: list[dict[str, Any]] = []
        for item in results:
            if isinstance(item, dict):
                normalized.append(item)

        self.diagnostics["product_pages_successful"] += len(normalized)

        print(
            "SHOPWARE FAST REFRESH COMPLETE | "
            f"Store={self.store_name} | Requested={len(requested)} | "
            f"Validated={len(normalized)} | HTTP429={self.diagnostics['http_429']} | "
            f"HTTPBlocked={self.diagnostics['http_blocked']}"
        )

        return normalized

    def normalize_product(self, product: Any) -> RetailerProduct | None:
        if not isinstance(product, dict):
            self.diagnostics["products_rejected"] += 1
            self.diagnostics["rejected_products"] += 1
            return None

        title = clean_text(product.get("title") or product.get("name"))
        url = canonical_url(self.base_url, product.get("url"))
        if not title or not url:
            self.diagnostics["products_rejected"] += 1
            self.diagnostics["rejected_products"] += 1
            return None

        game = classify_game(title)
        if not game:
            self.diagnostics["products_rejected"] += 1
            self.diagnostics["rejected_products"] += 1
            return None

        source = clean_text(product.get("source") or "LISTING_CARD").upper()
        text = clean_text(product.get("text") or title)
        preorder_page = bool(product.get("preorder_page"))

        price = normalize_price(product.get("price"))
        if price is None:
            price = parse_price_from_text(text)
        if price is not None and price <= 0:
            price = None
        if price is None:
            self.diagnostics["missing_prices"] += 1

        currency = clean_text(product.get("currency")).upper() or "USD"

        if product.get("availability_known") is not None:
            available = bool(product.get("available"))
            availability_known = bool(product.get("availability_known"))
            availability_state = clean_text(
                product.get("availability_state")
            ).upper() or "UNKNOWN"
            availability_source = clean_text(
                product.get("availability_source")
            ) or "SHOPWARE_PRODUCT_PAGE"
        else:
            (
                available,
                availability_known,
                availability_state,
                availability_source,
            ) = availability_from_text(
                text,
                preorder_context=preorder_page,
            )

        if not availability_known:
            self.diagnostics["unknown_availability"] += 1
        elif availability_state == "IN_STOCK":
            self.diagnostics["in_stock_products"] += 1
        elif availability_state == "OUT_OF_STOCK":
            self.diagnostics["out_of_stock_products"] += 1
        elif availability_state == "PREORDER":
            self.diagnostics["preorders"] += 1
        elif availability_state == "BACKORDER":
            self.diagnostics["backorders"] += 1

        product_category = classify_product_category(title)
        product_type = infer_product_type(title)
        product_family = classify_product_family(title)

        if availability_state == "IN_STOCK":
            product_state = "STOCK_AVAILABLE"
        elif availability_state == "OUT_OF_STOCK":
            product_state = "SOLD_OUT"
        elif availability_state == "PREORDER":
            product_state = "PREORDER"
        elif availability_state == "BACKORDER":
            product_state = "BACKORDER"
        elif preorder_page or any(term in text.lower() for term in PREORDER_TERMS):
            # Public preorder labeling confirms lifecycle/page state even when
            # the storefront does not expose a decisive orderability signal.
            # Keep stock availability UNKNOWN while preserving preorder routing.
            product_state = "PREORDER_PAGE"
        else:
            product_state = "PAGE_LIVE"

        external_product_id = clean_text(
            product.get("external_product_id")
            or product.get("product_id")
            or product.get("sku")
        ) or None
        if not external_product_id:
            slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            external_product_id = slug[:-5] if slug.lower().endswith(".html") else slug
            external_product_id = clean_text(external_product_id) or None

        sku = clean_text(product.get("sku")) or None
        image_url = canonical_url(self.base_url, product.get("image_url"))
        purchase_limit = product.get("purchase_limit")
        if purchase_limit is None:
            purchase_limit = parse_purchase_limit(text)

        capability = (
            "FULL_AVAILABILITY"
            if availability_known
            else (
                "DISCOVERY_PRICE_ONLY"
                if price is not None
                else "DISCOVERY_ONLY"
            )
        )

        platform_data = {
            "adapter": "shopware",
            "shopware_version_family": "6",
            "source": source,
            "availability_known": availability_known,
            "availability_state": availability_state,
            "availability_source": availability_source,
            "availability_capability": capability,
            "availability_confidence": (
                "HIGH" if source == "PRODUCT_PAGE" and availability_known
                else "MEDIUM" if availability_known
                else "LOW"
            ),
            "language": "English" if product_family == "GLOBAL_STANDARD" else product_family,
        }

        self.diagnostics["products_accepted"] += 1
        self.diagnostics["normalized_products"] += 1
        games = self.diagnostics.setdefault("games", {})
        games[game] = int(games.get(game, 0) or 0) + 1
        categories = self.diagnostics.setdefault("categories", {})
        categories[product_category] = int(categories.get(product_category, 0) or 0) + 1

        print(
            "SHOPWARE TCG ACCEPTED | "
            f"Store={self.store_name} | Game={game} | Category={product_category} | "
            f"Family={product_family} | Price={price} {currency} | "
            f"Availability={availability_state} | Source={availability_source} | "
            f"Capability={capability} | Title={title}"
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
            purchase_limit=purchase_limit,
            cart_base_url=None,
            platform_data=platform_data,
        )
