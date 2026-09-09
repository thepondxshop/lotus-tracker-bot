# -*- coding: utf-8 -*-
'''
Lotus Tracker Bot / PonDeX Trackers
Walmart public-storefront validation adapter
Step 6K-3A • Bot release 1.0.6

Purpose:
- Validate public Walmart product discovery, price and lifecycle/page-live signals.
- Reject Walmart Marketplace / third-party seller offers.
- Keep online stock UNKNOWN until a later milestone proves a trustworthy source.
- Keep local-store inventory, exact quantity, purchase limits and affiliate URLs disabled.

Safety:
- Transparent Lotus user agent; no browser impersonation.
- No CAPTCHA solving/bypass, identity rotation, login guessing or queue bypass.
- HTTP 403/challenge responses are surfaced and the source remains untrusted.
- HTTP 429/5xx responses receive bounded Retry-After/backoff handling only.
'''

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlparse

import aiohttp

from .base import (
    MajorRetailerAdapter,
    MajorRetailerCapabilityProfile,
    MajorRetailerProbe,
    MajorRetailerProduct,
)
from .registry import major_retailer_adapter

VERSION = "1.0.6"
STEP = "6K-3A"

USER_AGENT = (
    "LotusTracker/1.0.6 "
    "(PonDeX Trackers; Walmart public storefront validation)"
)
DEFAULT_TIMEOUT_SECONDS = 18
REQUEST_DELAY_SECONDS = 0.35
MAX_RETRIES = 2
MAX_DETAIL_REQUESTS = 60

SOURCE_PAGES: tuple[tuple[str, str], ...] = (
    (
        "collectibles_preorders",
        "https://www.walmart.com/shop/collectibles/preorders",
    ),
    (
        "one_piece",
        "https://www.walmart.com/browse/collectibles/one-piece-trading-cards/"
        "5967908_9807313_5652902_1323664",
    ),
    (
        "pokemon",
        "https://www.walmart.com/browse/collectibles/pokemon-cards/"
        "5967908_9807313_7941434_4252400",
    ),
    (
        "gundam",
        "https://www.walmart.com/browse/collectibles/trading-cards/gundam/"
        "5967908_9807313/YnJhbmQ6R3VuZGFt",
    ),
    (
        "dragon_ball",
        "https://www.walmart.com/browse/collectibles/dragon-ball-trading-cards/"
        "5967908_9807313_7941434_2362492",
    ),
    (
        "all_tcg",
        "https://www.walmart.com/browse/collectibles/trading-card-games/"
        "5967908_9807313_7941434",
    ),
)

RELATIVE_ITEM_URL_RE = re.compile(
    r'''(?:\\?/|/)+ip(?:\\?/|/)+([^"'<>\\\s?]+?)(?:\\?/|/)+([0-9]{6,})'''
    r'''(?=["'<>?&#/\\\s]|$)''',
    re.IGNORECASE,
)
HREF_ITEM_RE = re.compile(
    r'''href\s*=\s*["']([^"']*(?:/ip/)[^"']+)["']''',
    re.IGNORECASE,
)

