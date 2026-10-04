"""Masterpacks public product pages, version 1.0.0.

Bounded homepage discovery and sharded known-product refresh. Stock requires
agreement between the exact product's JSON-LD offer and its purchase form.
No JavaScript execution, cart requests, retries, or generic website crawling.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import socket
import time
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp

from app.event_listing_filter import is_event_listing
from app.retailer_adapter import RetailerAdapter, RetailerProduct
from app.retailer_registry import retailer_adapter
from app.retailers.prestashop_adapter import classify_game, product_category, product_type

ROOT = "https://masterpacks.pt/en"
MAX_BYTES = 1500000
SPACING_SECONDS = 2.0
_next_request = 0.0
_cooldown_until = 0.0
_request_lock = asyncio.Lock()
_discovery_cursor = 0


def public_url(value, *, product=False):
    value = str(value)
    p = urlsplit(value)
    if (p.scheme != "https" or p.hostname not in {"masterpacks.pt", "www.masterpacks.pt"}
            or p.username or p.password or p.port not in (None, 443)
            or p.query or p.fragment or re.search(r"[\\\s]", value)
            or re.search(r"%2[ef]|%5c|/\.\.?/", p.path, re.I)):
        raise ValueError("Use an HTTPS Masterpacks public page without query parameters.")
    if product and not re.fullmatch(
        r"/(?:en/product|pt/produto)/trading-card-games/[a-zA-Z0-9_%/-]+-\d+/?", p.path
    ):
        raise ValueError("Not a supported Masterpacks TCG product URL.")
    return urlunsplit(("https", "masterpacks.pt", p.path.rstrip("/") or "/", "", ""))


def product_id(url):
    try:
        return re.search(r"-(\d+)$", public_url(url, product=True))[1]
    except (ValueError, TypeError):
        return None


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []; self.scripts = []; self.title = []
        self.states = set(); self.forms = []; self._form = None
        self._json = None; self._title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set(a.get("class", "").split())
        if tag == "a" and len(self.links) < 5000:
            self.links.append(a.get("href", ""))
        if tag == "title": self._title = True
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._json = []
        if "product-page-wrap" in classes:
            self.states.update(c for c in classes if c.startswith("product-state-"))
        if tag == "form" and a.get("id") in {"productBuyForm", "productAlertForm"}:
            self._form = {"kind": a["id"], "id": None, "variant": False,
                          "enabled": False, "preorder": False, "limit": None}
            self.forms.append(self._form)
        if self._form is not None:
            if tag == "input" and a.get("name") == "produto_id":
                self._form["id"] = a.get("value")
            if tag == "select" or (tag == "input" and a.get("name") == "variante_id" and a.get("value")):
                self._form["variant"] = True
            if tag == "button" and a.get("id") == "productSubmitButton":
                self._form["enabled"] = "disabled" not in a and a.get("aria-disabled") != "true"
                self._form["preorder"] = any("preorder" in c for c in classes)
            if tag == "input" and a.get("id") == "qtyInput":
                try:
                    limit = int(a.get("data-limit-qty", "0"))
                    if 0 < limit <= 100: self._form["limit"] = limit
                except ValueError:
                    pass

    def handle_endtag(self, tag):
        if tag == "title": self._title = False
        if tag == "form": self._form = None
        if tag == "script" and self._json is not None:
            if len(self.scripts) < 50: self.scripts.append("".join(self._json))
            self._json = None

    def handle_data(self, data):
        if self._json is not None: self._json.append(data)
        if self._title: self.title.append(data)


def product_nodes(page):
    for script in page.scripts:
        try: pending = [json.loads(script)]
        except (ValueError, RecursionError): continue
        examined = 0
        while pending and examined < 300:
            node = pending.pop(); examined += 1
            if isinstance(node, list): pending.extend(node[:100])
            elif isinstance(node, dict):
                kinds = node.get("@type", [])
                if isinstance(kinds, str): kinds = [kinds]
                if isinstance(kinds, list) and "Product" in kinds: yield node
                if node.get("@graph"): pending.append(node["@graph"])


def language_family(title, url):
    text = unicodedata.normalize("NFKD", title + " " + url)
    text = " " + re.sub(r"[^a-z0-9]+", " ", text.encode("ascii", "ignore").decode().lower()) + " "
    families = []
    for family, words in {
        "JP": ("japanese", "japones", "jp", "jpn"),
        "KR": ("korean", "coreano", "kr", "kor"),
        "CN": ("chinese", "chines", "cn", "chs"),
        "GLOBAL_STANDARD": ("english", "ingles", "eng"),
    }.items():
        if any(" " + word + " " in text for word in words): families.append(family)
    # /en/ is the website locale, never evidence of the product's language.
    if not families and re.search(r"\b(?:EN)\b", title): families.append("GLOBAL_STANDARD")
    if re.search(r"\b(?:french|francais|frances|german|aleman|italian|italiano|spanish|espanhol)\b", text):
        return "UNKNOWN"
    return families[0] if len(families) == 1 else "UNKNOWN"


def parse_product(url, body):
    url = public_url(url, product=True)
    pid = product_id(url)
    page = Page(); page.feed(body)
    candidates = [n for n in product_nodes(page) if product_id(n.get("url", "")) == pid]
    if len(candidates) != 1: return None
    node = candidates[0]
    title = str(node.get("name") or "").strip()
    # Ticket/admission listings and another publisher's Naruto game are not
    # evidence for the supported Bandai game.
    if re.search(r"\b(ticket|admission|entry fee|inscri[cç][aã]o|bilhete|cicaboom|mythos)\b", title, re.I):
        return None
    if is_event_listing(title, str(node.get("category") or ""), url): return None
    game = classify_game(title, url)
    if not game: return None
    category = product_category(title)
    if category not in {"SEALED", "ACCESSORY"}: return None
    offers = node.get("offers")
    if isinstance(offers, dict): offers = [offers]
    if not isinstance(offers, list) or len(offers) != 1: return None
    offer = offers[0]
    if not isinstance(offer, dict) or offer.get("@type") != "Offer": return None
    if product_id(offer.get("url", "")) != pid: return None
    if offer.get("itemCondition") not in {"https://schema.org/NewCondition", "http://schema.org/NewCondition"}:
        return None
    try:
        price = float(offer.get("price"))
        if not math.isfinite(price) or price <= 0: return None
    except (ValueError, TypeError): return None
    if offer.get("priceCurrency") != "EUR": return None

    forms = [f for f in page.forms if f["id"] == pid]
    form = forms[0] if len(forms) == 1 else None
    availability_uri = str(offer.get("availability") or "")
    reported = availability_uri.rsplit("/", 1)[-1] if availability_uri.startswith(("https://schema.org/", "http://schema.org/")) else "UNKNOWN"
    state = "UNKNOWN"
    if form and not form["variant"]:
        if (reported == "InStock" and page.states == {"product-state-instock"}
                and form["kind"] == "productBuyForm" and form["enabled"] and not form["preorder"]):
            state = "IN_STOCK"
        elif (reported == "OutOfStock" and page.states == {"product-state-outstock"}
                and form["kind"] == "productAlertForm"):
            state = "OUT_OF_STOCK"
        # A live preorder fixture has not passed validation yet. Such pages
        # retain reported evidence and discovery/price capability only.
    known = state != "UNKNOWN"
    images = node.get("image") or []
    if isinstance(images, str): images = [images]
    image = images[0] if isinstance(images, list) and images and isinstance(images[0], str) else None
    return RetailerProduct(
        external_id=pid, external_product_id=pid, title=title, game=game, url=url,
        price=price, currency="EUR", available=state in {"IN_STOCK", "PREORDER"},
        product_category=category, product_type=product_type(title),
        product_family=language_family(title, url),
        product_state={"IN_STOCK": "STOCK_AVAILABLE", "OUT_OF_STOCK": "SOLD_OUT",
                       "PREORDER": "PREORDER"}.get(state, "PAGE_LIVE"),
        sku=str(node.get("sku") or "") or None, image_url=image, vendor="Masterpacks",
        purchase_limit=form["limit"] if form else None,
        platform_data={"adapter_version": "1.0.0", "availability_known": known,
                       "availability_state": state,
                       "availability_capability": "FULL_AVAILABILITY" if known else "DISCOVERY_PRICE_ONLY",
                       "availability_confidence": "HIGH" if known else "LOW",
                       "availability_source": "PRODUCT_SCHEMA_AND_FORM" if known else "UNCONFIRMED_PRODUCT_SCHEMA",
                       "reported_availability": reported, "item_condition": "NewCondition",
                       "shipping_to_us": "UNVERIFIED"},
    ).to_dict()


def retry_delay(value):
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
            delay = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError): delay = 900
    return max(60, delay) if math.isfinite(delay) else 900


@retailer_adapter("masterpacks")
class MasterpacksAdapter(RetailerAdapter):
    platform = "masterpacks"

    def __init__(self, *, domain, region="PT", store_name=None):
        super().__init__(domain=domain, region=region, store_name=store_name)
        if str(domain).lower().rstrip("/") not in {"masterpacks.pt", "www.masterpacks.pt", "https://masterpacks.pt", "https://www.masterpacks.pt"}:
            raise ValueError("The Masterpacks adapter only supports masterpacks.pt.")
        self.max_product_pages = 32
        self.known_ids = set()
        self.diagnostics = {k: 0 for k in ("pages_checked", "pages_successful", "product_urls_discovered",
                                         "product_pages_successful", "rejected_products")}

    def get_diagnostics(self): return dict(self.diagnostics)

    def set_known_product_urls(self, urls):
        self.known_ids = {product_id(u) for u in urls} - {None}

    def normalize_product(self, product): return product

    def session(self):
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15, connect=6), trust_env=True,
            connector=aiohttp.TCPConnector(family=socket.AF_INET, limit=1, limit_per_host=1),
            headers={"User-Agent": "LotusTracker/1.0 (public product monitoring)", "Accept": "text/html"},
        )

    async def _get(self, session, url):
        global _next_request, _cooldown_until
        url = public_url(url)
        for _ in range(4):
            async with _request_lock:
                if time.monotonic() < _cooldown_until:
                    raise RuntimeError("MASTERPACKS_COOLDOWN_ACTIVE")
                await asyncio.sleep(max(0, _next_request - time.monotonic()))
                _next_request = time.monotonic() + SPACING_SECONDS
                self.diagnostics["pages_checked"] += 1
                async with session.get(url, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        url = public_url(urljoin(url, response.headers.get("Location", "")))
                        continue
                    if response.status in {202, 401, 403, 429, 503}:
                        _cooldown_until = time.monotonic() + retry_delay(response.headers.get("Retry-After"))
                        raise RuntimeError(f"MASTERPACKS_ACCESS_PAUSED:HTTP_{response.status}")
                    if response.status in {404, 410}: return url, None
                    if response.status != 200:
                        raise RuntimeError(f"MASTERPACKS_HTTP_{response.status}")
                    chunks = []; size = 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > MAX_BYTES: raise ValueError("MASTERPACKS_RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                    body = b"".join(chunks).decode("utf-8", errors="replace")
                    page = Page(); page.feed(body)
                    if re.search(r"captcha|just a moment|access denied|verify you are human", "".join(page.title), re.I):
                        _cooldown_until = time.monotonic() + 900
                        raise RuntimeError("MASTERPACKS_ACCESS_CHALLENGE")
                    self.diagnostics["pages_successful"] += 1
                    return url, body
        raise ValueError("MASTERPACKS_TOO_MANY_REDIRECTS")

    async def _products(self, session, urls):
        products = []; seen = set()
        for original in urls:
            pid = product_id(original)
            if not pid or pid in seen: continue
            seen.add(pid)
            url, body = await self._get(session, original)
            if body is None: continue  # Absence is not an out-of-stock observation.
            if product_id(url) != pid: raise ValueError("MASTERPACKS_PRODUCT_REDIRECT_MISMATCH")
            self.diagnostics["product_pages_successful"] += 1
            item = parse_product(url, body)
            if item:
                # Keep the stored URL stable across canonical redirect changes.
                item["url"] = public_url(original, product=True)
                products.append(item)
            else: self.diagnostics["rejected_products"] += 1
        return products

    async def get_normalized_products_from_urls(self, urls):
        async with self.session() as session:
            return await self._products(session, list(urls)[:24])

    async def _discover(self, limit):
        global _discovery_cursor
        async with self.session() as session:
            url, body = await self._get(session, ROOT)
            if body is None: raise ValueError("MASTERPACKS_HOME_MISSING")
            page = Page(); page.feed(body)
            candidates = {}
            for href in page.links:
                try: target = public_url(urljoin(url, href), product=True)
                except ValueError: continue
                # One website locale; never multiply discovery by language aliases.
                if not urlsplit(target).path.startswith("/en/product/"): continue
                if not re.search(
                    r"/trading-card-games/(?:pokemon-tcg|one-piece-tcg|magic-the-gathering|riftbound[^/]*|gundam-card-game|palworld-tcg|cyberpunk-tcg|cataclysm-arcade(?:-tcg)?|hellbreak-tcg|azuki-tcg|dragonball/fusion-world)/",
                    urlsplit(target).path,
                ): continue
                pid = product_id(target)
                if pid not in self.known_ids: candidates.setdefault(pid, target)
            urls = list(candidates.values())
            self.diagnostics["product_urls_discovered"] += len(urls)
            if not urls: return []
            start = _discovery_cursor % len(urls)
            selected = (urls[start:] + urls[:start])[:limit]
            _discovery_cursor = (start + len(selected)) % len(urls)
            return await self._products(session, selected)

    async def fetch_products(self):
        return await self._discover(min(32, self.max_product_pages))

    async def discover_delta_products(self, known_urls, limit=6):
        self.set_known_product_urls(known_urls)
        return await self._discover(min(6, limit))
