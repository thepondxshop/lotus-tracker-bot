"""
Lotus Tracker Bot / PonDeX Trackers
LinkConnector Official Product Feed Client
Version 1.0.0

Step 6J-3F12 — Official Product Feed / Hybrid Retailer Source

Uses LinkConnector's documented Affiliate Product Feed APIs only.
No merchant/admin credentials, checkout actions, scraping bypasses, or cart mutation.

Miniature Market stock is intentionally NOT inferred from LinkConnector's stock
endpoint: LinkConnector currently documents that endpoint as limited to selected
products for a different merchant. Feed products therefore advertise
DISCOVERY_PRICE_ONLY capability until a separately verified stock source exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp


VERSION = "1.0.0"
API_URL = "https://www.linkconnector.com/api/"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_CACHE_SECONDS = 300
DEFAULT_ROWS_PER_CALL = 50
DEFAULT_PAGES_PER_KEYWORD = 2
DEFAULT_MAX_PRODUCTS = 600
DEFAULT_CONCURRENCY = 4

DEFAULT_KEYWORDS = (
    "Pokemon",
    "One Piece",
    "Gundam",
    "Fusion World",
    "Riftbound",
    "Palworld",
    "Naruto",
    "Cyberpunk",
    "Azuki",
    "Hellbreak",
)


# ---------------------------------------------------------------------------
# Module cache survives the short-lived adapter objects created by each scan.
# This keeps the universal monitor from making a complete official-feed request
# set every 60 seconds when it performs sharded known-product refreshes.
# ---------------------------------------------------------------------------
_FEED_CACHE: dict[str, tuple[float, list[dict[str, Any]], dict[str, Any]]] = {}
_MERCHANT_CACHE: dict[str, tuple[float, str | None, dict[str, Any]]] = {}
_CACHE_LOCK = asyncio.Lock()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError, AttributeError):
        value = default
    return max(minimum, min(maximum, value))


def _positive_price(value: Any) -> float | None:
    raw = _clean(value).replace("$", "").replace(",", "")
    if not raw:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _looks_like_record(value: Any, expected_fields: set[str]) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key).lower() for key in value.keys()}
    expected = {field.lower() for field in expected_fields}
    return bool(keys & expected)


def _extract_records(payload: Any, expected_fields: set[str]) -> list[dict[str, Any]]:
    """Tolerantly extract records from LinkConnector JSON wrappers."""
    output: list[dict[str, Any]] = []
    seen_objects: set[int] = set()

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(value, dict):
            object_id = id(value)
            if object_id in seen_objects:
                return
            seen_objects.add(object_id)
            if _looks_like_record(value, expected_fields):
                output.append(dict(value))
                return
            for nested in value.values():
                if isinstance(nested, (dict, list, tuple)):
                    walk(nested, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item, depth + 1)

    walk(payload)
    return output


def _value_ci(row: dict[str, Any], *names: str) -> Any:
    wanted = {name.lower() for name in names}
    for key, value in row.items():
        if str(key).lower() in wanted:
            return value
    return None


@dataclass
class LinkConnectorProbeResult:
    provider: str = "linkconnector"
    enabled: bool = False
    configured: bool = False
    api_key_configured: bool = False
    merchant_id: str | None = None
    merchant_name: str | None = None
    merchant_catalog_found: bool = False
    sample_products: int = 0
    sample_price_hits: int = 0
    stock_capability_verified: bool = False
    cache_hit: bool = False
    api_calls: int = 0
    last_error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "configured": self.configured,
            "api_key_configured": self.api_key_configured,
            "merchant_id": self.merchant_id,
            "merchant_name": self.merchant_name,
            "merchant_catalog_found": self.merchant_catalog_found,
            "sample_products": self.sample_products,
            "sample_price_hits": self.sample_price_hits,
            "stock_capability_verified": self.stock_capability_verified,
            "cache_hit": self.cache_hit,
            "api_calls": self.api_calls,
            "last_error": self.last_error,
            "notes": list(self.notes),
        }


class LinkConnectorProductFeed:
    provider = "linkconnector"

    def __init__(
        self,
        *,
        merchant_name: str,
        merchant_id_env: str | None = None,
        enabled_env: str | None = None,
    ) -> None:
        self.merchant_name = _clean(merchant_name)
        self.merchant_id_env = _clean(merchant_id_env) or None
        self.enabled_env = _clean(enabled_env) or None

        self.api_key = _clean(os.getenv("LINKCONNECTOR_API_KEY"))
        self.affiliate_id = _clean(os.getenv("LINKCONNECTOR_AFFILIATE_ID"))
        self.affiliate_track = _clean(
            os.getenv("LINKCONNECTOR_AFFILIATE_TRACK", "lotus-tracker")
        )

        configured_merchant_id = (
            _clean(os.getenv(self.merchant_id_env))
            if self.merchant_id_env
            else ""
        )
        self.configured_merchant_id = configured_merchant_id or None

        # An explicit false disables the source. If unset, providing the API key
        # is enough to make the integration available for probing/scan use.
        self.enabled = (
            _env_bool(self.enabled_env, default=bool(self.api_key))
            if self.enabled_env
            else bool(self.api_key)
        )

        self.cache_seconds = _env_int(
            "LINKCONNECTOR_FEED_CACHE_SECONDS",
            DEFAULT_CACHE_SECONDS,
            60,
            3600,
        )
        self.pages_per_keyword = _env_int(
            "LINKCONNECTOR_FEED_PAGES_PER_KEYWORD",
            DEFAULT_PAGES_PER_KEYWORD,
            1,
            10,
        )
        self.max_products = _env_int(
            "LINKCONNECTOR_FEED_MAX_PRODUCTS",
            DEFAULT_MAX_PRODUCTS,
            50,
            3000,
        )
        self.concurrency = _env_int(
            "LINKCONNECTOR_FEED_CONCURRENCY",
            DEFAULT_CONCURRENCY,
            1,
            8,
        )
        self.timeout_seconds = _env_int(
            "LINKCONNECTOR_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
            5,
            60,
        )

        self.diagnostics: dict[str, Any] = {}
        self._reset_diagnostics()

    def _reset_diagnostics(self) -> None:
        self.diagnostics = {
            "official_feed_provider": self.provider,
            "official_feed_enabled": bool(self.enabled),
            "official_feed_configured": bool(self.api_key),
            "official_feed_active": False,
            "official_feed_cache_hit": False,
            "official_feed_merchant_id": self.configured_merchant_id,
            "official_feed_catalogs_seen": 0,
            "official_feed_api_calls": 0,
            "official_feed_search_calls": 0,
            "official_feed_rows_seen": 0,
            "official_feed_rows_deduped": 0,
            "official_feed_products": 0,
            "official_feed_price_hits": 0,
            "official_feed_stock_hits": 0,
            "official_feed_keywords_completed": 0,
            "official_feed_truncated": False,
            "official_feed_last_error": None,
        }

    def get_diagnostics(self) -> dict[str, Any]:
        return dict(self.diagnostics)

    def _cache_identity(self, merchant_id: str | None) -> str:
        secret_fingerprint = _hash_token(self.api_key) if self.api_key else "nokey"
        return "|".join(
            (
                secret_fingerprint,
                _clean(merchant_id).lower(),
                self.merchant_name.lower(),
                self.affiliate_id,
                self.affiliate_track,
                str(self.pages_per_keyword),
                str(self.max_products),
            )
        )

    async def _request_json(
        self,
        session: aiohttp.ClientSession,
        *,
        function: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        request_params: dict[str, Any] = {
            "Key": self.api_key,
            "Function": function,
            "Format": "JSON",
        }
        for key, value in (params or {}).items():
            if value is None or value == "":
                continue
            request_params[key] = value

        self.diagnostics["official_feed_api_calls"] += 1
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

        try:
            async with session.get(
                API_URL,
                params=request_params,
                timeout=timeout,
                allow_redirects=True,
                headers={
                    "Accept": "application/json,text/plain;q=0.8,*/*;q=0.5",
                    "User-Agent": "LotusTracker/1.0.4 (PonDeX Trackers; official product feed)",
                },
            ) as response:
                if response.status >= 400:
                    raise RuntimeError(f"LINKCONNECTOR_HTTP_{response.status}")

                # Some APIs return JSON with a non-standard content-type; allow
                # aiohttp to decode by content rather than requiring the header.
                try:
                    return await response.json(content_type=None)
                except Exception:
                    text = await response.text(errors="replace")
                    raise RuntimeError(
                        f"LINKCONNECTOR_INVALID_JSON_HTTP_{response.status}_BYTES_{len(text)}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.diagnostics["official_feed_last_error"] = (
                f"{type(error).__name__}:{error}"
            )[:240]
            raise

    async def _discover_merchant_id(
        self,
        session: aiohttp.ClientSession,
    ) -> tuple[str | None, dict[str, Any] | None]:
        if self.configured_merchant_id:
            self.diagnostics["official_feed_merchant_id"] = self.configured_merchant_id
            return self.configured_merchant_id, None

        merchant_cache_key = "|".join(
            (
                _hash_token(self.api_key) if self.api_key else "nokey",
                self.merchant_name.lower(),
            )
        )
        now = time.monotonic()

        async with _CACHE_LOCK:
            cached = _MERCHANT_CACHE.get(merchant_cache_key)
            if cached and cached[0] > now:
                merchant_id, catalog = cached[1], dict(cached[2])
                self.diagnostics["official_feed_cache_hit"] = True
                self.diagnostics["official_feed_merchant_id"] = merchant_id
                return merchant_id, catalog

        payload = await self._request_json(
            session,
            function="getFeedProductPullCatalogs",
        )
        catalogs = _extract_records(
            payload,
            {"MerchantID", "Merchant", "ProductsCnt", "PullAPI_URL"},
        )
        self.diagnostics["official_feed_catalogs_seen"] = len(catalogs)

        target = self.merchant_name.lower().replace("&", "and")
        chosen: dict[str, Any] | None = None
        for catalog in catalogs:
            merchant = _clean(_value_ci(catalog, "Merchant", "MerchantName"))
            normalized = merchant.lower().replace("&", "and")
            if normalized == target:
                chosen = catalog
                break
        if chosen is None:
            for catalog in catalogs:
                merchant = _clean(_value_ci(catalog, "Merchant", "MerchantName"))
                normalized = merchant.lower().replace("&", "and")
                if target in normalized or normalized in target:
                    chosen = catalog
                    break

        merchant_id = (
            _clean(_value_ci(chosen, "MerchantID", "MerchantId"))
            if chosen
            else ""
        ) or None
        self.diagnostics["official_feed_merchant_id"] = merchant_id

        async with _CACHE_LOCK:
            _MERCHANT_CACHE[merchant_cache_key] = (
                now + self.cache_seconds,
                merchant_id,
                dict(chosen or {}),
            )

        return merchant_id, chosen

    async def _search_keyword(
        self,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        *,
        merchant_id: str,
        keyword: str,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        pages = max_pages or self.pages_per_keyword

        for page in range(pages):
            row_start = page * DEFAULT_ROWS_PER_CALL
            params: dict[str, Any] = {
                "RowsPerCall": DEFAULT_ROWS_PER_CALL,
                "RowStart": row_start,
                "KeywordSearch": keyword,
                "SortField": "Title",
                "SortDirection": "ASC",
                "MerchantIDs": merchant_id,
                "ImageSizePreference": "Image",
            }
            if self.affiliate_id:
                params["AffiliateID"] = self.affiliate_id
            if self.affiliate_track:
                params["AffiliateTrack"] = self.affiliate_track

            async with semaphore:
                payload = await self._request_json(
                    session,
                    function="getFeedProductSearch",
                    params=params,
                )
            self.diagnostics["official_feed_search_calls"] += 1

            page_rows = _extract_records(
                payload,
                {"Title", "Price", "MerchantID", "ProductID", "URL"},
            )
            rows.extend(page_rows)
            self.diagnostics["official_feed_rows_seen"] += len(page_rows)

            if len(page_rows) < DEFAULT_ROWS_PER_CALL:
                break

        self.diagnostics["official_feed_keywords_completed"] += 1
        return rows

    @staticmethod
    def _normalize_feed_row(row: dict[str, Any]) -> dict[str, Any] | None:
        title = _clean(_value_ci(row, "Title", "Product", "Name"))
        product_url = _clean(_value_ci(row, "URL", "ProductURL", "Link"))
        product_id = _clean(_value_ci(row, "ProductID", "ProductId", "ID"))
        merchant_id = _clean(_value_ci(row, "MerchantID", "MerchantId"))
        description = _clean(_value_ci(row, "Description"))
        promo = _clean(_value_ci(row, "Promo", "Promotion"))
        image_url = _clean(_value_ci(row, "ImageURL", "ImageUrl", "Image")) or None
        price = _positive_price(_value_ci(row, "Price"))

        if not title or not product_url:
            return None
        if not product_url.lower().startswith(("http://", "https://")):
            return None

        return {
            "title": title,
            "url": product_url,
            "price": price,
            "currency": "USD",
            "available": False,
            "availability_known": False,
            "availability_state": "UNKNOWN",
            "availability_source": "LINKCONNECTOR_PRODUCT_FEED_NO_VERIFIED_STOCK",
            "image_url": image_url,
            "sku": None,
            "external_product_id": product_id or None,
            "product_id": product_id or None,
            "merchant_id": merchant_id or None,
            "description": description,
            "promo": promo,
            "text": " ".join(part for part in (title, description, promo) if part),
            "source": "LINKCONNECTOR_PRODUCT_FEED",
            "official_feed_provider": "linkconnector",
            "official_feed": True,
            # Stock capability is deliberately false for Miniature Market until
            # a separately verified source can establish inventory state.
            "stock_capability_verified": False,
        }

    async def fetch_products(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        self._reset_diagnostics()

        if not self.enabled:
            self.diagnostics["official_feed_last_error"] = "OFFICIAL_FEED_DISABLED"
            return []
        if not self.api_key:
            self.diagnostics["official_feed_last_error"] = "LINKCONNECTOR_API_KEY_NOT_CONFIGURED"
            return []

        connector = aiohttp.TCPConnector(limit=6, limit_per_host=6)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                merchant_id, _catalog = await self._discover_merchant_id(session)
            except asyncio.CancelledError:
                raise
            except Exception:
                return []

            if not merchant_id:
                self.diagnostics["official_feed_last_error"] = (
                    "MINIATURE_MARKET_PRODUCT_CATALOG_NOT_AVAILABLE_TO_THIS_LINKCONNECTOR_ACCOUNT"
                )
                return []

            cache_key = self._cache_identity(merchant_id)
            now = time.monotonic()
            if not force_refresh:
                async with _CACHE_LOCK:
                    cached = _FEED_CACHE.get(cache_key)
                    if cached and cached[0] > now:
                        products = [dict(item) for item in cached[1]]
                        cached_diag = dict(cached[2])
                        self.diagnostics.update(cached_diag)
                        self.diagnostics["official_feed_cache_hit"] = True
                        self.diagnostics["official_feed_active"] = bool(products)
                        return products

            semaphore = asyncio.Semaphore(self.concurrency)
            try:
                batches = await asyncio.gather(
                    *(
                        self._search_keyword(
                            session,
                            semaphore,
                            merchant_id=merchant_id,
                            keyword=keyword,
                        )
                        for keyword in DEFAULT_KEYWORDS
                    ),
                    return_exceptions=False,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                return []

        deduped: dict[str, dict[str, Any]] = {}
        for batch in batches:
            for raw in batch:
                item = self._normalize_feed_row(raw)
                if item is None:
                    continue
                key = (
                    _clean(item.get("external_product_id"))
                    or _clean(item.get("url"))
                )
                if not key:
                    continue
                # Prefer the row with a usable price/image when a keyword search
                # returns the same product more than once.
                existing = deduped.get(key)
                if existing is None:
                    deduped[key] = item
                    continue
                if existing.get("price") is None and item.get("price") is not None:
                    existing["price"] = item.get("price")
                if not existing.get("image_url") and item.get("image_url"):
                    existing["image_url"] = item.get("image_url")
                if len(_clean(item.get("text"))) > len(_clean(existing.get("text"))):
                    existing["text"] = item.get("text")

        products = list(deduped.values())
        products.sort(key=lambda item: _clean(item.get("title")).lower())
        self.diagnostics["official_feed_rows_deduped"] = len(products)

        if len(products) > self.max_products:
            products = products[: self.max_products]
            self.diagnostics["official_feed_truncated"] = True

        self.diagnostics["official_feed_products"] = len(products)
        self.diagnostics["official_feed_price_hits"] = sum(
            1 for item in products if item.get("price") is not None
        )
        # Deliberately 0 until a verified stock source is available.
        self.diagnostics["official_feed_stock_hits"] = 0
        self.diagnostics["official_feed_active"] = bool(products)

        cache_diag = dict(self.diagnostics)
        cache_diag["official_feed_cache_hit"] = False
        async with _CACHE_LOCK:
            _FEED_CACHE[cache_key] = (
                time.monotonic() + self.cache_seconds,
                [dict(item) for item in products],
                cache_diag,
            )

        return products

    async def probe(self) -> LinkConnectorProbeResult:
        result = LinkConnectorProbeResult(
            enabled=bool(self.enabled),
            configured=bool(self.enabled and self.api_key),
            api_key_configured=bool(self.api_key),
            merchant_id=self.configured_merchant_id,
            merchant_name=self.merchant_name,
            stock_capability_verified=False,
        )

        if not self.enabled:
            result.last_error = "OFFICIAL_FEED_DISABLED"
            return result
        if not self.api_key:
            result.last_error = "LINKCONNECTOR_API_KEY_NOT_CONFIGURED"
            return result

        self._reset_diagnostics()
        connector = aiohttp.TCPConnector(limit=3, limit_per_host=3)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                merchant_id, catalog = await self._discover_merchant_id(session)
                result.merchant_id = merchant_id
                result.merchant_catalog_found = bool(merchant_id)
                if catalog:
                    merchant_name = _clean(_value_ci(catalog, "Merchant", "MerchantName"))
                    if merchant_name:
                        result.merchant_name = merchant_name

                if not merchant_id:
                    result.last_error = (
                        "MINIATURE_MARKET_PRODUCT_CATALOG_NOT_AVAILABLE_TO_THIS_LINKCONNECTOR_ACCOUNT"
                    )
                    result.api_calls = int(self.diagnostics["official_feed_api_calls"] or 0)
                    return result

                semaphore = asyncio.Semaphore(1)
                sample = await self._search_keyword(
                    session,
                    semaphore,
                    merchant_id=merchant_id,
                    keyword="Pokemon",
                    max_pages=1,
                )
                normalized = [
                    item
                    for item in (self._normalize_feed_row(row) for row in sample)
                    if item is not None
                ]
                result.sample_products = len(normalized)
                result.sample_price_hits = sum(
                    1 for item in normalized if item.get("price") is not None
                )
                result.notes.append(
                    "Stock alerts remain capability-gated because Miniature Market stock is not verified by this feed integration."
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                result.last_error = f"{type(error).__name__}:{error}"[:240]

        result.api_calls = int(self.diagnostics["official_feed_api_calls"] or 0)
        result.cache_hit = bool(self.diagnostics["official_feed_cache_hit"])
        if not result.last_error:
            result.last_error = self.diagnostics.get("official_feed_last_error")
        return result