SCRIPT_JSON_RE = re.compile(
    r'''<script[^>]*type=["']application/(?:ld\+json|json)["'][^>]*>(.*?)</script>''',
    re.IGNORECASE | re.DOTALL,
)
NEXT_DATA_RE = re.compile(
    r'''<script[^>]*id=["']__NEXT_DATA__["'][^>]*>(.*?)</script>''',
    re.IGNORECASE | re.DOTALL,
)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
OG_TITLE_RE = re.compile(
    r'''<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']''',
    re.IGNORECASE,
)
OG_TITLE_RE_REV = re.compile(
    r'''<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:title["']''',
    re.IGNORECASE,
)
OG_IMAGE_RE = re.compile(
    r'''<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']''',
    re.IGNORECASE,
)
OG_IMAGE_RE_REV = re.compile(
    r'''<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']''',
    re.IGNORECASE,
)
META_PRICE_RE = re.compile(
    r'''<meta[^>]+(?:property|itemprop)=["'](?:product:price:amount|price)["']'''
    r'''[^>]+content=["']([0-9]+(?:\.[0-9]{1,2})?)["']''',
    re.IGNORECASE,
)
META_PRICE_RE_REV = re.compile(
    r'''<meta[^>]+content=["']([0-9]+(?:\.[0-9]{1,2})?)["']'''
    r'''[^>]+(?:property|itemprop)=["'](?:product:price:amount|price)["']''',
    re.IGNORECASE,
)
VISIBLE_PRICE_RE = re.compile(
    r'''(?:Current\s+price(?:\s+is)?(?:\s+USD)?|current\s+price|Price\s+when\s+purchased\s+online)'''
    r'''[^$0-9]{0,80}\$?\s*([0-9]{1,5}(?:\.[0-9]{1,2})?)''',
    re.IGNORECASE,
)
GENERIC_PRICE_RE = re.compile(r'''\$\s*([0-9]{1,5}(?:\.[0-9]{1,2})?)''')
RELEASE_DATE_RE = re.compile(
    r'''Release\s+date\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2}(?:,\s+\d{4})?)''',
    re.IGNORECASE,
)

SELLER_JSON_PATTERNS = (
    re.compile(r'''"sellerDisplayName"\s*:\s*"([^"]{1,120})"''', re.IGNORECASE),
    re.compile(r'''"sellerName"\s*:\s*"([^"]{1,120})"''', re.IGNORECASE),
    re.compile(r'''"seller"\s*:\s*\{\s*"name"\s*:\s*"([^"]{1,120})"''', re.IGNORECASE),
)
SELLER_TEXT_RE = re.compile(
    r'''Sold\s+(?:and\s+shipped|&\s+shipped|by)\s+(?:by\s+)?'''
    r'''([A-Za-z0-9&.'’\- ]{2,100}?)'''
    r'''(?=\s+(?:Add\s+to\s+cart|Seller\s+Rating|Report\s+an\s+issue|'''
    r'''Free\s+shipping|Shipping|Pickup|Delivery|Not\s+returnable|Returns|'''
    r'''[0-9](?:\.[0-9]+)?\s+out\s+of\s+5\s+stars)|$)''',
    re.IGNORECASE,
)

CHALLENGE_MARKERS = (
    "captcha",
    "verify you are human",
    "access denied",
    "robot or human",
    "challenge-platform",
)

DIRECT_SELLER_NAMES = {
    "walmart",
    "walmart.com",
    "walmart com",
    "walmart.com usa llc",
    "walmart stores",
    "walmart stores inc",
}


