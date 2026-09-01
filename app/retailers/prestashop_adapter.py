"""
Lotus Tracker Bot / PonDeX Trackers
PrestaShop Universal Retailer Adapter
Version 1.0.4
Step 6J-3A — PrestaShop Public Storefront Foundation

Safety:
- Public storefront pages and public sitemap GETs only
- No authentication guessing or private PrestaShop Webservice access
- No cart mutation or checkout automation
- No CAPTCHA / queue / anti-bot bypass
- Conservative bounded discovery and request pacing
- Availability is trusted only when explicitly published in Product JSON-LD
- Unknown availability never means sold out
- Non-positive/missing prices are treated as unknown
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from urllib.parse import urljoin, urlparse

import aiohttp

from app.retailer_adapter import RetailerAdapter, RetailerProduct, normalize_price
from app.retailer_registry import retailer_adapter

VERSION = "1.0.4"
USER_AGENT = "LotusTracker/1.0.4 (PonDeX Trackers; public retailer monitor)"
DEFAULT_TIMEOUT = 15
DEFAULT_REQUEST_DELAY = 0.70
MAX_SITEMAPS = 25
MAX_DISCOVERED_URLS = 12000
MAX_PRODUCT_PAGES = 200

SITEMAP_PATHS = (
    "/1_index_sitemap.xml",
    "/sitemap.xml",
    "/sitemap_index.xml",
)

TCG_PRIORITY = (
    "pokemon", "pokémon", "one-piece", "onepiece", "gundam", "fusion-world",
    "riftbound", "palworld", "naruto", "cyberpunk", "azuki", "hellbreak",
    "booster", "deck", "tcg", "trading-card", "card", "single",
)

UNSUPPORTED = (
    "magic the gathering", "magic: the gathering", "yu-gi-oh", "yugioh",
    "lorcana", "digimon", "weiss schwarz", "union arena", "flesh and blood",
    "star wars unlimited", "warhammer", "games workshop",
)

GAME_TERMS = {
    "Pokemon": (
        "pokemon tcg", "pokémon tcg", "pokemon trading card", "pokémon trading card",
        "pokemon card game", "pokémon card game",
    ),
    "Gundam": ("gundam card game", "gundam tcg"),
    "Dragon Ball Fusion World": ("dragon ball fusion world", "fusion world tcg"),
    "Riftbound": ("riftbound",),
    "Palworld": ("palworld tcg", "palworld card game"),
    "Naruto": ("naruto tcg", "naruto card game"),
    "Cyberpunk TCG": ("cyberpunk tcg", "cyberpunk trading card game"),
    "Azuki TCG": ("azuki tcg", "azuki trading card game"),
    "Hellbreak TCG": ("hellbreak tcg", "hellbreak trading card game"),
}

SEALED_TERMS = (
    "booster box", "booster display", "booster pack", "booster bundle",
    "elite trainer box", "starter deck", "battle deck", "structure deck",
    "collection box", "collection set", "special collection", "premium collection",
    "figure collection", "v box", "vstar box", "v star", "world championship deck",
    "world championships deck", "build & battle stadium", "build and battle stadium",
    "deluxe box", "deluxe pack", "double pack", "blister", "tin", "case",
)
SINGLE_TERMS = (
    "single card", "tcg single", "card single", "singles", "individual card",
    "black star promo", "promo card",
)
ACCESSORY_TERMS = (
    "sleeves", "deck box", "binder", "playmat", "play mat", "portfolio",
    "toploader", "top loader",
)

ONE_PIECE_CODE = re.compile(r"\b(?:OP|EB|PRB|ST|EX)\d{1,2}-\d{2,4}\b", re.I)
POKEMON_NUMBER = re.compile(r"\b\d{1,4}\s*/\s*\d{1,4}\b")
JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)
OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
OG_TITLE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', re.I
)
OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
OG_IMAGE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I
)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def clean(value):
    if value is None:
        return ""
    value = html_lib.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_domain(value):
    value = re.sub(r"^https?://", "", str(value or "").strip(), flags=re.I)
    return value.strip("/")


def same_domain(url, domain):
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        dom = domain.lower().split(":")[0]
        return host == dom or host.endswith("." + dom)
    except Exception:
        return False


def classify_game(title):
    text = clean(title).lower()
    if not text or any(term in text for term in UNSUPPORTED):
        return None
    if "one piece card game" in text or "one piece tcg" in text or ONE_PIECE_CODE.search(title or ""):
        return "One Piece"
    for game, terms in GAME_TERMS.items():
        if any(term in text for term in terms):
            return game
    return None


def product_category(title):
    text = clean(title).lower()
    if ONE_PIECE_CODE.search(title or ""):
        return "SINGLE"
    if POKEMON_NUMBER.search(title or "") and ("pokemon" in text or "pokémon" in text):
        return "SINGLE"
    if any(term in text for term in SINGLE_TERMS):
        return "SINGLE"
    if any(term in text for term in SEALED_TERMS):
        return "SEALED"
    if any(term in text for term in ACCESSORY_TERMS):
        return "ACCESSORY"
    return "UNKNOWN"


def product_type(title):
    category = product_category(title)
    if category == "SINGLE":
        return "Single Card"
    text = clean(title).lower()
    mapping = (
        (("elite trainer box",), "Elite Trainer Box"),
        (("booster box", "booster display"), "Booster Box"),
        (("booster bundle",), "Booster Bundle"),
        (("booster pack",), "Booster Pack"),
        (("starter deck",), "Starter Deck"),
        (("battle deck",), "Battle Deck"),
        (("structure deck",), "Structure Deck"),
        (("premium collection",), "Premium Collection"),
        (("tin",), "Tin"),
        (("playmat", "play mat"), "Playmat"),
        (("sleeves",), "Sleeves"),
        (("binder",), "Binder"),
        (("deck box",), "Deck Box"),
    )
    for terms, label in mapping:
        if any(term in text for term in terms):
            return label
    return "TCG Product"


def product_family(title):
    text = f" {clean(title).lower()} "
    if any(term in text for term in (" japanese ", " japan ", " jp version ", " jp edition ", " jp ")):
        return "JP"
    if any(term in text for term in (" korean ", " korea ", " kr version ", " kr edition ", " kr ")):
        return "KR"
    if any(term in text for term in (
        " simplified chinese ", " chinese ", " china ", " cn version ", " cn edition ", " cn ",
    )):
        return "CN"
    if " import " in text:
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


def jsonld_objects(text):
    output = []
    for match in JSON_LD.finditer(text or ""):
        raw = html_lib.unescape(match.group(1).strip())
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        output.extend(parsed if isinstance(parsed, list) else [parsed])
    return output


def product_schema(text):
    queue = list(jsonld_objects(text))
    while queue:
        item = queue.pop(0)
        if isinstance(item, list):
            queue.extend(item)
            continue
        if not isinstance(item, dict):
            continue
        raw_type = item.get("@type")
        types = (
            {str(value).lower() for value in raw_type}
            if isinstance(raw_type, list)
            else {str(raw_type or "").lower()}
        )
        if "product" in types:
            return item
        graph = item.get("@graph")
        if isinstance(graph, list):
            queue.extend(graph)
    return None


def first_offer(schema):
    offers = schema.get("offers") if isinstance(schema, dict) else None
    if isinstance(offers, list):
        return next((offer for offer in offers if isinstance(offer, dict)), None)
    return offers if isinstance(offers, dict) else None


def parse_price(offer):
    if not isinstance(offer, dict):
        return None, "USD"
    raw = offer.get("price") or offer.get("lowPrice")
    currency = clean(offer.get("priceCurrency")).upper() or "USD"
    price = normalize_price(raw)
    if price is not None and price <= 0:
        price = None
    return price, currency


def parse_availability(schema, offer):
    raw = ""
    if isinstance(offer, dict):
        raw = clean(offer.get("availability") or offer.get("itemAvailability")).lower()
    if not raw and isinstance(schema, dict):
        raw = clean(schema.get("availability")).lower()

    compact = re.sub(r"[^a-z]", "", raw)
    if "instock" in compact or "limitedavailability" in compact:
        return True, True, "IN_STOCK", "JSON_LD_OFFER_AVAILABILITY"
    if "outofstock" in compact or "soldout" in compact or "discontinued" in compact:
        return False, True, "OUT_OF_STOCK", "JSON_LD_OFFER_AVAILABILITY"
    if "preorder" in compact or "presale" in compact:
        return True, True, "PREORDER", "JSON_LD_OFFER_AVAILABILITY"
    return False, False, "UNKNOWN", "UNKNOWN"


def parse_title(schema, text):
    title = clean(schema.get("name")) if isinstance(schema, dict) else ""
    if title:
        return title
    for pattern in (OG_TITLE, OG_TITLE_REVERSED, TITLE):
        match = pattern.search(text or "")
        if match:
            return clean(match.group(1))
    return ""


def parse_image(schema, text):
    image = schema.get("image") if isinstance(schema, dict) else None
    if isinstance(image, str) and image.strip():
        return image.strip()
    if isinstance(image, list):
        for item in image:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict) and clean(item.get("url")):
                return clean(item.get("url"))
    if isinstance(image, dict) and clean(image.get("url")):
        return clean(image.get("url"))
    for pattern in (OG_IMAGE, OG_IMAGE_REVERSED):
        match = pattern.search(text or "")
        if match:
            return clean(match.group(1))
    return None


def url_priority(url):
    lowered = str(url or "").lower()
    return sum(10 for term in TCG_PRIORITY if term in lowered)


@retailer_adapter("prestashop")
class PrestaShopAdapter(RetailerAdapter):
    platform = "prestashop"

    def __init__(
        self,
        *,
        domain,
        region="US",
        store_name=None,
        request_delay=DEFAULT_REQUEST_DELAY,
        max_product_pages=MAX_PRODUCT_PAGES,
    ):
        super().__init__(domain=domain, region=region, store_name=store_name)
        self.domain = normalize_domain(self.domain)
        self.base_url = f"https://{self.domain}"
        self.request_delay = max(float(request_delay), 0.5)
        self.max_product_pages = max(1, min(int(max_product_pages), MAX_PRODUCT_PAGES))
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
            "rejected_products": 0,
            "adapter_unknown_availability": 0,
            "adapter_missing_prices": 0,
            "sitemaps_seen": 0,
            "last_error": None,
        }

    def get_diagnostics(self):
        return dict(self.diagnostics)

    async def _get(self, session, url):
        self.diagnostics["pages_checked"] += 1
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
                allow_redirects=True,
            ) as response:
                if response.status >= 400:
                    self.diagnostics["pages_failed"] += 1
                    return None
                self.diagnostics["pages_successful"] += 1
                return await response.text(errors="ignore")
        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            self.diagnostics["pages_failed"] += 1
            self.diagnostics["last_error"] = f"{type(error).__name__}: {error}"
            return None

    async def _discover(self, session):
        queue = [urljoin(self.base_url + "/", path.lstrip("/")) for path in SITEMAP_PATHS]
        visited = set()
        product_urls = set()

        while queue and len(visited) < MAX_SITEMAPS and len(product_urls) < MAX_DISCOVERED_URLS:
            sitemap_url = queue.pop(0)
            if sitemap_url in visited:
                continue
            visited.add(sitemap_url)

            text = await self._get(session, sitemap_url)
            if not text:
                continue

            locations = [clean(value) for value in LOC.findall(text)]
            if not locations:
                continue

            self.diagnostics["sitemaps_seen"] += 1
            for location in locations:
                if not location or not same_domain(location, self.domain):
                    continue
                lowered = location.lower()
                if lowered.endswith(".xml") or "sitemap" in lowered:
                    if location not in visited and location not in queue:
                        queue.append(location)
                else:
                    product_urls.add(location)
                    if len(product_urls) >= MAX_DISCOVERED_URLS:
                        break

            await asyncio.sleep(self.request_delay)

        ranked = sorted(product_urls, key=lambda value: (-url_priority(value), value))
        selected = ranked[: self.max_product_pages]
        self.diagnostics["product_urls_discovered"] = len(product_urls)

        print(
            "PRESTASHOP DISCOVERY | "
            f"Store={self.store_name} | "
            f"Sitemaps={self.diagnostics['sitemaps_seen']} | "
            f"TotalURLs={len(product_urls)} | "
            f"SelectedForFetch={len(selected)}"
        )
        return selected

    async def fetch_products(self):
        self._reset_diagnostics()
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        raw_products = []

        async with aiohttp.ClientSession(
            headers=headers,
            connector=aiohttp.TCPConnector(limit=4, limit_per_host=2),
        ) as session:
            product_urls = await self._discover(session)
            for url in product_urls:
                text = await self._get(session, url)
                if not text:
                    continue
                schema = product_schema(text)
                if not isinstance(schema, dict):
                    continue
                raw_products.append({"url": url, "html": text, "schema": schema})
                self.diagnostics["product_pages_successful"] += 1
                await asyncio.sleep(self.request_delay)

        print(
            "PRESTASHOP FETCH COMPLETE | "
            f"Store={self.store_name} | "
            f"ProductURLs={self.diagnostics['product_urls_discovered']} | "
            f"ProductPages={self.diagnostics['product_pages_successful']} | "
            f"RawProducts={len(raw_products)}"
        )
        return raw_products

    def normalize_product(self, raw_product):
        if not isinstance(raw_product, dict):
            self.diagnostics["products_rejected"] += 1
            self.diagnostics["rejected_products"] += 1
            return None

        url = clean(raw_product.get("url"))
        text = raw_product.get("html") or ""
        schema = raw_product.get("schema")
        if not url or not isinstance(schema, dict):
            self.diagnostics["products_rejected"] += 1
            self.diagnostics["rejected_products"] += 1
            return None

        title = parse_title(schema, text)
        game = classify_game(title)
        if not game:
            self.diagnostics["products_rejected"] += 1
            self.diagnostics["rejected_products"] += 1
            return None

        offer = first_offer(schema)
        price, currency = parse_price(offer)
        if price is None:
            self.diagnostics["adapter_missing_prices"] += 1

        available, availability_known, availability_state, availability_source = (
            parse_availability(schema, offer)
        )
        if not availability_known:
            self.diagnostics["adapter_unknown_availability"] += 1

        category = product_category(title)
        ptype = product_type(title)
        family = product_family(title)
        image = parse_image(schema, text)
        product_state = {
            "IN_STOCK": "STOCK_AVAILABLE",
            "OUT_OF_STOCK": "SOLD_OUT",
            "PREORDER": "PREORDER",
        }.get(availability_state, "PAGE_LIVE")

        sku = clean(schema.get("sku")) or None
        external_id = clean(schema.get("productID") or schema.get("mpn") or sku) or None

        capability = (
            "FULL_AVAILABILITY"
            if availability_known
            else ("DISCOVERY_PRICE_ONLY" if price is not None else "DISCOVERY_ONLY")
        )

        platform_data = {
            "adapter": "prestashop",
            "availability_known": availability_known,
            "availability_state": availability_state,
            "availability_source": availability_source,
            "availability_capability": capability,
            "language": family_language(family),
            "structured_data": "JSON_LD_PRODUCT",
        }

        self.diagnostics["products_accepted"] += 1
        print(
            "PRESTASHOP TCG ACCEPTED | "
            f"Store={self.store_name} | Game={game} | Category={category} | "
            f"Family={family} | Price={price} {currency} | PriceKnown={price is not None} | "
            f"Availability={availability_state} | AvailabilitySource={availability_source} | "
            f"AvailabilityCapability={capability} | Title={title}"
        )

        return RetailerProduct(
            external_id=external_id,
            title=title,
            game=game,
            url=url,
            price=price,
            currency=currency,
            available=available,
            product_type=ptype,
            product_category=category,
            product_family=family,
            product_state=product_state,
            image_url=image,
            vendor=self.store_name,
            tags=None,
            sku=sku,
            external_product_id=external_id,
            offer_id=None,
            variant_id=None,
            purchase_limit=None,
            cart_base_url=None,
            platform_data=platform_data,
        )
