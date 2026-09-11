"""Lotus 6K-3C: GameStop public discovery validation, no live alerts."""
from __future__ import annotations
import asyncio
import json
import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import aiohttp
from .base import MajorRetailerAdapter, MajorRetailerCapabilityProfile, MajorRetailerProbe, MajorRetailerProduct
from .registry import major_retailer_adapter

STEP = "6K-3C"
CATEGORY_URL = "https://www.gamestop.com/toys-games/trading-cards"
PRODUCT_PATH = re.compile(r"^/toys-games/trading-cards/products/[^/]+/([0-9]+)\.html$")
_LOCK = asyncio.Lock()
_NEXT_REQUEST = 0.0
GAMES = (
    ("Pokemon", r"\bpok[eé]mon\b"), ("One Piece", r"\bone piece\b"),
    ("Gundam", r"\bgundam\b"), ("Dragon Ball", r"\bdragon ball\b"),
    ("Riftbound", r"\briftbound\b"), ("Palworld", r"\bpalworld\b"),
    ("Naruto", r"\bnaruto\b"), ("Cyberpunk TCG", r"\bcyberpunk\b"),
    ("Azuki TCG", r"\bazuki\b"), ("Hellbreak TCG", r"\bhellbreak\b"),
)

class GameStopSourceError(RuntimeError):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.status = status


