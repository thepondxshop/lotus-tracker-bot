"""
Lotus Tracker Bot / PonDeX Trackers
Target Dedicated Major-Retailer Adapter
Step 6K-1C

Purpose
-------
Read-only Target product discovery for Lotus controlled silent validation.
The adapter uses public Target search/product pages only.

Safety
------
- Public GET requests only.
- No login, cart mutation, checkout, queue or CAPTCHA bypass.
- No local-store inventory in this milestone.
- No exact inventory inference.
- UNKNOWN stays UNKNOWN when a product page does not expose a decisive state.
- Explicit third-party marketplace sellers are rejected from the Target-direct
  candidate set so marketplace/scalper listings do not contaminate Target data.
"""

from __future__ import annotations

import asyncio
import gzip
import html as html_lib
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import quote, unquote, urljoin, urlparse

import aiohttp

from .base import (
    MajorRetailerAdapter,
    MajorRetailerCapabilityProfile,
    MajorRetailerProbe,
    MajorRetailerProduct,
)
from .registry import major_retailer_adapter

VERSION = "1.3.0"
STEP = "6K-1C1"
BASE_URL = "https://www.target.com"
REQUEST_TIMEOUT_SECONDS = 18
MAX_RESPONSE_BYTES = 3_500_000
DEFAULT_REQUEST_DELAY = 0.45
MAX_PRODUCT_PAGES = 40

# Target's own engineering team describes Redsky as the aggregation layer
# serving Target.com/mobile clients. This adapter only uses read-only GETs.
REDSKY_BASE_URL = "https://redsky.target.com"
REDSKY_SEARCH_ENDPOINT = f"{REDSKY_BASE_URL}/redsky_aggregations/v1/web/plp_search_v2"
REDSKY_DETAIL_ENDPOINT = f"{REDSKY_BASE_URL}/redsky_aggregations/v1/web/pdp_client_v1"
# Public web-client key currently embedded in Target's frontend ecosystem.
# Keep an env override so Lotus can recover from a normal frontend-key rotation
# without a code deployment. This is not an account credential.
DEFAULT_REDSKY_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
REDSKY_SEARCH_COUNT = 24
REDSKY_REQUEST_DELAY = 0.18


# Transparent crawler identity. We intentionally do not spoof a browser or
# attempt to evade retailer controls.
USER_AGENT = "LotusTracker/1.2 (+https://thepondx.com; public Target monitoring)"

SEARCH_TERMS = (
    "pokemon tcg",
    "one piece card game",
    "gundam card game",
    "dragon ball fusion world",
    "riftbound tcg",
    "tcg cards",
)

# Canonical Target taxonomy pages are preferred over free-text search because
# they are public SEO/crawl surfaces and can expose product links differently
# from /s/... search responses.
CATEGORY_URLS = (
    ("trading_card_games", f"{BASE_URL}/c/trading-card-games-cards-toys/-/N-d4gjq"),
    ("pokemon", f"{BASE_URL}/c/pokemon-trading-cards-card-games-toys/-/N-6llsh"),
    ("one_piece", f"{BASE_URL}/c/one-piece-trading-cards-card-games-toys/-/N-m64pf"),
    ("dragon_ball", f"{BASE_URL}/c/dragon-ball-z-trading-cards-card-games-toys/-/N-y80jp"),
)

# Target publishes this sitemap endpoint in robots.txt. Sitemap discovery is
# a bounded public fallback only; it does not crawl the full Target catalog.
PDP_SITEMAP_INDEX = f"{BASE_URL}/sitemap_pdp-index.xml.gz"
MAX_SITEMAP_INDEX_BYTES = 8_000_000
MAX_SITEMAP_DOC_BYTES = 10_000_000
MAX_SITEMAP_CHILDREN = 4

# Product URLs can appear in rendered anchors or serialized page state.
RAW_PRODUCT_URL_RE = re.compile(
    r"(?:https?:\/\/www\.target\.com|https?://www\.target\.com)?"
    r"(?P<path>/p/[^\"'<>\s]{3,500}?/-/A-(?P<tcin>\d{6,14}))",
    re.I,
)

PRODUCT_URL_RE = re.compile(r"/-/A-(\d{6,14})(?:[/?#]|$)", re.I)
TCIN_TEXT_RE = re.compile(r"\bTCIN\s*:?\s*(\d{6,14})\b", re.I)
UPC_TEXT_RE = re.compile(r"\bUPC\s*:?\s*([0-9]{8,18})\b", re.I)
DPCI_TEXT_RE = re.compile(r"\b(?:Item Number \(DPCI\)|DPCI)\s*:?\s*([0-9-]{5,20})\b", re.I)
PRICE_RE = re.compile(r"\$\s*([0-9]{1,5}(?:,[0-9]{3})*(?:\.\d{2}))")
LIMIT_RE = re.compile(r"\b(?:limit|max(?:imum)?)\s*(?:of\s*)?(\d{1,2})\s*(?:per\s*(?:guest|customer|order))?\b", re.I)
SELLER_RE = re.compile(
    r"\bSold\s*(?:&|and)\s*shipped\s*by\s*([^|•\n\r]{2,80})",
    re.I,
)

UNSUPPORTED_TERMS = (
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
    "sports trading card",
    "football trading card",
    "baseball trading card",
    "basketball trading card",
)

CARD_EVIDENCE = (
    "tcg",
    "trading card",
    "card game",
    "booster",
    "elite trainer",
    "starter deck",
    "deck",
    "collection",
    "blister",
    "tin",
    "card pack",
    "cards",
    "portfolio",
    "binder",
    "playmat",
    "sleeves",
)

