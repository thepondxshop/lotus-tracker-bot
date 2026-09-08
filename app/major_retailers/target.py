"""
Lotus Tracker Bot / PonDeX Trackers
Target Dedicated Major-Retailer Adapter
Step 6K-1B

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
import html as html_lib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import quote, urljoin, urlparse

import aiohttp

from .base import (
    MajorRetailerAdapter,
    MajorRetailerCapabilityProfile,
    MajorRetailerProbe,
    MajorRetailerProduct,
)
from .registry import major_retailer_adapter

VERSION = "1.1.0"
STEP = "6K-1B"
BASE_URL = "https://www.target.com"
REQUEST_TIMEOUT_SECONDS = 18
MAX_RESPONSE_BYTES = 3_500_000
DEFAULT_REQUEST_DELAY = 0.45
MAX_PRODUCT_PAGES = 40

# Transparent crawler identity. We intentionally do not spoof a browser or
# attempt to evade retailer controls.
USER_AGENT = "LotusTracker/1.1 (+https://thepondx.com; public Target monitoring)"

SEARCH_TERMS = (
    "pokemon tcg",
    "one piece card game",
    "gundam card game",
    "dragon ball fusion world",
    "riftbound tcg",
    "tcg cards",
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
            online_availability=True,
            local_store_availability=False,
            exact_inventory=False,
            purchase_limit=False,
            affiliate_links=False,
        )

    def _reset_diagnostics(self):
        self.diagnostics = {
            "version": VERSION,
            "step": STEP,
            "search_requests": 0,
            "search_http_ok": 0,
            "search_http_non_200": 0,
            "search_bytes_max": 0,
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
        if kind == "search":
            self.diagnostics["search_requests"] += 1
        else:
            self.diagnostics["product_requests"] += 1
        self.diagnostics["last_url"] = url

        try:
            async with session.get(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                self.diagnostics["last_http_status"] = response.status
                final_url = str(response.url)
                if response.status != 200:
                    if kind == "search":
                        self.diagnostics["search_http_non_200"] += 1
                    else:
                        self.diagnostics["product_http_non_200"] += 1
                    return None, response.status, final_url

                body = await response.content.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    self.diagnostics["last_error"] = f"{kind.upper()}_BODY_TOO_LARGE"
                    return None, response.status, final_url

                byte_count = len(body)
                if kind == "search":
                    self.diagnostics["search_http_ok"] += 1
                    self.diagnostics["search_bytes_max"] = max(
                        self.diagnostics["search_bytes_max"], byte_count
                    )
                else:
                    self.diagnostics["product_http_ok"] += 1
                    self.diagnostics["product_bytes_max"] = max(
                        self.diagnostics["product_bytes_max"], byte_count
                    )
                return body.decode(response.charset or "utf-8", errors="ignore"), response.status, final_url
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.diagnostics["last_error"] = f"FETCH_ERROR:{type(error).__name__}:{error}"
            return None, None, url

    def _parse_search_candidates(self, html_text: str, search_term: str) -> list[_Candidate]:
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
            title_hint = _title_from_anchor(anchor)
            game = classify_game(title_hint)
            if not game:
                self.diagnostics["unsupported_title_rejections"] += 1
                continue
            self.diagnostics["supported_title_candidates"] += 1
            if tcin not in result:
                result[tcin] = _Candidate(
                    tcin=tcin,
                    url=url.split("?")[0],
                    title_hint=title_hint,
                    search_term=search_term,
                )
        self.diagnostics["target_urls_deduped"] += len(result)
        return list(result.values())

    async def healthcheck(self) -> MajorRetailerProbe:
        self._reset_diagnostics()
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
        }
        url = f"{BASE_URL}/s/{quote('tcg cards', safe='')}"
        async with aiohttp.ClientSession(headers=headers) as session:
            body, status, final_url = await self._get(session, url, kind="search")

        if body is None:
            return MajorRetailerProbe(
                retailer_key=self.retailer_key,
                success=False,
                source_name="Target public search",
                confidence="LOW",
                http_status=status,
                message=self.diagnostics.get("last_error") or "TARGET_SEARCH_UNAVAILABLE",
                diagnostics=self.get_diagnostics(),
            )

        candidates = self._parse_search_candidates(body, "tcg cards")
        success = len(candidates) > 0
        return MajorRetailerProbe(
            retailer_key=self.retailer_key,
            success=success,
            source_name="Target public search/product pages",
            confidence="HIGH" if success else "LOW",
            http_status=status,
            message=(
                f"TARGET_PUBLIC_SEARCH_CONFIRMED:{len(candidates)}_SUPPORTED_PRODUCT_URLS"
                if success
                else "TARGET_SEARCH_HTTP_OK_BUT_NO_SUPPORTED_PRODUCT_URLS"
            ),
            diagnostics={
                **self.get_diagnostics(),
                "final_url": final_url,
                "sample_tcin": candidates[0].tcin if candidates else None,
            },
        )

    async def discover_products(self, *, limit: int = 50) -> list[MajorRetailerProduct]:
        self._reset_diagnostics()
        limit = max(1, min(int(limit or 50), MAX_PRODUCT_PAGES))
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
        }

        candidates: dict[str, _Candidate] = {}
        products: list[MajorRetailerProduct] = []

        async with aiohttp.ClientSession(headers=headers) as session:
            for term in SEARCH_TERMS:
                search_url = f"{BASE_URL}/s/{quote(term, safe='')}"
                body, _, _ = await self._get(session, search_url, kind="search")
                if body:
                    for candidate in self._parse_search_candidates(body, term):
                        candidates.setdefault(candidate.tcin, candidate)
                if len(candidates) >= max(limit * 2, 24):
                    break
                await asyncio.sleep(DEFAULT_REQUEST_DELAY)

            for candidate in list(candidates.values())[:limit]:
                body, _, final_url = await self._get(session, candidate.url, kind="product")
                if not body:
                    await asyncio.sleep(DEFAULT_REQUEST_DELAY)
                    continue

                parsed = _parse_product_page(body, final_url or candidate.url, candidate)
                self.diagnostics["products_parsed"] += 1
                if parsed.get("json_ld_product"):
                    self.diagnostics["json_ld_hits"] += 1
                if parsed.get("h1_found"):
                    self.diagnostics["h1_hits"] += 1
                if parsed.get("tcin"):
                    self.diagnostics["tcin_hits"] += 1
                if parsed.get("upc"):
                    self.diagnostics["upc_hits"] += 1
                if parsed.get("purchase_limit_detected"):
                    self.diagnostics["purchase_limit_signals"] += 1

                title = _clean(parsed.get("title"))
                game = classify_game(title)
                if not game:
                    self.diagnostics["unsupported_title_rejections"] += 1
                    await asyncio.sleep(DEFAULT_REQUEST_DELAY)
                    continue

                seller = _clean(parsed.get("seller"))
                if seller and seller.lower() not in {"target", "target.com"}:
                    self.diagnostics["marketplace_rejections"] += 1
                    await asyncio.sleep(DEFAULT_REQUEST_DELAY)
                    continue

                price = parsed.get("price")
                if price is None:
                    self.diagnostics["missing_prices"] += 1

                availability_known = bool(parsed.get("availability_known"))
                availability_state = _clean(parsed.get("availability_state") or "UNKNOWN").upper()
                if availability_known:
                    self.diagnostics["availability_known"] += 1
                    if availability_state == "IN_STOCK":
                        self.diagnostics["in_stock"] += 1
                    elif availability_state == "OUT_OF_STOCK":
                        self.diagnostics["out_of_stock"] += 1
                    elif availability_state == "PREORDER":
                        self.diagnostics["preorders"] += 1
                else:
                    self.diagnostics["availability_unknown"] += 1

                tcin = _clean(parsed.get("tcin") or candidate.tcin)
                product_url = final_url if _is_target_url(final_url or "") else candidate.url

                product = MajorRetailerProduct(
                    retailer_key="target",
                    external_product_id=tcin,
                    title=title,
                    game=game,
                    url=product_url,
                    price=price,
                    currency="USD",
                    availability_state=availability_state,
                    availability_known=availability_known,
                    availability_confidence=_clean(parsed.get("availability_confidence") or "UNKNOWN").upper(),
                    lifecycle_state=_clean(parsed.get("lifecycle_state") or "PAGE_LIVE").upper(),
                    lifecycle_confidence=_clean(parsed.get("lifecycle_confidence") or "MEDIUM").upper(),
                    product_type="TCG Product",
                    product_category=classify_category(title),
                    product_family=classify_family(title),
                    image_url=parsed.get("image_url"),
                    sku=parsed.get("dpci"),
                    upc=parsed.get("upc"),
                    offer_id=tcin,
                    purchase_limit=None,
                    source_name="target_public_storefront",
                    source_confidence=(
                        "HIGH"
                        if parsed.get("json_ld_product") or (parsed.get("h1_found") and tcin)
                        else "MEDIUM"
                    ),
                    extra={
                        "tcin": tcin,
                        "dpci": parsed.get("dpci"),
                        "seller": seller or None,
                        "seller_signal": "EXPLICIT" if seller else "NOT_EXPOSED",
                        "price_source": parsed.get("price_source"),
                        "availability_source": parsed.get("availability_source"),
                        "purchase_limit_detected_but_not_enabled": parsed.get("purchase_limit_detected"),
                        "search_term": candidate.search_term,
                        "target_adapter_version": VERSION,
                        "target_adapter_step": STEP,
                    },
                )
                products.append(product)
                self.diagnostics["products_accepted"] += 1

                if len(products) >= limit:
                    break
                await asyncio.sleep(DEFAULT_REQUEST_DELAY)

        return products