def product_url(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlparse(urljoin(CATEGORY_URL, value))
        if (p.scheme != "https" or p.hostname not in {"gamestop.com", "www.gamestop.com"}
                or p.username or p.password or p.port not in (None, 443)
                or not PRODUCT_PATH.fullmatch(p.path)):
            return None
        return "https://www.gamestop.com" + p.path
    except ValueError:
        return None


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []; self.h1 = []; self.scripts = []
        self._h1 = False; self._json = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            url = product_url(attrs.get("href"))
            if url and url not in self.links:
                self.links.append(url)
        if tag == "h1":self._h1 = True
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self._json = []
    def handle_data(self, data):
        if self._h1:self.h1.append(data)
        if self._json is not None:self._json.append(data)
    def handle_endtag(self, tag):
        if tag == "h1":self._h1 = False
        if tag == "script" and self._json is not None:
            try:self.scripts.append(json.loads("".join(self._json)))
            except (ValueError, TypeError):pass
            self._json = None


def _product_records(document):
    # Only root/graph products, not recommendation/product-list descendants.
    roots = document if isinstance(document, list) else [document]
    for root in roots:
        if not isinstance(root, dict):continue
        typ = root.get("@type")
        if typ == "Product" or isinstance(typ, list) and "Product" in typ:
            yield root
        graph = root.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                if isinstance(node, dict) and node.get("@type") == "Product":yield node


def parse_product(body, url):
    url = product_url(url)
    if url is None:return None
    page = Page();page.feed(body)
    pid = PRODUCT_PATH.fullmatch(urlparse(url).path).group(1)
    matches = [r for doc in page.scripts for r in _product_records(doc)
               if product_url(r.get("url")) == url]
    record = matches[0] if len(matches) == 1 else None
    title = str(record.get("name") or "") if record else " ".join(page.h1).strip()
    if not re.search(r"trading card|\btcg\b|booster|elite trainer|starter deck", title, re.I):return None
    games = [name for name, pattern in GAMES if re.search(pattern, title, re.I)]
    if len(games) != 1:return None
    offer = record.get("offers") if record else None
    # Only a single SKU-bound offer is retained as a candidate. Multiple offers,
    # Pro/member pricing and page-wide dollar amounts are not resolved here.
    candidate_price = None
    availability = None
    if isinstance(offer, dict) and offer.get("@type") == "Offer":
        availability = offer.get("availability") if isinstance(offer.get("availability"), str) else None
        if offer.get("priceCurrency") == "USD" and not any(k in offer for k in ("priceSpecification", "eligibleCustomerType", "validForMemberTier")):
            value = offer.get("price")
            try:
                if not isinstance(value, bool):
                    number = float(value)
                    if math.isfinite(number) and number > 0:candidate_price = number
            except (ValueError, TypeError):pass
    return MajorRetailerProduct(
        retailer_key="gamestop", external_product_id=pid, title=title, game=games[0], url=url,
        price=None, currency="USD", availability_state="UNKNOWN", availability_known=False,
        lifecycle_state="PAGE_LIVE", lifecycle_confidence="LOW",
        product_category="UNKNOWN", product_family="UNKNOWN",
        source_name="GameStopPublicStorefront", source_confidence="LOW",
        extra={"validation_only": True, "stock_signal_verified": False,
               "local_inventory_verified": False, "gamestop_price_candidate": candidate_price,
               "gamestop_structured_availability_candidate": availability,
               "gamestop_identity_source": "MATCHED_JSON_LD" if record else "H1_AND_PRODUCT_URL",
               "gamestop_pro_price_verified": False},
    )


def retry_after(value):
    try:delay = float(value)
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:dt = dt.replace(tzinfo=timezone.utc)
            delay = (dt-datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):delay = 60
    return max(1, delay) if math.isfinite(delay) else 60


@major_retailer_adapter("gamestop")
class GameStopMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "gamestop"
    version = "1.0.6-6K3C"
    @property
    def capabilities(self):
        return MajorRetailerCapabilityProfile(discovery=True, page_live=True)
    def _reset(self):
        self.diagnostics = {"integration_state": "VALIDATION_ONLY", "step": STEP,
                            "requests": 0, "candidate_links": 0, "parsed_products": 0,
                            "rejected_products": 0, "last_error": None,
                            "price_verified": False, "stock_verified": False,
                            "catalog_complete": False}
    def _session(self):
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8),
                    headers={"User-Agent": "LotusTracker/1.0.6 GameStopValidation", "Accept": "text/html"})
    async def _request(self, session, url):
        global _NEXT_REQUEST
        if url != CATEGORY_URL and product_url(url) != url:
            raise GameStopSourceError("GAMESTOP_INVALID_URL")
        async with _LOCK:
            delay = _NEXT_REQUEST-time.monotonic()
            if delay > 2:raise GameStopSourceError("GAMESTOP_COOLDOWN_ACTIVE")
            if delay > 0:await asyncio.sleep(delay)
            self.diagnostics["requests"] += 1
            _NEXT_REQUEST = time.monotonic()+1
            try:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        if response.status == 429:_NEXT_REQUEST = time.monotonic()+retry_after(response.headers.get("Retry-After"))
                        elif response.status >= 500:_NEXT_REQUEST = time.monotonic()+30
                        raise GameStopSourceError(f"GAMESTOP_HTTP_{response.status}",response.status)
                    if "html" not in response.headers.get("Content-Type", "").lower():
                        raise GameStopSourceError("GAMESTOP_UNEXPECTED_CONTENT_TYPE",200)
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body)>4*1024*1024:raise GameStopSourceError("GAMESTOP_RESPONSE_TOO_LARGE",200)
                    text = body.decode("utf-8",errors="replace")
                    # Avoid treating a captcha script on a normal page as a block;
                    # reject explicit challenge messaging instead.
                    if any(term in text.lower() for term in ("verify you are human", "access denied", "robot or human", "pardon our interruption")):
                        raise GameStopSourceError("GAMESTOP_CHALLENGE_PAGE",200)
                    return text
            except asyncio.CancelledError:raise
            except GameStopSourceError:raise
            except Exception as error:
                raise GameStopSourceError("GAMESTOP_TRANSPORT_"+type(error).__name__.upper()) from None
    async def healthcheck(self):
        self._reset()
        try:
            async with self._session() as session:
                body = await self._request(session,CATEGORY_URL)
                page = Page();page.feed(body);self.diagnostics["candidate_links"] = len(page.links)
                if not page.links:raise GameStopSourceError("GAMESTOP_NO_PRODUCT_LINKS",200)
                body = await self._request(session,page.links[0])
                product = parse_product(body,page.links[0])
                if product is None:raise GameStopSourceError("GAMESTOP_SAMPLE_NOT_PARSED",200)
                self.diagnostics["parsed_products"] = 1
            return MajorRetailerProbe(self.retailer_key,True,"GameStopPublicStorefront","LOW",200,
                    "GAMESTOP_DISCOVERY_SAMPLE_ONLY",self.get_diagnostics())
        except GameStopSourceError as error:
            self.diagnostics["last_error"] = str(error)
            return MajorRetailerProbe(self.retailer_key,False,"GameStopPublicStorefront","LOW",error.status,
                                      str(error),self.get_diagnostics())
    async def discover_products(self, *, limit=20):
        self._reset();limit=max(1,min(int(limit),4));products=[]
        try:
            async with self._session() as session:
                body=await self._request(session,CATEGORY_URL)
                page=Page();page.feed(body);self.diagnostics["candidate_links"]=len(page.links)
                if not page.links:raise GameStopSourceError("GAMESTOP_NO_PRODUCT_LINKS",200)
                self.diagnostics["detail_budget"]=limit
                for url in page.links[:limit]:
                    body=await self._request(session,url)
                    product=parse_product(body,url)
                    if product:products.append(product)
                    else:self.diagnostics["rejected_products"]+=1
            self.diagnostics["parsed_products"]=len(products)
            if not products:raise GameStopSourceError("GAMESTOP_NO_SUPPORTED_PRODUCTS_PARSED",200)
            return products
        except GameStopSourceError as error:
            self.diagnostics["last_error"]=str(error)
            raise