def _clean(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = html.unescape(str(value))
    value = re.sub(r"\s+", " ", value).strip()
    return value or default


def _normalize_json_escapes(value: str) -> str:
    return (
        str(value or "")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003F", "?")
        .replace("\\u003f", "?")
    )


def _strip_tags(raw: str) -> str:
    value = re.sub(r"(?is)<script\b.*?</script>", " ", raw or "")
    value = re.sub(r"(?is)<style\b.*?</style>", " ", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    return _clean(value)


def _safe_json(raw: str) -> Any:
    try:
        return json.loads(html.unescape(raw))
    except Exception:
        return None


def _walk_dicts(value: Any, *, max_nodes: int = 50000) -> Iterable[dict[str, Any]]:
    stack = [value]
    seen = 0
    while stack and seen < max_nodes:
        item = stack.pop()
        seen += 1
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _json_documents(raw_html: str) -> list[Any]:
    docs: list[Any] = []
    match = NEXT_DATA_RE.search(raw_html or "")
    if match:
        parsed = _safe_json(match.group(1))
        if parsed is not None:
            docs.append(parsed)

    for block in SCRIPT_JSON_RE.findall(raw_html or ""):
        parsed = _safe_json(block)
        if parsed is not None:
            docs.append(parsed)
    return docs


def _id_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return str(int(value))
        except Exception:
            return str(value)
    return _clean(value)


def _record_for_item(raw_html: str, item_id: str) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for document in _json_documents(raw_html):
        for record in _walk_dicts(document):
            values = [
                _id_value(record.get("usItemId")),
                _id_value(record.get("itemId")),
                _id_value(record.get("productId")),
                _id_value(record.get("id")),
            ]
            if item_id not in values:
                continue
            score = 10
            lowered_keys = {str(k).lower() for k in record.keys()}
            if {"name", "title"} & lowered_keys:
                score += 2
            if {"sellername", "sellerdisplayname", "seller"} & lowered_keys:
                score += 3
            if {"price", "priceinfo", "currentprice"} & lowered_keys:
                score += 2
            if {"availabilitystatus", "availability", "fulfillment"} & lowered_keys:
                score += 1
            if best is None or score > best[0]:
                best = (score, record)
    return best[1] if best else None


def _first_nested_value(value: Any, keys: set[str], *, max_nodes: int = 4000) -> Any:
    stack = [value]
    seen = 0
    lower_keys = {key.lower() for key in keys}
    while stack and seen < max_nodes:
        item = stack.pop()
        seen += 1
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).lower() in lower_keys and child not in (None, "", [], {}):
                    return child
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None


def _price_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in (
            "price",
            "priceString",
            "displayValue",
            "value",
            "amount",
            "currentPrice",
        ):
            parsed = _price_value(value.get(key))
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 2) if 0 < number < 100000 else None
    text = _clean(value)
    match = re.search(r"([0-9]{1,6}(?:\.[0-9]{1,2})?)", text.replace(",", ""))
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return round(number, 2) if 0 < number < 100000 else None


def _json_ld_product(raw_html: str) -> dict[str, Any] | None:
    for document in _json_documents(raw_html):
        for record in _walk_dicts(document, max_nodes=10000):
            item_type = record.get("@type")
            if isinstance(item_type, list):
                types = {_clean(x).lower() for x in item_type}
            else:
                types = {_clean(item_type).lower()}
            if "product" in types:
                return record
    return None