SEALED_TERMS = (
    "booster box",
    "booster display",
    "booster pack",
    "booster bundle",
    "elite trainer box",
    "starter deck",
    "battle deck",
    "structure deck",
    "collection box",
    "premium collection",
    "poster collection",
    "binder collection",
    "mini tin",
    " tin",
    "blister",
    "bundle",
    "box set",
    "deck",
)

ACCESSORY_TERMS = (
    "sleeves",
    "deck box",
    "binder",
    "portfolio",
    "playmat",
    "play mat",
    "toploader",
    "top loader",
)

SINGLE_TERMS = (
    "single card",
    "promo card",
    "graded card",
    " psa ",
    " cgc ",
)


@dataclass
class _Candidate:
    tcin: str
    url: str
    title_hint: str
    search_term: str


class _TargetHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._anchor: dict[str, Any] | None = None
        self._in_h1 = False
        self._h1_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.json_ld_blocks: list[str] = []
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        amap = {str(k).lower(): (v or "") for k, v in attrs}
        tag = tag.lower()

        if tag == "a":
            self._anchor = {
                "href": amap.get("href", ""),
                "title": amap.get("title", ""),
                "aria": amap.get("aria-label", ""),
                "img_alt": "",
                "parts": [],
            }
        elif tag == "img" and self._anchor is not None:
            self._anchor["img_alt"] = amap.get("alt", "")
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "meta":
            key = (
                amap.get("property")
                or amap.get("name")
                or amap.get("itemprop")
                or ""
            ).strip().lower()
            content = amap.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "script":
            script_type = amap.get("type", "").strip().lower()
            if script_type == "application/ld+json":
                self._in_json_ld = True
                self._json_ld_parts = []

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag == "a" and self._anchor is not None:
            parts = [str(x).strip() for x in self._anchor.pop("parts", []) if str(x).strip()]
            self._anchor["text"] = " ".join(parts).strip()
            self.anchors.append({k: str(v or "") for k, v in self._anchor.items()})
            self._anchor = None
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            payload = "".join(self._json_ld_parts).strip()
            if payload:
                self.json_ld_blocks.append(payload)
            self._json_ld_parts = []

    def handle_data(self, data: str):
        if not data:
            return
        if self._in_json_ld:
            self._json_ld_parts.append(data)
            return
        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return
        self.text_parts.append(clean)
        if self._anchor is not None:
            self._anchor["parts"].append(clean)
        if self._in_h1:
            self._h1_parts.append(clean)

    @property
    def h1(self) -> str:
        return " ".join(self._h1_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self.text_parts).strip()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html_lib.unescape(str(value))).strip()


def _safe_price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 100000:
        return None
    return round(number, 2)


def _is_target_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"target.com", "www.target.com"}


def _tcin_from_url(url: str) -> str | None:
    match = PRODUCT_URL_RE.search(url or "")
    return match.group(1) if match else None


def _title_from_anchor(anchor: dict[str, str]) -> str:
    choices = (
        anchor.get("aria"),
        anchor.get("title"),
        anchor.get("text"),
        anchor.get("img_alt"),
    )
    for value in choices:
        text = _clean(value)
        if text and len(text) >= 5:
            return text
    return ""


def _candidate_title_from_url(url: str) -> str:
    """Recover a useful title hint from a Target PDP slug."""
    try:
        path = unquote(urlparse(url).path)
    except Exception:
        path = url or ""
    match = re.search(r"/p/([^/]+)/-/A-\d{6,14}", path, re.I)
    if not match:
        return ""
    slug = match.group(1)
    slug = slug.replace("-", " ").replace("_", " ")
    slug = re.sub(r"\b821[0-9]{1,3}\b", " ", slug)
    return _clean(slug)


def _normalize_serialized_target_url(raw: str) -> str:
    value = html_lib.unescape(str(raw or ""))
    value = value.replace("\\/", "/")
    if value.startswith("/p/"):
        value = urljoin(BASE_URL, value)
    return value.split("?")[0].split("#")[0]


def _extract_raw_product_candidates(
    html_text: str,
    source_label: str,
) -> list[_Candidate]:
    """Extract PDP URLs from raw/serialized HTML without relying on <a>."""
    normalized = (html_text or "").replace("\\/", "/")
    found: dict[str, _Candidate] = {}
    for match in RAW_PRODUCT_URL_RE.finditer(normalized):
        path = match.group("path")
        tcin = match.group("tcin")
        url = _normalize_serialized_target_url(path)
        if not _is_target_url(url):
            continue
        title_hint = _candidate_title_from_url(url)
        if not classify_game(title_hint):
            continue
        found.setdefault(
            tcin,
            _Candidate(
                tcin=tcin,
                url=url,
                title_hint=title_hint,
                search_term=source_label,
            ),
        )
    return list(found.values())


def _decode_xml_payload(payload: bytes) -> str | None:
    if not payload:
        return None
    try:
        if payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
    except Exception:
        return None
    try:
        return payload.decode("utf-8", errors="ignore")
    except Exception:
        return None


def _xml_locations(xml_text: str) -> list[str]:
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return [
            html_lib.unescape(x.strip())
            for x in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text, re.I | re.S)
            if x.strip()
        ]
    locations: list[str] = []
    for element in root.iter():
        if str(element.tag).lower().endswith("loc") and element.text:
            value = html_lib.unescape(element.text.strip())
            if value:
                locations.append(value)
    return locations


