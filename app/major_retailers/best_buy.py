"""Lotus 6K-3B / 1.0.6: Best Buy US official API, validation only.

No background task, persistence, event publication, or checkout in this module.
Live stock remains UNKNOWN until the source is validated with an approved key.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, parse_qsl

import aiohttp
from .base import (MajorRetailerAdapter, MajorRetailerCapabilityProfile,
                   MajorRetailerProbe, MajorRetailerProduct)
from .registry import major_retailer_adapter

VERSION = "1.0.6"
STEP = "6K-3B"
API_ROOT = "https://api.bestbuy.com/v1/products"
FIELDS = ("sku,name,salePrice,priceRestriction,url,image,onlineAvailability,"
          "onlineAvailabilityUpdateDate,inStoreAvailability,orderable,releaseDate,"
          "active,type,categoryPath,preowned,secondaryMarket")
_REQUEST_LOCK = asyncio.Lock()
_NEXT_REQUEST_AT = 0.0
GAMES = (
    ("Pokemon", r"\bpok[eé]mon\b"), ("One Piece", r"\bone piece\b"),
    ("Gundam", r"\bgundam\b"), ("Dragon Ball", r"\bdragon ball\b"),
    ("Riftbound", r"\briftbound\b"), ("Palworld", r"\bpalworld\b"),
    ("Naruto", r"\bnaruto\b"), ("Cyberpunk TCG", r"\bcyberpunk\b"),
    ("Azuki TCG", r"\bazuki\b"), ("Hellbreak TCG", r"\bhellbreak\b"),
)


class BestBuyAPIError(RuntimeError):
    """Messages never contain request URLs, API keys, or raw response bodies."""
    def __init__(self, code, status=None):
        super().__init__(code)
        self.status = status


def _safe_url(value, hosts):
    if not isinstance(value, str):
        return None
    try:
        p = urlparse(value)
        if (p.scheme == "https" and p.hostname in hosts and not p.username
                and not p.password and p.port in (None, 443)):
            return value
    except ValueError:
        pass
    return None


def _retry_seconds(value):
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            seconds = (dt - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = 60.0
    return max(1.0, seconds) if math.isfinite(seconds) else 60.0


def normalize_best_buy_product(row):
    if not isinstance(row, dict):
        return None
    sku = str(row.get("sku", ""))
    title = row.get("name")
    if not sku.isdigit() or not isinstance(title, str) or not title.strip():
        return None
    if row.get("active") is not True or row.get("type") not in {"hardgood", "bundle"}:
        return None
    if row.get("preowned") is True or row.get("secondaryMarket") is True:
        return None
    taxonomy = " ".join(str(c.get("name", "")) for c in row.get("categoryPath", [])
                        if isinstance(c, dict)) if isinstance(row.get("categoryPath"), list) else ""
    if not re.search(r"trading cards?|\btcg\b|booster|starter deck|elite trainer", title+" "+taxonomy, re.I):
        return None
    games = [name for name, pattern in GAMES if re.search(pattern, title, re.I)]
    if len(games) != 1:
        return None
    url = _safe_url(row.get("url"), {"www.bestbuy.com", "bestbuy.com", "api.bestbuy.com"})
    if not url:
        return None
    parsed_url = urlparse(url)
    if any(k.lower() in {"apikey", "api_key"} for k, _ in parse_qsl(parsed_url.query)):
        return None
    if parsed_url.hostname == "api.bestbuy.com" and not re.fullmatch(r"/click/[^/]+/[0-9]+/pdp", parsed_url.path):
        return None
    price = row.get("salePrice")
    if isinstance(price, bool):
        price = None
    try:
        price = float(price)
        if not math.isfinite(price) or price <= 0:
            price = None
    except (TypeError, ValueError):
        price = None
    restriction = str(row.get("priceRestriction") or "").strip()
    if restriction:
        price = None
    candidate = row.get("onlineAvailability")
    candidate = candidate if type(candidate) is bool else None
    state = "IN_STOCK" if candidate is True else "OUT_OF_STOCK" if candidate is False else "UNKNOWN"
    # Signals are retained as candidates only; API semantics and freshness still
    # require live validation. In-store availability never supplies online stock.
    category = "ACCESSORIES" if re.search(r"sleeves?|binder|playmat|deck box|portfolio", title, re.I) else "SEALED"
    return MajorRetailerProduct(
        retailer_key="best_buy", external_product_id=sku, sku=sku,
        title=title.strip(), game=games[0], url=url, price=price, currency="USD",
        availability_state="UNKNOWN", availability_known=False,
        availability_confidence="UNKNOWN", lifecycle_state="PAGE_LIVE",
        lifecycle_confidence="MEDIUM", product_category=category,
        product_type="Accessory" if category == "ACCESSORIES" else "TCG Product",
        product_family="UNKNOWN",
        image_url=_safe_url(row.get("image"), {"pisces.bbystatic.com", "images.bestbuy.com", "www.bestbuy.com"}),
        source_name="BestBuyProductsAPI", source_confidence="MEDIUM",
        extra={"validation_only": True, "stock_signal_verified": False,
               "local_inventory_verified": False,
               "best_buy_online_availability_candidate": state,
               "best_buy_online_availability_updated_at": row.get("onlineAvailabilityUpdateDate"),
               "best_buy_orderable_candidate": row.get("orderable"),
               "best_buy_release_date_candidate": row.get("releaseDate"),
               "best_buy_price_restricted": bool(restriction)},
    )


@major_retailer_adapter("best_buy")
class BestBuyMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "best_buy"
    version = "1.0.6-6K3B"

    @property
    def capabilities(self):
        return MajorRetailerCapabilityProfile(discovery=True, price=True, page_live=True)

    def _reset(self):
        self.diagnostics = {"integration_state": "VALIDATION_ONLY", "step": STEP,
                            "requests": 0, "accepted": 0, "rejected": 0,
                            "last_error": None, "partial": False,
                            "online_availability_verified": False}

    async def _request(self, session, expression, *, page=1, page_size=100):
        global _NEXT_REQUEST_AT
        key = os.getenv("BESTBUY_API_KEY", "").strip()
        if not key:
            raise BestBuyAPIError("BESTBUY_API_KEY_MISSING")
        async with _REQUEST_LOCK:
            wait = _NEXT_REQUEST_AT - time.monotonic()
            if wait > 2:
                raise BestBuyAPIError("BESTBUY_COOLDOWN_ACTIVE")
            if wait > 0:
                await asyncio.sleep(wait)
            _NEXT_REQUEST_AT = time.monotonic() + 1.0
            self.diagnostics["requests"] += 1
            try:
                async with session.get(
                    API_ROOT + expression,
                    params={"apiKey": key, "format": "json", "show": FIELDS,
                            "pageSize": page_size, "page": page, "sort": "sku.asc"},
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        if response.status == 429:
                            _NEXT_REQUEST_AT = time.monotonic() + _retry_seconds(response.headers.get("Retry-After"))
                        elif response.status >= 500:
                            _NEXT_REQUEST_AT = time.monotonic() + 30
                        raise BestBuyAPIError(f"BESTBUY_HTTP_{response.status}", response.status)
                    # Bound response size; never log the canonicalUrl (contains key).
                    chunks = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        chunks.extend(chunk)
                        if len(chunks) > 4 * 1024 * 1024:
                            raise BestBuyAPIError("BESTBUY_RESPONSE_TOO_LARGE")
                    import json
                    try:
                        data = json.loads(chunks)
                    except (ValueError, UnicodeError):
                        raise BestBuyAPIError("BESTBUY_INVALID_JSON") from None
                    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
                        raise BestBuyAPIError("BESTBUY_INVALID_SCHEMA")
                    if data.get("partial") is not False:
                        raise BestBuyAPIError("BESTBUY_PARTIAL_OR_UNVERIFIED_RESPONSE")
                    return data
            except asyncio.CancelledError:
                raise
            except BestBuyAPIError:
                raise
            except Exception:
                raise BestBuyAPIError("BESTBUY_TRANSPORT_ERROR") from None

    def _session(self):
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                                     headers={"User-Agent": "LotusTracker/1.0.6 BestBuyValidation", "Accept": "application/json"})

    async def healthcheck(self):
        self._reset()
        try:
            async with self._session() as session:
                await self._request(session, "(search=trading&search=cards)", page_size=1)
            return MajorRetailerProbe(self.retailer_key, True, "BestBuyProductsAPI", "MEDIUM", 200,
                                      "BESTBUY_API_REACHABLE_VALIDATION_ONLY", self.get_diagnostics())
        except BestBuyAPIError as error:
            self.diagnostics["last_error"] = str(error)
            return MajorRetailerProbe(self.retailer_key, False, "BestBuyProductsAPI", "LOW", error.status,
                                      str(error), self.get_diagnostics())

    async def discover_products(self, *, limit=50):
        self._reset()
        limit = max(1, min(int(limit), 100))
        products = {}
        try:
            async with self._session() as session:
                for page in range(1, 4):
                    data = await self._request(session, "(search=trading&search=cards)", page=page)
                    for row in data["products"]:
                        product = normalize_best_buy_product(row)
                        if product is None:
                            self.diagnostics["rejected"] += 1
                        else:
                            products.setdefault(product.external_product_id, product)
                    total_pages = data.get("totalPages")
                    if type(total_pages) is not int or total_pages < 0:
                        raise BestBuyAPIError("BESTBUY_INVALID_PAGINATION")
                    more = page < total_pages
                    self.diagnostics["discovery_truncated"] = more or len(products) > limit
                    if len(products) >= limit or not more:
                        break
            result = list(products.values())[:limit]
            self.diagnostics["accepted"] = len(result)
            return result
        except BestBuyAPIError as error:
            self.diagnostics["last_error"] = str(error)
            self.diagnostics["partial"] = True
            # A failed scan must not become an apparently healthy empty snapshot.
            raise

    async def refresh_products(self, product_ids):
        self._reset()
        ids = list(dict.fromkeys(str(value).strip() for value in product_ids))
        if any(not re.fullmatch(r"[0-9]{1,12}", sku) for sku in ids) or len(ids) > 100:
            raise BestBuyAPIError("BESTBUY_INVALID_SKU_BATCH")
        if not ids:
            return []
        products = {}
        async with self._session() as session:
            for offset in range(0, len(ids), 20):
                data = await self._request(session, "(sku in("+",".join(ids[offset:offset+20])+"))")
                for row in data["products"]:
                    product = normalize_best_buy_product(row)
                    if product is not None and product.external_product_id in ids:
                        products[product.external_product_id] = product
        self.diagnostics["accepted"] = len(products)
        return list(products.values())