def _offer_from_json_ld(product: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(product, dict):
        return None
    offers = product.get("offers")
    if isinstance(offers, list):
        for item in offers:
            if isinstance(item, dict):
                return item
        return None
    return offers if isinstance(offers, dict) else None


def _item_id_from_url(url: str) -> str:
    match = re.search(r"/([0-9]{6,})(?:[?/#]|$)", str(url or ""))
    return match.group(1) if match else ""


def _slug_title_from_url(url: str) -> str:
    path = urlparse(url).path
    parts = [part for part in path.split("/") if part]
    if "ip" not in parts:
        return ""
    idx = parts.index("ip")
    if idx + 1 >= len(parts):
        return ""
    slug = unquote(parts[idx + 1])
    return _clean(slug.replace("-", " "))


def _canonical_item_url(raw_url: str, item_id: str = "") -> str:
    value = _normalize_json_escapes(html.unescape(str(raw_url or "")))
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin("https://www.walmart.com", value)
    parsed = urlparse(value)
    if parsed.netloc and "walmart.com" not in parsed.netloc.lower():
        return ""
    iid = item_id or _item_id_from_url(value)
    if not iid:
        return ""
    path = parsed.path or ""
    if "/ip/" not in path:
        return ""
    return f"https://www.walmart.com{path}"


def _extract_item_links(raw_html: str) -> list[str]:
    prepared = _normalize_json_escapes(raw_html or "")
    found: dict[str, str] = {}

    for raw in HREF_ITEM_RE.findall(prepared):
        url = _canonical_item_url(raw)
        iid = _item_id_from_url(url)
        if url and iid:
            found.setdefault(iid, url)

    for slug, iid in RELATIVE_ITEM_URL_RE.findall(prepared):
        url = _canonical_item_url(f"/ip/{slug}/{iid}", iid)
        if url:
            found.setdefault(iid, url)

    return list(found.values())


def _title_from_page(raw_html: str, item_id: str) -> str:
    record = _record_for_item(raw_html, item_id)
    if record:
        value = _first_nested_value(record, {"name", "title", "productName"})
        if isinstance(value, str) and len(_clean(value)) >= 4:
            return _clean(value)

    product = _json_ld_product(raw_html)
    if product:
        value = _clean(product.get("name"))
        if value:
            return value

    for pattern in (H1_RE, OG_TITLE_RE, OG_TITLE_RE_REV, TITLE_RE):
        match = pattern.search(raw_html or "")
        if match:
            text = _strip_tags(match.group(1))
            text = re.sub(r"\s*-\s*Walmart\.com\s*$", "", text, flags=re.I)
            if text:
                return _clean(text)
    return ""


def _image_from_page(raw_html: str, item_id: str) -> str | None:
    record = _record_for_item(raw_html, item_id)
    if record:
        value = _first_nested_value(
            record,
            {"imageUrl", "imageURL", "image", "thumbnailUrl", "mainImageUrl"},
        )
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    product = _json_ld_product(raw_html)
    if product:
        image = product.get("image")
        if isinstance(image, list):
            image = next((x for x in image if isinstance(x, str)), None)
        if isinstance(image, str) and image.startswith(("http://", "https://")):
            return image

    for pattern in (OG_IMAGE_RE, OG_IMAGE_RE_REV):
        match = pattern.search(raw_html or "")
        if match:
            return html.unescape(match.group(1))
    return None


def _price_from_page(raw_html: str, item_id: str, primary_text: str) -> tuple[float | None, str | None]:
    record = _record_for_item(raw_html, item_id)
    if record:
        for keyset in (
            {"currentPrice"},
            {"priceInfo"},
            {"price"},
            {"itemPrice"},
            {"linePrice"},
        ):
            value = _first_nested_value(record, keyset)
            price = _price_value(value)
            if price is not None:
                return price, "WALMART_STRUCTURED_ITEM"

    product = _json_ld_product(raw_html)
    offer = _offer_from_json_ld(product)
    if offer:
        price = _price_value(offer.get("price") or offer.get("lowPrice"))
        if price is not None:
            return price, "JSON_LD_OFFER"

    for pattern in (META_PRICE_RE, META_PRICE_RE_REV, VISIBLE_PRICE_RE):
        match = pattern.search(raw_html or "")
        if match:
            price = _price_value(match.group(1))
            if price is not None:
                return price, "META_OR_PRIMARY_PRICE"

    match = GENERIC_PRICE_RE.search(primary_text[:3500])
    if match:
        price = _price_value(match.group(1))
        if price is not None:
            return price, "PRIMARY_TEXT_PRICE"
    return None, None


def _seller_from_page(raw_html: str, item_id: str, primary_text: str) -> tuple[str, str]:
    record = _record_for_item(raw_html, item_id)
    if record:
        seller = _first_nested_value(
            record,
            {"sellerDisplayName", "sellerName", "sellerDisplay", "seller"},
        )
        if isinstance(seller, dict):
            seller = _first_nested_value(seller, {"name", "displayName"})
        if isinstance(seller, str) and _clean(seller):
            return _clean(seller), "WALMART_STRUCTURED_ITEM"

    match = SELLER_TEXT_RE.search(primary_text)
    if match:
        return _clean(match.group(1)), "PRIMARY_TEXT"

    prepared = _normalize_json_escapes(raw_html or "")
    for pattern in SELLER_JSON_PATTERNS:
        match = pattern.search(prepared)
        if match:
            return _clean(match.group(1)), "RAW_STRUCTURED_TEXT"

    return "", "UNKNOWN"


def _seller_kind(seller: str) -> str:
    normalized = re.sub(r"[^a-z0-9.]+", " ", _clean(seller).lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized in DIRECT_SELLER_NAMES:
        return "DIRECT_WALMART"
    if normalized.startswith("walmart.com ") or normalized.startswith("walmart stores"):
        return "DIRECT_WALMART"
    if normalized:
        return "THIRD_PARTY"
    return "UNKNOWN"


def _primary_product_text(raw_html: str, title: str) -> str:
    text = _strip_tags(raw_html)
    lower = text.lower()
    start = 0
    title_key = _clean(title).lower()
    if title_key:
        pos = lower.find(title_key)
        if pos >= 0:
            start = pos
    scoped = text[start:start + 14000]
    scoped_lower = scoped.lower()
    cut_markers = (
        "similar items you might like",
        "customers also bought",
        "customers also considered",
        "based on what customers bought",
        "related products",
        "sponsored",
        "frequently bought together",
    )
    positions = [scoped_lower.find(marker) for marker in cut_markers]
    positions = [p for p in positions if p > 400]
    if positions:
        scoped = scoped[:min(positions)]
    return _clean(scoped)


def _classify_game(title: str, extra_text: str = "") -> str | None:
    text = f"{title} {extra_text}".lower()

    if "fusion world" in text:
        return "Dragon Ball Fusion World"
    if "one piece" in text and any(
        token in text for token in ("card", "tcg", "trading", "booster", "deck")
    ):
        return "One Piece"
    if ("pokemon" in text or "pokémon" in text) and any(
        token in text for token in ("card", "tcg", "booster", "deck", "trainer", "tin", "collection")
    ):
        return "Pokemon"
    if "gundam" in text and any(
        token in text for token in ("card", "tcg", "booster", "deck", "accessory")
    ):
        return "Gundam"
    if "riftbound" in text:
        return "Riftbound"
    if "palworld" in text and any(token in text for token in ("card", "tcg", "booster", "deck")):
        return "Palworld"
    if "naruto" in text and any(token in text for token in ("card", "tcg", "booster", "deck")):
        return "Naruto"
    if "cyberpunk" in text and any(token in text for token in ("card", "tcg", "trading")):
        return "Cyberpunk TCG"
    if "azuki" in text and any(token in text for token in ("card", "tcg", "trading")):
        return "Azuki TCG"
    if "hellbreak" in text:
        return "Hellbreak TCG"
    return None


def _classify_product_type(title: str) -> tuple[str, str]:
    text = _clean(title).lower()
    mappings = (
        (("booster box", "booster display", "display box"), "Booster Box", "SEALED"),
        (("booster bundle",), "Booster Bundle", "SEALED"),
        (("elite trainer box", " etb"), "Elite Trainer Box", "SEALED"),
        (("deck build box",), "Deck Build Box", "SEALED"),
        (("double pack",), "Double Pack", "SEALED"),
        (("booster pack",), "Booster Pack", "SEALED"),
        (("starter deck", "start deck", "champion deck", "battle deck"), "Deck", "SEALED"),
        (("collection box", "premium collection", "collection set", " ex box"), "Collection", "SEALED"),
        (("tin",), "Tin", "SEALED"),
        (("blister",), "Blister", "SEALED"),
        (("sleeve", "playmat", "play mat", "binder", "portfolio", "deck box", "accessory set"), "Accessory", "ACCESSORIES"),
        (("psa ", "bgs ", "cgc ", "graded"), "Graded Single", "SINGLES"),
    )
    for keywords, label, category in mappings:
        if any(keyword in text for keyword in keywords):
            return label, category
    return "TCG Product", "SEALED"


def _classify_family(title: str, primary_text: str = "") -> str:
    text = f" {title} {primary_text[:1200]} ".lower()
    if any(token in text for token in (" japanese ", " japan ", " jp ", "(jp)", " jpn ")):
        return "JP"
    if any(token in text for token in (" korean ", " korea ", " kr ", "(kr)")):
        return "KR"
    if any(token in text for token in (" simplified chinese ", " chinese ", " china ", " cn ", "(cn)")):
        return "CN"
    return "GLOBAL_STANDARD"


def _lifecycle(primary_text: str) -> tuple[str, str]:
    text = _clean(primary_text).lower()
    if re.search(r"\bpre[\s-]?order\b", text):
        return "PREORDER", "HIGH"
    if "coming soon" in text:
        return "COMING_SOON", "MEDIUM"
    return "PAGE_LIVE", "HIGH"


def _availability_hint(primary_text: str) -> str:
    text = _clean(primary_text).lower()
    if re.search(r"\bout of stock\b|\bsold out\b", text):
        return "OUT_OF_STOCK_HINT"
    if re.search(r"\bpre[\s-]?order\b", text):
        return "PREORDER_HINT"
    if "coming soon" in text:
        return "COMING_SOON_HINT"
    if "add to cart" in text:
        return "ADD_TO_CART_HINT"
    return "UNKNOWN"


def _release_date_hint(primary_text: str) -> str | None:
    match = RELEASE_DATE_RE.search(primary_text or "")
    return _clean(match.group(1)) if match else None


def _challenge(raw_html: str) -> bool:
    text = (raw_html or "").lower()
    return any(marker in text for marker in CHALLENGE_MARKERS)


@major_retailer_adapter("walmart")
class WalmartMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "walmart"
    version = VERSION

    def __init__(self, definition):
        super().__init__(definition)
        self._last_request_at = 0.0
        self.diagnostics = self._fresh_diagnostics()

    @staticmethod
    def _fresh_diagnostics() -> dict[str, Any]:
        return {
            "integration_state": "VALIDATION_ONLY",
            "source_strategy": "PUBLIC_STOREFRONT_BROWSE_PLUS_PDP",
            "discovery_source": "WALMART_PUBLIC_STOREFRONT",
            "browse_requests": 0,
            "browse_http_ok": 0,
            "browse_http_403": 0,
            "browse_http_429": 0,
            "browse_http_5xx": 0,
            "browse_challenge_pages": 0,
            "candidate_links": 0,
            "detail_requests": 0,
            "detail_http_ok": 0,
            "detail_http_403": 0,
            "detail_http_429": 0,
            "detail_http_5xx": 0,
            "detail_challenge_pages": 0,
            "direct_walmart_accepted": 0,
            "third_party_rejected": 0,
            "unknown_seller_rejected": 0,
            "unsupported_games_rejected": 0,
            "price_hits": 0,
            "missing_prices": 0,
            "preorder_hits": 0,
            "coming_soon_hits": 0,
            "release_date_hints": 0,
            "availability_hint_add_to_cart": 0,
            "availability_hint_out_of_stock": 0,
            "availability_hint_preorder": 0,
            "availability_hint_unknown": 0,
            "rate_limit_retries": 0,
            "rate_limit_backoff_seconds": 0.0,
            "last_non_success_status": None,
            "last_error": None,
            "seller_samples": [],
            "source_pages_ok": [],
        }

    @property
    def capabilities(self) -> MajorRetailerCapabilityProfile:
        return MajorRetailerCapabilityProfile(
            discovery=True,
            price=True,
            page_live=True,
            preorder=True,
            online_availability=False,
            local_store_availability=False,
            exact_inventory=False,
            purchase_limit=False,
            affiliate_links=False,
            release_date=False,
        )

    async def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = REQUEST_DELAY_SECONDS - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _request_text(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        kind: str,
    ) -> tuple[int, str]:
        retry = 0
        while True:
            await self._pace()
            self.diagnostics[f"{kind}_requests"] += 1

            try:
                async with session.get(
                    url,
                    allow_redirects=True,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml",
                    },
                ) as response:
                    self._last_request_at = time.monotonic()
                    status = int(response.status)
                    body = await response.text(errors="replace")

                    if status == 200:
                        if _challenge(body):
                            self.diagnostics[f"{kind}_challenge_pages"] += 1
                            self.diagnostics["last_non_success_status"] = 200
                            self.diagnostics["last_error"] = "WALMART_CHALLENGE_PAGE"
                            return status, ""
                        self.diagnostics[f"{kind}_http_ok"] += 1
                        return status, body

                    self.diagnostics["last_non_success_status"] = status
                    if status == 403:
                        self.diagnostics[f"{kind}_http_403"] += 1
                        self.diagnostics["last_error"] = "WALMART_HTTP_403"
                        return status, ""
                    if status == 429:
                        self.diagnostics[f"{kind}_http_429"] += 1
                    elif status >= 500:
                        self.diagnostics[f"{kind}_http_5xx"] += 1

                    if status == 429 or status >= 500:
                        if retry < MAX_RETRIES:
                            retry += 1
                            self.diagnostics["rate_limit_retries"] += 1
                            retry_after = response.headers.get("Retry-After")
                            try:
                                wait = float(retry_after) if retry_after else 0.0
                            except Exception:
                                wait = 0.0
                            if wait <= 0:
                                wait = min(2.0 * (2 ** (retry - 1)), 10.0)
                            wait = max(0.5, min(wait, 20.0))
                            self.diagnostics["rate_limit_backoff_seconds"] = round(
                                float(self.diagnostics["rate_limit_backoff_seconds"]) + wait,
                                2,
                            )
                            await asyncio.sleep(wait)
                            continue

                    self.diagnostics["last_error"] = f"WALMART_HTTP_{status}"
                    return status, ""

            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._last_request_at = time.monotonic()
                self.diagnostics["last_error"] = (
                    f"{type(error).__name__}: {_clean(error)}"
                )
                return 0, ""

    async def healthcheck(self) -> MajorRetailerProbe:
        self.diagnostics = self._fresh_diagnostics()
        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(limit=4)
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
        ) as session:
            status, body = await self._request_text(
                session,
                SOURCE_PAGES[-1][1],
                kind="browse",
            )

        links = _extract_item_links(body) if body else []
        self.diagnostics["candidate_links"] = len(links)
        if body:
            self.diagnostics["source_pages_ok"].append(SOURCE_PAGES[-1][0])

        success = status == 200 and bool(body)
        confidence = "HIGH" if success and links else ("MEDIUM" if success else "LOW")
        message = (
            "WALMART_PUBLIC_STOREFRONT_REACHABLE"
            if success
            else (self.diagnostics.get("last_error") or "WALMART_PUBLIC_STOREFRONT_UNAVAILABLE")
        )
        return MajorRetailerProbe(
            retailer_key=self.retailer_key,
            success=success,
            source_name="WalmartPublicStorefront",
            confidence=confidence,
            http_status=status or None,
            message=message,
            diagnostics=self.get_diagnostics(),
        )

    async def discover_products(self, *, limit: int = 50) -> list[MajorRetailerProduct]:
        self.diagnostics = self._fresh_diagnostics()
        limit = max(1, min(int(limit or 50), 50))
        detail_budget = min(MAX_DETAIL_REQUESTS, max(limit * 3, 20))

        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(limit=6)
        candidate_map: dict[str, dict[str, str]] = {}

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
        ) as session:
            for source_name, source_url in SOURCE_PAGES:
                _, body = await self._request_text(
                    session,
                    source_url,
                    kind="browse",
                )
                if not body:
                    continue
                self.diagnostics["source_pages_ok"].append(source_name)
                for url in _extract_item_links(body):
                    iid = _item_id_from_url(url)
                    if not iid:
                        continue
                    candidate_map.setdefault(
                        iid,
                        {"url": url, "source_page": source_name},
                    )
                    if len(candidate_map) >= max(detail_budget * 2, 80):
                        break

            self.diagnostics["candidate_links"] = len(candidate_map)
            results: list[MajorRetailerProduct] = []
            detail_count = 0

            for item_id, candidate in candidate_map.items():
                if len(results) >= limit or detail_count >= detail_budget:
                    break
                detail_count += 1

                _, body = await self._request_text(
                    session,
                    candidate["url"],
                    kind="detail",
                )
                if not body:
                    continue

                title = _title_from_page(body, item_id) or _slug_title_from_url(candidate["url"])
                if not title:
                    self.diagnostics["unsupported_games_rejected"] += 1
                    continue

                primary_text = _primary_product_text(body, title)
                game = _classify_game(title, primary_text[:1500])
                if not game:
                    self.diagnostics["unsupported_games_rejected"] += 1
                    continue

                seller, seller_source = _seller_from_page(body, item_id, primary_text)
                seller_kind = _seller_kind(seller)

                if seller and seller not in self.diagnostics["seller_samples"]:
                    samples = list(self.diagnostics["seller_samples"])
                    if len(samples) < 8:
                        samples.append(seller)
                        self.diagnostics["seller_samples"] = samples

                if seller_kind == "THIRD_PARTY":
                    self.diagnostics["third_party_rejected"] += 1
                    continue
                if seller_kind != "DIRECT_WALMART":
                    self.diagnostics["unknown_seller_rejected"] += 1
                    continue

                price, price_source = _price_from_page(body, item_id, primary_text)
                if price is not None:
                    self.diagnostics["price_hits"] += 1
                else:
                    self.diagnostics["missing_prices"] += 1

                lifecycle_state, lifecycle_confidence = _lifecycle(primary_text)
                if lifecycle_state == "PREORDER":
                    self.diagnostics["preorder_hits"] += 1
                elif lifecycle_state == "COMING_SOON":
                    self.diagnostics["coming_soon_hits"] += 1

                availability_hint = _availability_hint(primary_text)
                hint_counter = {
                    "ADD_TO_CART_HINT": "availability_hint_add_to_cart",
                    "OUT_OF_STOCK_HINT": "availability_hint_out_of_stock",
                    "PREORDER_HINT": "availability_hint_preorder",
                }.get(availability_hint, "availability_hint_unknown")
                self.diagnostics[hint_counter] += 1

                release_hint = _release_date_hint(primary_text)
                if release_hint:
                    self.diagnostics["release_date_hints"] += 1

                product_type, product_category = _classify_product_type(title)
                family = _classify_family(title, primary_text)
                image_url = _image_from_page(body, item_id)

                results.append(
                    MajorRetailerProduct(
                        retailer_key=self.retailer_key,
                        external_product_id=item_id,
                        title=title,
                        game=game,
                        url=_canonical_item_url(candidate["url"], item_id),
                        price=price,
                        currency="USD",
                        availability_state="UNKNOWN",
                        availability_known=False,
                        availability_confidence="UNKNOWN",
                        lifecycle_state=lifecycle_state,
                        lifecycle_confidence=lifecycle_confidence,
                        product_type=product_type,
                        product_category=product_category,
                        product_family=family,
                        image_url=image_url,
                        source_name="WalmartPublicStorefront",
                        source_confidence="HIGH",
                        extra={
                            "walmart_source_page": candidate["source_page"],
                            "walmart_seller": seller,
                            "walmart_seller_source": seller_source,
                            "walmart_seller_kind": seller_kind,
                            "price_source": price_source,
                            "availability_hint": availability_hint,
                            "release_date_candidate": release_hint,
                            "stock_signal_verified": False,
                            "local_inventory_verified": False,
                            "marketplace_offer_rejected": False,
                            "validation_only": True,
                        },
                    )
                )
                self.diagnostics["direct_walmart_accepted"] += 1

        if not results and not self.diagnostics.get("last_error"):
            if self.diagnostics["third_party_rejected"] or self.diagnostics["unknown_seller_rejected"]:
                self.diagnostics["last_error"] = "NO_DIRECT_WALMART_OFFERS_ACCEPTED"
            elif self.diagnostics["candidate_links"] == 0:
                self.diagnostics["last_error"] = "NO_WALMART_PRODUCT_CANDIDATES"
            else:
                self.diagnostics["last_error"] = "NO_SUPPORTED_DIRECT_WALMART_PRODUCTS"

        return results