def _dig(value: Any, *path: str) -> Any:
    current = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _redsky_rows(payload: Any) -> list[dict[str, Any]]:
    """Recover Target product rows while tolerating minor Redsky schema drift."""
    if not isinstance(payload, dict):
        return []

    direct = (
        _dig(payload, "data", "search", "products"),
        _dig(payload, "data", "search", "items"),
        _dig(payload, "data", "products"),
        payload.get("products"),
    )
    for value in direct:
        if isinstance(value, list) and any(isinstance(x, dict) for x in value):
            return [x for x in value if isinstance(x, dict)]

    # Fallback for harmless response-envelope changes: collect dictionaries
    # that look like product summaries and dedupe by TCIN.
    found: dict[str, dict[str, Any]] = {}
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            tcin = _clean(current.get("tcin"))
            title = _clean(
                _first_nonempty(
                    _dig(current, "item", "product_description", "title"),
                    _dig(current, "product_description", "title"),
                    current.get("title"),
                )
            )
            if tcin and title:
                found.setdefault(tcin, current)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return list(found.values())


def _redsky_product(payload_or_row: Any) -> dict[str, Any] | None:
    if not isinstance(payload_or_row, dict):
        return None
    product = _dig(payload_or_row, "data", "product")
    if isinstance(product, dict):
        return product
    if _clean(payload_or_row.get("tcin")):
        return payload_or_row
    return None


def _redsky_title(row: dict[str, Any]) -> str:
    return _clean(
        _first_nonempty(
            _dig(row, "item", "product_description", "title"),
            _dig(row, "product_description", "title"),
            row.get("title"),
            row.get("name"),
        )
    )


def _redsky_tcin(row: dict[str, Any]) -> str:
    return _clean(_first_nonempty(row.get("tcin"), _dig(row, "item", "tcin")))


def _redsky_price(row: dict[str, Any]) -> float | None:
    candidates = (
        _dig(row, "price", "current_retail"),
        _dig(row, "price", "current_retail_min"),
        _dig(row, "price", "formatted_current_price"),
        _dig(row, "price", "reg_retail"),
        row.get("current_retail"),
        row.get("formatted_current_price"),
    )
    for value in candidates:
        price = _safe_price(value)
        if price is not None:
            return price
    return None


def _redsky_image(row: dict[str, Any]) -> str | None:
    candidates = (
        _dig(row, "item", "enrichment", "images", "primary_image_url"),
        _dig(row, "item", "enrichment", "images", "primary_image"),
        _dig(row, "enrichment", "images", "primary_image_url"),
        row.get("image_url"),
    )
    for value in candidates:
        text = _clean(value)
        if text.startswith("http://") or text.startswith("https://"):
            return text
    return None


def _redsky_url(row: dict[str, Any], tcin: str) -> str:
    candidates = (
        _dig(row, "item", "enrichment", "buy_url"),
        _dig(row, "enrichment", "buy_url"),
        row.get("url"),
    )
    for value in candidates:
        text = _clean(value)
        if text:
            if text.startswith("/"):
                text = urljoin(BASE_URL, text)
            if _is_target_url(text):
                return text.split("?")[0]
    return f"{BASE_URL}/p/-/A-{tcin}"


def _redsky_upc(row: dict[str, Any]) -> str | None:
    candidates = (
        _dig(row, "item", "primary_barcode"),
        row.get("primary_barcode"),
        row.get("upc"),
    )
    for value in candidates:
        text = _clean(value)
        if text.isdigit() and 8 <= len(text) <= 18:
            return text
    return None


def _redsky_dpci(row: dict[str, Any]) -> str | None:
    for value in (row.get("dpci"), _dig(row, "item", "dpci")):
        text = _clean(value)
        if text:
            return text
    return None


def _redsky_explicit_seller(row: dict[str, Any]) -> str | None:
    """Return only explicit seller/merchant fields; manufacturer/vendor is ignored."""
    seller_keys = {
        "seller", "seller_name", "sellername", "merchant", "merchant_name",
        "merchantname", "sold_by", "soldby", "seller_display_name",
    }
    stack = [row]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                normalized = str(key or "").strip().lower()
                if normalized in seller_keys:
                    if isinstance(value, dict):
                        text = _clean(_first_nonempty(value.get("name"), value.get("display_name")))
                    else:
                        text = _clean(value)
                    if text:
                        return text
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return None


def _redsky_lifecycle(row: dict[str, Any], title: str) -> tuple[str, str]:
    text = (title or "").lower()
    # Use only explicit preorder wording. Do not infer from dates.
    if "pre-order" in text or "preorder" in text:
        return "PREORDER", "MEDIUM"
    return "PAGE_LIVE", "HIGH"


def classify_game(title: str) -> str | None:
    text = _clean(title).lower()
    if not text:
        return None
    if any(term in text for term in UNSUPPORTED_TERMS):
        return None

    evidence = any(term in text for term in CARD_EVIDENCE)

    if ("pokemon" in text or "pokémon" in text) and evidence:
        return "Pokemon"
    if "one piece" in text and evidence:
        return "One Piece"
    if "gundam" in text and evidence:
        return "Gundam"
    if (
        "fusion world" in text
        or ("dragon ball" in text and evidence)
    ):
        return "Dragon Ball Fusion World"
    if "riftbound" in text and evidence:
        return "Riftbound"
    if "palworld" in text and evidence:
        return "Palworld"
    if "naruto" in text and evidence:
        return "Naruto"
    if "cyberpunk" in text and ("tcg" in text or "card game" in text):
        return "Cyberpunk TCG"
    if "azuki" in text and ("tcg" in text or "card game" in text):
        return "Azuki TCG"
    if "hellbreak" in text and ("tcg" in text or "card game" in text):
        return "Hellbreak TCG"
    return None


def classify_category(title: str) -> str:
    text = f" {_clean(title).lower()} "
    if any(term in text for term in ACCESSORY_TERMS):
        return "ACCESSORY"
    if any(term in text for term in SINGLE_TERMS):
        return "SINGLE"
    if any(term in text for term in SEALED_TERMS):
        return "SEALED"
    if "booster" in text or " tcg " in text or "card game" in text:
        return "SEALED"
    return "UNKNOWN"


def classify_family(title: str) -> str:
    text = _clean(title).lower()
    if "japanese" in text or "japan version" in text or "japan edition" in text:
        return "JP"
    if "simplified chinese" in text or "chinese" in text:
        return "CN"
    if "korean" in text or "korea" in text:
        return "KR"
    return "GLOBAL_STANDARD"


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _json_ld_product(blocks: list[str]) -> dict[str, Any] | None:
    for raw in blocks:
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for item in _walk_json(payload):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(x or "").lower() == "product" for x in types):
                return item
    return None


def _offer_from_product(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(schema, dict):
        return None
    offers = schema.get("offers")
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                return offer
    return None


def _availability_from_schema(offer: dict[str, Any] | None) -> tuple[str, bool, str]:
    if not isinstance(offer, dict):
        return "UNKNOWN", False, "UNKNOWN"
    raw = _clean(offer.get("availability")).lower()
    if not raw:
        return "UNKNOWN", False, "UNKNOWN"
    if "preorder" in raw or "pre-order" in raw:
        return "PREORDER", True, "HIGH"
    if "outofstock" in raw or "out_of_stock" in raw or "out-of-stock" in raw:
        return "OUT_OF_STOCK", True, "HIGH"
    if "instock" in raw or "in_stock" in raw or "in-stock" in raw:
        return "IN_STOCK", True, "HIGH"
    if "backorder" in raw:
        return "BACKORDER", True, "HIGH"
    return "UNKNOWN", False, "UNKNOWN"


def _primary_product_text(full_text: str, title: str) -> str:
    text = _clean(full_text)
    if not text:
        return ""
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
        "find alternative",
        "discover more options",
        "guests also viewed",
        "recommendations for you",
        "related deals",
        "about this item",
    )
    positions = [scoped_lower.find(marker) for marker in cut_markers]
    positions = [p for p in positions if p > 0]
    if positions:
        scoped = scoped[:min(positions)]
    return _clean(scoped)


def _parse_product_page(html_text: str, url: str, candidate: _Candidate) -> dict[str, Any]:
    parser = _TargetHTMLParser()
    try:
        parser.feed(html_text or "")
    except Exception:
        pass

    schema = _json_ld_product(parser.json_ld_blocks)
    offer = _offer_from_product(schema)

    title = _clean(
        (schema or {}).get("name")
        or parser.h1
        or parser.meta.get("og:title")
        or candidate.title_hint
    )
    tcin = (
        _tcin_from_url(url)
        or _clean((schema or {}).get("sku"))
        or candidate.tcin
    )

    text = parser.text
    primary = _primary_product_text(text, title)

    tcin_match = TCIN_TEXT_RE.search(text)
    if tcin_match:
        tcin = tcin_match.group(1)

    upc = ""
    for key in ("gtin12", "gtin13", "gtin", "mpn"):
        value = _clean((schema or {}).get(key))
        if value.isdigit() and len(value) >= 8:
            upc = value
            break
    if not upc:
        match = UPC_TEXT_RE.search(text)
        if match:
            upc = match.group(1)

    dpci = ""
    match = DPCI_TEXT_RE.search(text)
    if match:
        dpci = match.group(1)

    price = None
    price_source = None
    if isinstance(offer, dict):
        price = _safe_price(offer.get("price") or offer.get("lowPrice"))
        if price is not None:
            price_source = "JSON_LD_OFFER"
    if price is None:
        for key in ("product:price:amount", "price"):
            price = _safe_price(parser.meta.get(key))
            if price is not None:
                price_source = "META_PRICE"
                break
    if price is None:
        match = PRICE_RE.search(primary)
        if match:
            price = _safe_price(match.group(1))
            if price is not None:
                price_source = "PRIMARY_TEXT_PRICE"

    availability_state, availability_known, availability_confidence = _availability_from_schema(offer)
    availability_source = "JSON_LD" if availability_known else None

    primary_lower = primary.lower()
    if not availability_known:
        if "pre-order" in primary_lower or "preorder" in primary_lower:
            availability_state = "PREORDER"
            availability_known = True
            availability_confidence = "MEDIUM"
            availability_source = "PRIMARY_TEXT_PREORDER"
        elif "out of stock" in primary_lower or "currently unavailable" in primary_lower:
            availability_state = "OUT_OF_STOCK"
            availability_known = True
            availability_confidence = "MEDIUM"
            availability_source = "PRIMARY_TEXT_OUT_OF_STOCK"
        elif "add to cart" in primary_lower or "ship it" in primary_lower:
            availability_state = "IN_STOCK"
            availability_known = True
            availability_confidence = "MEDIUM"
            availability_source = "PRIMARY_TEXT_BUY_ACTION"

    if "pre-order" in primary_lower or "preorder" in primary_lower or availability_state == "PREORDER":
        lifecycle_state = "PREORDER"
        lifecycle_confidence = "HIGH" if availability_state == "PREORDER" else "MEDIUM"
    elif "coming soon" in primary_lower:
        lifecycle_state = "COMING_SOON"
        lifecycle_confidence = "MEDIUM"
    else:
        lifecycle_state = "PAGE_LIVE"
        lifecycle_confidence = "HIGH" if title and tcin else "MEDIUM"

    image_url = ""
    image = (schema or {}).get("image") if isinstance(schema, dict) else None
    if isinstance(image, str):
        image_url = _clean(image)
    elif isinstance(image, list):
        for entry in image:
            if isinstance(entry, str) and _clean(entry):
                image_url = _clean(entry)
                break
            if isinstance(entry, dict) and _clean(entry.get("url")):
                image_url = _clean(entry.get("url"))
                break
    elif isinstance(image, dict):
        image_url = _clean(image.get("url"))
    if not image_url:
        image_url = _clean(parser.meta.get("og:image"))

    seller = ""
    seller_match = SELLER_RE.search(primary or text[:12000])
    if seller_match:
        seller = _clean(seller_match.group(1))
        # Stop a greedy text capture at common UI phrases.
        seller = re.split(
            r"\b(?:Returns|Shipping|Get it|Add to cart|About this item|Save)\b",
            seller,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" -|•")

    purchase_limit = None
    limit_match = LIMIT_RE.search(primary)
    if limit_match:
        try:
            value = int(limit_match.group(1))
            if 1 <= value <= 20:
                purchase_limit = value
        except Exception:
            purchase_limit = None

    return {
        "title": title,
        "tcin": tcin,
        "upc": upc or None,
        "dpci": dpci or None,
        "price": price,
        "price_source": price_source,
        "availability_state": availability_state,
        "availability_known": availability_known,
        "availability_confidence": availability_confidence,
        "availability_source": availability_source,
        "lifecycle_state": lifecycle_state,
        "lifecycle_confidence": lifecycle_confidence,
        "image_url": image_url or None,
        "seller": seller or None,
        "purchase_limit_detected": purchase_limit,
        "json_ld_product": bool(schema),
        "h1_found": bool(parser.h1),
        "primary_text_bytes": len(primary.encode("utf-8", errors="ignore")),
    }


@major_retailer_adapter("target")
class TargetMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "target"
    version = VERSION

    def __init__(self, definition):
        super().__init__(definition)
        self._reset_diagnostics()

    @property
    def capabilities(self) -> MajorRetailerCapabilityProfile:
        # Local store availability/exact quantities remain intentionally off.
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
        )

    def _reset_diagnostics(self):
        self.diagnostics = {
            "version": VERSION,
            "step": STEP,
            "redsky_key_source": "ENV" if os.getenv("TARGET_REDSKY_KEY") else "PUBLIC_WEB_DEFAULT",
            "redsky_search_requests": 0,
            "redsky_search_http_ok": 0,
            "redsky_search_http_206": 0,
            "redsky_search_http_non_success": 0,
            "redsky_search_rows_seen": 0,
            "redsky_supported_candidates": 0,
            "redsky_detail_requests": 0,
            "redsky_detail_http_ok": 0,
            "redsky_detail_http_non_success": 0,
            "redsky_price_hits": 0,
            "redsky_image_hits": 0,
            "redsky_seller_hits": 0,
            "redsky_marketplace_rejections": 0,
            "redsky_key_rejected": 0,
            "search_requests": 0,
            "search_http_ok": 0,
            "search_http_non_200": 0,
            "search_bytes_max": 0,
            "category_requests": 0,
            "category_http_ok": 0,
            "category_http_non_200": 0,
            "category_bytes_max": 0,
            "category_anchor_candidates": 0,
            "raw_url_candidates": 0,
            "raw_url_supported": 0,
            "sitemap_index_requests": 0,
            "sitemap_index_http_ok": 0,
            "sitemap_index_http_non_200": 0,
            "sitemap_child_urls": 0,
            "sitemap_child_requests": 0,
            "sitemap_child_http_ok": 0,
            "sitemap_child_http_non_200": 0,
            "sitemap_locations_seen": 0,
            "sitemap_tcg_candidates": 0,
            "discovery_source": None,
            "product_anchor_candidates": 0,
            "target_urls_deduped": 0,
            "supported_title_candidates": 0,
            "unsupported_title_rejections": 0,
            "product_requests": 0,
            "product_http_ok": 0,
            "product_http_non_200": 0,
            "product_bytes_max": 0,
            "products_parsed": 0,
            "products_accepted": 0,
            "marketplace_rejections": 0,
            "missing_prices": 0,
            "availability_known": 0,
            "availability_unknown": 0,
            "in_stock": 0,
            "out_of_stock": 0,
            "preorders": 0,
            "json_ld_hits": 0,
            "h1_hits": 0,
            "tcin_hits": 0,
            "upc_hits": 0,
            "purchase_limit_signals": 0,
            "last_http_status": None,
            "last_url": None,
            "last_error": None,
        }

    async def _get(self, session: aiohttp.ClientSession, url: str, *, kind: str):
        counter_prefix = {
            "search": "search",
            "category": "category",
            "product": "product",
            "sitemap_index": "sitemap_index",
            "sitemap_child": "sitemap_child",
        }.get(kind, kind)

        request_key = f"{counter_prefix}_requests"
        if request_key in self.diagnostics:
            self.diagnostics[request_key] += 1
        self.diagnostics["last_url"] = url

        max_bytes = (
            MAX_SITEMAP_INDEX_BYTES
            if kind == "sitemap_index"
            else MAX_SITEMAP_DOC_BYTES
            if kind == "sitemap_child"
            else MAX_RESPONSE_BYTES
        )

        try:
            async with session.get(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                self.diagnostics["last_http_status"] = response.status
                final_url = str(response.url)
                if response.status != 200:
                    non_200_key = f"{counter_prefix}_http_non_200"
                    if non_200_key in self.diagnostics:
                        self.diagnostics[non_200_key] += 1
                    return None, response.status, final_url

                body = await response.content.read(max_bytes + 1)
                if len(body) > max_bytes:
                    self.diagnostics["last_error"] = f"{kind.upper()}_BODY_TOO_LARGE"
                    return None, response.status, final_url

                ok_key = f"{counter_prefix}_http_ok"
                if ok_key in self.diagnostics:
                    self.diagnostics[ok_key] += 1

                byte_count = len(body)
                byte_key = f"{counter_prefix}_bytes_max"
                if byte_key in self.diagnostics:
                    self.diagnostics[byte_key] = max(
                        int(self.diagnostics.get(byte_key, 0) or 0), byte_count
                    )

                if kind in {"sitemap_index", "sitemap_child"}:
                    return body, response.status, final_url
                return body.decode(response.charset or "utf-8", errors="ignore"), response.status, final_url
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.diagnostics["last_error"] = f"FETCH_ERROR:{type(error).__name__}:{error}"
            return None, None, url

    async def _get_redsky_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        params: dict[str, Any],
        kind: str,
    ) -> tuple[dict[str, Any] | None, int | None]:
        if kind == "search":
            self.diagnostics["redsky_search_requests"] += 1
        else:
            self.diagnostics["redsky_detail_requests"] += 1
        self.diagnostics["last_url"] = url
        try:
            async with session.get(
                url,
                params=params,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
                headers={"Accept": "application/json"},
            ) as response:
                status = int(response.status)
                self.diagnostics["last_http_status"] = status
                success = status in {200, 206}
                if kind == "search":
                    if success:
                        self.diagnostics["redsky_search_http_ok"] += 1
                        if status == 206:
                            self.diagnostics["redsky_search_http_206"] += 1
                    else:
                        self.diagnostics["redsky_search_http_non_success"] += 1
                else:
                    if success:
                        self.diagnostics["redsky_detail_http_ok"] += 1
                    else:
                        self.diagnostics["redsky_detail_http_non_success"] += 1
                if status in {401, 403}:
                    self.diagnostics["redsky_key_rejected"] += 1
                if not success:
                    return None, status
                try:
                    payload = await response.json(content_type=None)
                except Exception as error:
                    self.diagnostics["last_error"] = f"REDSKY_JSON_ERROR:{type(error).__name__}:{error}"
                    return None, status
                if not isinstance(payload, dict):
                    self.diagnostics["last_error"] = "REDSKY_JSON_NOT_OBJECT"
                    return None, status
                return payload, status
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.diagnostics["last_error"] = f"REDSKY_FETCH_ERROR:{type(error).__name__}:{error}"
            return None, None

    def _redsky_key(self) -> str:
        return _clean(os.getenv("TARGET_REDSKY_KEY") or DEFAULT_REDSKY_KEY)

    def _redsky_common_params(self) -> dict[str, str]:
        params = {
            "key": self._redsky_key(),
            "channel": "WEB",
            "visitor_id": "0000000000000000000000000000000000",
        }
        pricing_store = _clean(os.getenv("TARGET_PRICING_STORE_ID"))
        if pricing_store:
            params["pricing_store_id"] = pricing_store
        return params

    async def _discover_redsky_candidates(
        self,
        session: aiohttp.ClientSession,
        *,
        limit: int,
        terms: tuple[str, ...] = SEARCH_TERMS,
    ) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for term in terms:
            params: dict[str, Any] = {
                **self._redsky_common_params(),
                "keyword": term,
                "count": REDSKY_SEARCH_COUNT,
                "offset": 0,
                "default_purchasability_filter": "false",
                "include_sponsored": "false",
            }
            payload, _ = await self._get_redsky_json(
                session, REDSKY_SEARCH_ENDPOINT, params=params, kind="search"
            )
            if payload:
                rows = _redsky_rows(payload)
                self.diagnostics["redsky_search_rows_seen"] += len(rows)
                for row in rows:
                    tcin = _redsky_tcin(row)
                    title = _redsky_title(row)
                    if not tcin or not title:
                        continue
                    game = classify_game(title)
                    if not game:
                        continue
                    seller = _redsky_explicit_seller(row)
                    if seller:
                        self.diagnostics["redsky_seller_hits"] += 1
                        if seller.lower() not in {"target", "target.com", "target corporation"}:
                            self.diagnostics["redsky_marketplace_rejections"] += 1
                            continue
                    found.setdefault(tcin, {
                        "tcin": tcin,
                        "title": title,
                        "game": game,
                        "row": row,
                        "search_term": term,
                        "seller": seller,
                    })
                    if len(found) >= max(limit * 2, 24):
                        break
            if len(found) >= max(limit * 2, 24):
                break
            await asyncio.sleep(REDSKY_REQUEST_DELAY)
        self.diagnostics["redsky_supported_candidates"] = len(found)
        return list(found.values())

    async def _redsky_detail(
        self,
        session: aiohttp.ClientSession,
        tcin: str,
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            **self._redsky_common_params(),
            "tcin": tcin,
            "page": f"/p/A-{tcin}",
        }
        pricing_store = _clean(os.getenv("TARGET_PRICING_STORE_ID"))
        if pricing_store:
            params["store_id"] = pricing_store
            params["has_pricing_store_id"] = "true"
        payload, _ = await self._get_redsky_json(
            session, REDSKY_DETAIL_ENDPOINT, params=params, kind="detail"
        )
        return _redsky_product(payload) if payload else None

    def _parse_page_candidates(
        self,
        html_text: str,
        source_label: str,
        *,
        source_kind: str,
    ) -> list[_Candidate]:
        parser = _TargetHTMLParser()
        try:
            parser.feed(html_text or "")
        except Exception:
            pass

        result: dict[str, _Candidate] = {}
        for anchor in parser.anchors:
            href = _clean(anchor.get("href"))
            if not href:
                continue
            url = urljoin(BASE_URL, href)
            if not _is_target_url(url):
                continue
            tcin = _tcin_from_url(url)
            if not tcin:
                continue
            self.diagnostics["product_anchor_candidates"] += 1
            if source_kind == "category":
                self.diagnostics["category_anchor_candidates"] += 1
            title_hint = _title_from_anchor(anchor) or _candidate_title_from_url(url)
            game = classify_game(title_hint)
            if not game:
                self.diagnostics["unsupported_title_rejections"] += 1
                continue
            self.diagnostics["supported_title_candidates"] += 1
            result.setdefault(
                tcin,
                _Candidate(
                    tcin=tcin,
                    url=url.split("?")[0],
                    title_hint=title_hint,
                    search_term=source_label,
                ),
            )

        raw_candidates = _extract_raw_product_candidates(html_text, source_label)
        self.diagnostics["raw_url_candidates"] += len(raw_candidates)
        for candidate in raw_candidates:
            self.diagnostics["raw_url_supported"] += 1
            result.setdefault(candidate.tcin, candidate)

        self.diagnostics["target_urls_deduped"] += len(result)
        return list(result.values())

    async def _discover_from_sitemaps(
        self,
        session: aiohttp.ClientSession,
        *,
        max_candidates: int,
    ) -> list[_Candidate]:
        index_payload, _, _ = await self._get(
            session, PDP_SITEMAP_INDEX, kind="sitemap_index"
        )
        if not isinstance(index_payload, (bytes, bytearray)):
            return []
        index_text = _decode_xml_payload(bytes(index_payload))
        child_urls = [
            url
            for url in _xml_locations(index_text or "")
            if _is_target_url(url)
        ]
        self.diagnostics["sitemap_child_urls"] = len(child_urls)
        if not child_urls:
            return []

        # Bounded sample: newest/end shards plus start shards.
        selected: list[str] = []
        for url in child_urls[-MAX_SITEMAP_CHILDREN:] + child_urls[:MAX_SITEMAP_CHILDREN]:
            if url not in selected:
                selected.append(url)
            if len(selected) >= MAX_SITEMAP_CHILDREN:
                break

        found: dict[str, _Candidate] = {}
        for child_url in selected:
            payload, _, _ = await self._get(session, child_url, kind="sitemap_child")
            if not isinstance(payload, (bytes, bytearray)):
                continue
            xml_text = _decode_xml_payload(bytes(payload))
            locations = _xml_locations(xml_text or "")
            self.diagnostics["sitemap_locations_seen"] += len(locations)
            for url in locations:
                if not _is_target_url(url):
                    continue
                tcin = _tcin_from_url(url)
                if not tcin:
                    continue
                title_hint = _candidate_title_from_url(url)
                if not classify_game(title_hint):
                    continue
                found.setdefault(
                    tcin,
                    _Candidate(
                        tcin=tcin,
                        url=url.split("?")[0],
                        title_hint=title_hint,
                        search_term="target_pdp_sitemap",
                    ),
                )
                if len(found) >= max_candidates:
                    break
            if len(found) >= max_candidates:
                break
            await asyncio.sleep(DEFAULT_REQUEST_DELAY)

        self.diagnostics["sitemap_tcg_candidates"] += len(found)
        return list(found.values())

    async def healthcheck(self) -> MajorRetailerProbe:
        self._reset_diagnostics()
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.8",
        }
        status = None
        candidates: list[dict[str, Any]] = []
        async with aiohttp.ClientSession(headers=headers) as session:
            candidates = await self._discover_redsky_candidates(
                session, limit=8, terms=("pokemon tcg",)
            )
            status = self.diagnostics.get("last_http_status")

            # Keep the old public-page path only as a diagnostic fallback.
            if not candidates:
                label, url = CATEGORY_URLS[0]
                body, status, final_url = await self._get(session, url, kind="category")
                page_candidates = []
                if isinstance(body, str):
                    page_candidates = self._parse_page_candidates(
                        body, label, source_kind="category"
                    )
                if page_candidates:
                    self.diagnostics["discovery_source"] = "CATEGORY_PAGE_FALLBACK"
                    candidates = [
                        {"tcin": c.tcin, "title": c.title_hint, "game": classify_game(c.title_hint)}
                        for c in page_candidates
                    ]

        success = len(candidates) > 0
        if success and not self.diagnostics.get("discovery_source"):
            self.diagnostics["discovery_source"] = "REDSKY_SEARCH"

        return MajorRetailerProbe(
            retailer_key=self.retailer_key,
            success=success,
            source_name="Target Redsky read-only product aggregation",
            confidence="HIGH" if success else "LOW",
            http_status=int(status) if status is not None else None,
            message=(
                f"TARGET_REDSKY_DISCOVERY_CONFIRMED:{len(candidates)}_SUPPORTED_PRODUCTS"
                if success
                else "TARGET_REDSKY_AND_PUBLIC_PAGE_DISCOVERY_EMPTY"
            ),
            diagnostics={
                **self.get_diagnostics(),
                "sample_tcin": candidates[0].get("tcin") if candidates else None,
            },
        )

    async def discover_products(self, *, limit: int = 50) -> list[MajorRetailerProduct]:
        self._reset_diagnostics()
        limit = max(1, min(int(limit or 50), MAX_PRODUCT_PAGES))
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.8",
        }
        products: list[MajorRetailerProduct] = []

        async with aiohttp.ClientSession(headers=headers) as session:
            candidates = await self._discover_redsky_candidates(session, limit=limit)
            if candidates:
                self.diagnostics["discovery_source"] = "REDSKY_SEARCH"

            # If Redsky ever rotates or becomes unavailable, retain the existing
            # HTML/sitemap code as a bounded diagnostic fallback rather than
            # failing silently. It does not claim stock capability.
            if not candidates:
                legacy: dict[str, _Candidate] = {}
                for label, category_url in CATEGORY_URLS:
                    body, _, _ = await self._get(session, category_url, kind="category")
                    if isinstance(body, str):
                        for candidate in self._parse_page_candidates(
                            body, label, source_kind="category"
                        ):
                            legacy.setdefault(candidate.tcin, candidate)
                    await asyncio.sleep(DEFAULT_REQUEST_DELAY)
                if len(legacy) < limit:
                    sitemap_candidates = await self._discover_from_sitemaps(
                        session, max_candidates=max(limit * 2, 24)
                    )
                    for candidate in sitemap_candidates:
                        legacy.setdefault(candidate.tcin, candidate)
                candidates = [
                    {
                        "tcin": c.tcin,
                        "title": c.title_hint,
                        "game": classify_game(c.title_hint),
                        "row": {},
                        "search_term": c.search_term,
                        "seller": None,
                    }
                    for c in legacy.values()
                    if classify_game(c.title_hint)
                ]
                if candidates:
                    self.diagnostics["discovery_source"] = "PUBLIC_PAGE_FALLBACK"

            for candidate in candidates[:limit]:
                tcin = _clean(candidate.get("tcin"))
                base_row = candidate.get("row") if isinstance(candidate.get("row"), dict) else {}
                detail = await self._redsky_detail(session, tcin) if tcin else None
                row = detail if isinstance(detail, dict) else base_row

                title = _redsky_title(row) or _clean(candidate.get("title"))
                game = classify_game(title)
                if not tcin or not title or not game:
                    self.diagnostics["unsupported_title_rejections"] += 1
                    continue

                seller = _redsky_explicit_seller(row) or _clean(candidate.get("seller"))
                if seller:
                    self.diagnostics["redsky_seller_hits"] += 1
                    if seller.lower() not in {"target", "target.com", "target corporation"}:
                        self.diagnostics["redsky_marketplace_rejections"] += 1
                        self.diagnostics["marketplace_rejections"] += 1
                        continue

                price = _redsky_price(row)
                if price is None and row is not base_row:
                    price = _redsky_price(base_row)
                if price is not None:
                    self.diagnostics["redsky_price_hits"] += 1
                else:
                    self.diagnostics["missing_prices"] += 1

                image_url = _redsky_image(row) or _redsky_image(base_row)
                if image_url:
                    self.diagnostics["redsky_image_hits"] += 1

                product_url = _redsky_url(row, tcin)
                if product_url.endswith(f"/A-{tcin}") and base_row:
                    product_url = _redsky_url(base_row, tcin)

                upc = _redsky_upc(row) or _redsky_upc(base_row)
                dpci = _redsky_dpci(row) or _redsky_dpci(base_row)
                lifecycle_state, lifecycle_confidence = _redsky_lifecycle(row, title)
                if lifecycle_state == "PREORDER":
                    self.diagnostics["preorders"] += 1

                # 6K-1C1 deliberately does not claim online availability yet.
                # Discovery + price are now verified; stock validation is 6K-1D.
                self.diagnostics["availability_unknown"] += 1

                product = MajorRetailerProduct(
                    retailer_key="target",
                    external_product_id=tcin,
                    title=title,
                    game=game,
                    url=product_url,
                    price=price,
                    currency="USD",
                    availability_state="UNKNOWN",
                    availability_known=False,
                    availability_confidence="UNKNOWN",
                    lifecycle_state=lifecycle_state,
                    lifecycle_confidence=lifecycle_confidence,
                    product_type="TCG Product",
                    product_category=classify_category(title),
                    product_family=classify_family(title),
                    image_url=image_url,
                    sku=dpci,
                    upc=upc,
                    offer_id=tcin,
                    purchase_limit=None,
                    source_name="target_redsky_readonly",
                    source_confidence="HIGH" if detail else "MEDIUM",
                    extra={
                        "tcin": tcin,
                        "dpci": dpci,
                        "seller": seller or None,
                        "seller_signal": "EXPLICIT" if seller else "NOT_EXPOSED",
                        "price_source": "REDSKY_DETAIL" if detail and price is not None else "REDSKY_SEARCH",
                        "availability_source": None,
                        "discovery_source": self.diagnostics.get("discovery_source"),
                        "search_term": candidate.get("search_term"),
                        "target_adapter_version": VERSION,
                        "target_adapter_step": STEP,
                    },
                )
                products.append(product)
                self.diagnostics["products_parsed"] += 1
                self.diagnostics["products_accepted"] += 1
                if len(products) >= limit:
                    break
                await asyncio.sleep(REDSKY_REQUEST_DELAY)

        return products
