"""
Lotus Tracker Bot / PonDeX Trackers
Magento 2 / Adobe Commerce Universal Retailer Adapter
Version 1.0.6

Step 6J-4A — Public Magento Catalog Foundation

Safety:
- Public storefront homepage and public GraphQL catalog queries only.
- No customer tokens, admin APIs, credential guessing, cart mutations,
  checkout automation, CAPTCHA/queue bypass, or login automation.
- Bounded search terms, pages, page size, response size, and request pacing.
- Stock is trusted only from Magento's explicit ``stock_status`` field.
- Unknown stock never means sold out, and missing/non-positive prices remain
  unknown so they cannot create false price events.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from app.retailer_adapter import RetailerAdapter, RetailerProduct, normalize_price
from app.retailer_registry import retailer_adapter
from app.retailers.shopware_adapter import (
    classify_game,
    classify_product_category,
    classify_product_family,
    clean_text,
    infer_product_type,
)


VERSION = "1.0.6"

print(
    f"LOTUS MAGENTO ADAPTER | Version={VERSION} | "
    "Discovery=BROAD_GAME_SEARCH | BodyRead=COMPLETE_STREAM",
    flush=True,
)

USER_AGENT = f"LotusTracker/{VERSION} (PonDeX Trackers; public Magento catalog monitor)"
DEFAULT_TIMEOUT = 18
DEFAULT_REQUEST_DELAY = 0.35
MAX_RESPONSE_BYTES = 8_000_000
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES_PER_SEARCH = 3
MAX_GRAPHQL_ATTEMPTS = 3
GRAPHQL_RETRY_DELAY = 0.75

# Searches are intentionally tied to games Lotus supports. Results still pass
# strict title classification, so a broad Magento search match is not accepted
# merely because it appeared in a response.
DEFAULT_SEARCH_TERMS = (
    # Keep discovery searches broad. Some Magento search configurations treat
    # multi-word searches as strict AND queries even though a single game name
    # returns the correct catalog. Every result is still passed through Lotus's
    # strict supported-game and non-TCG-merchandise filters before acceptance.
    "pokemon",
    "one piece",
    "gundam",
    "dragon ball",
    "riftbound",
    "palworld",
    "naruto",
    "cyberpunk",
    "azuki",
    "hellbreak",
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
)

NON_TCG_MERCHANDISE = (
    re.compile(r"\bplush(?:ie|ies)?\b", re.I),
    re.compile(r"\bkey[\s-]*chain\b", re.I),
    re.compile(r"\bkeyring\b", re.I),
    re.compile(r"\bclip[\s-]*on\b", re.I),
    re.compile(r"\bfunko\b", re.I),
    re.compile(r"\bpop!(?:\s|$)", re.I),
    re.compile(r"\baction\s+figure\b", re.I),
    re.compile(r"\b(?:vinyl\s+figure|statue|doll|model\s+kit|gunpla)\b", re.I),
    re.compile(r"\b(?:t[\s-]*shirt|shirt|hoodie|sweatshirt|socks|blanket)\b", re.I),
    re.compile(r"\b(?:backpack|wallet|mug|lanyard)\b", re.I),
)

CATALOG_QUERY = """
query LotusPublicCatalog($search: String!, $pageSize: Int!, $currentPage: Int!) {
  products(search: $search, pageSize: $pageSize, currentPage: $currentPage) {
    total_count
    page_info { current_page total_pages page_size }
    items {
      sku
      name
      url_key
      url_rewrites { url }
      stock_status
      small_image { url }
      price_range {
        minimum_price {
          regular_price { value currency }
          final_price { value currency }
        }
      }
    }
  }
}
"""

FINGERPRINT_QUERY = """
query LotusMagentoFingerprint {
  products(search: "pokemon", pageSize: 1, currentPage: 1) {
    total_count
    items { sku name stock_status }
  }
}
"""


class MagentoIncompleteDiscoveryError(RuntimeError):
    """At least one requested catalog page failed; this is not an empty catalog."""


def _clean_domain(value: str) -> str:
    raw = str(value or "").strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    return str(parsed.netloc or parsed.path).strip().strip("/").lower()


def _positive_price(value: Any) -> float | None:
    price = normalize_price(value)
    if price is None or price <= 0:
        return None
    return price


def _price_from_item(item: dict[str, Any]) -> tuple[float | None, str, str]:
    minimum = (
        ((item.get("price_range") or {}).get("minimum_price") or {})
        if isinstance(item, dict)
        else {}
    )
    final_price = minimum.get("final_price") or {}
    regular_price = minimum.get("regular_price") or {}

    price = _positive_price(final_price.get("value"))
    source = "MAGENTO_GRAPHQL_FINAL_PRICE"
    currency = clean_text(final_price.get("currency")).upper()

    if price is None:
        price = _positive_price(regular_price.get("value"))
        source = "MAGENTO_GRAPHQL_REGULAR_PRICE"
        currency = clean_text(regular_price.get("currency")).upper()

    return price, currency or "USD", source if price is not None else "UNKNOWN"


def _availability_from_item(item: dict[str, Any]) -> tuple[bool, bool, str]:
    stock_status = clean_text(item.get("stock_status")).upper()
    if stock_status == "IN_STOCK":
        return True, True, "IN_STOCK"
    if stock_status == "OUT_OF_STOCK":
        return False, True, "OUT_OF_STOCK"
    return False, False, "UNKNOWN"


def _is_supported_tcg_product(title: str) -> bool:
    lowered = clean_text(title).lower()
    if not lowered or any(term in lowered for term in UNSUPPORTED_GAME_TERMS):
        return False
    return not any(pattern.search(title) for pattern in NON_TCG_MERCHANDISE)


@retailer_adapter("magento")
class MagentoAdapter(RetailerAdapter):
    platform = "magento"

    def __init__(
        self,
        *,
        domain: str,
        region: str = "US",
        store_name: str | None = None,
        search_terms: tuple[str, ...] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages_per_search: int = DEFAULT_MAX_PAGES_PER_SEARCH,
        request_delay: float = DEFAULT_REQUEST_DELAY,
    ) -> None:
        super().__init__(domain=domain, region=region, store_name=store_name)
        self.domain = _clean_domain(domain)
        self.base_url = f"https://{self.domain}"
        self.graphql_url = f"{self.base_url}/graphql"
        self.search_terms = tuple(search_terms or DEFAULT_SEARCH_TERMS)
        self.page_size = max(1, min(int(page_size), 50))
        self.max_pages_per_search = max(1, min(int(max_pages_per_search), 3))
        self.request_delay = max(0.0, float(request_delay))
        self.diagnostics: dict[str, Any] = {
            "adapter": "magento",
            "adapter_version": VERSION,
            "discovery_mode": "DIRECT_CATALOG_API",
            "graphql_endpoint": self.graphql_url,
            "graphql_requests": 0,
            "graphql_successful": 0,
            "graphql_errors": 0,
            "graphql_retries": 0,
            "graphql_retry_recoveries": 0,
            "searches_attempted": 0,
            "searches_completed": 0,
            "searches_failed": 0,
            "failed_searches": {},
            "discovery_complete": False,
            "pages_checked": 0,
            "pages_successful": 0,
            "raw_products_seen": 0,
            "catalog_products_discovered": 0,
            "empty_searches": 0,
            "search_result_counts": {},
            "products_deduplicated": 0,
            "products_accepted": 0,
            "products_rejected": 0,
            "rejection_samples": [],
            "missing_prices": 0,
            "unknown_availability": 0,
            "in_stock_products": 0,
            "out_of_stock_products": 0,
            "last_http_status": None,
            "last_error": None,
            "network_transport": "IPV4_ONLY",
        }

    def get_diagnostics(self) -> dict[str, Any]:
        diagnostics = dict(self.diagnostics)
        # The universal monitor uses this common field for rejection totals.
        diagnostics["rejected_products"] = diagnostics["products_rejected"]
        return diagnostics

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        """Read through EOF, with a hard limit on the decoded response bytes."""
        length = response.headers.get("Content-Length")
        if length:
            try:
                declared_length = int(length)
            except (TypeError, ValueError):
                declared_length = 0
            if declared_length > MAX_RESPONSE_BYTES:
                raise ValueError("MAGENTO_GRAPHQL_BODY_TOO_LARGE")

        # StreamReader.read(n) can return an early network fragment. A single
        # call is not a complete-body read, even with a large n or Content-Length.
        raw = bytearray()
        while True:
            chunk = await response.content.read(
                min(64 * 1024, MAX_RESPONSE_BYTES + 1 - len(raw))
            )
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("MAGENTO_GRAPHQL_BODY_TOO_LARGE")

        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("MAGENTO_GRAPHQL_INVALID_PAYLOAD")
        return payload

    @classmethod
    async def platform_probe(cls, domain_or_url: str) -> dict[str, Any]:
        """Confirm the public Magento product GraphQL schema without mutation."""
        domain = _clean_domain(domain_or_url)
        if not domain:
            return {"detected": False, "reason": "INVALID_DOMAIN"}

        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT, connect=8)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            limit=2,
            limit_per_host=1,
        )

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
                connector=connector,
                cookie_jar=aiohttp.DummyCookieJar(),
            ) as session:
                # Resolve the canonical public origin before POSTing. This
                # preserves POST semantics across www/non-www redirects.
                origin = f"https://{domain}"
                try:
                    async with session.get(origin + "/", allow_redirects=True) as home:
                        parsed = urlparse(str(home.url))
                        if parsed.scheme in {"http", "https"} and parsed.netloc:
                            origin = f"{parsed.scheme}://{parsed.netloc}"
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass

                endpoint = origin.rstrip("/") + "/graphql"
                async with session.post(
                    endpoint,
                    json={"query": FINGERPRINT_QUERY},
                    allow_redirects=False,
                ) as response:
                    status = int(response.status)
                    if status != 200:
                        return {
                            "detected": False,
                            "endpoint": endpoint,
                            "http_status": status,
                            "reason": f"HTTP_{status}",
                        }
                    payload = await cls._read_json(response)

                products = (payload.get("data") or {}).get("products")
                if isinstance(products, dict) and isinstance(products.get("items"), list):
                    return {
                        "detected": True,
                        "endpoint": endpoint,
                        "http_status": 200,
                        "reason": "PUBLIC_PRODUCTS_GRAPHQL_CONFIRMED",
                    }

                errors = payload.get("errors") or []
                return {
                    "detected": False,
                    "endpoint": endpoint,
                    "http_status": 200,
                    "reason": "GRAPHQL_SCHEMA_NOT_CONFIRMED",
                    "errors": [clean_text(item.get("message")) for item in errors if isinstance(item, dict)][:3],
                }
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return {
                "detected": False,
                "reason": f"{type(error).__name__}:{error}",
            }

    async def _resolve_origin(self, session: aiohttp.ClientSession) -> None:
        try:
            async with session.get(self.base_url + "/", allow_redirects=True) as response:
                parsed = urlparse(str(response.url))
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    self.base_url = f"{parsed.scheme}://{parsed.netloc}"
                    self.graphql_url = self.base_url.rstrip("/") + "/graphql"
                    self.diagnostics["graphql_endpoint"] = self.graphql_url
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.diagnostics["last_error"] = f"HOMEPAGE:{type(error).__name__}:{error}"

    async def _query_catalog(
        self,
        session: aiohttp.ClientSession,
        *,
        search: str,
        current_page: int,
    ) -> dict[str, Any] | None:
        self.diagnostics["pages_checked"] += 1
        request_body = {
            "query": CATALOG_QUERY,
            "variables": {
                "search": search,
                "pageSize": self.page_size,
                "currentPage": current_page,
            },
        }

        for attempt in range(1, MAX_GRAPHQL_ATTEMPTS + 1):
            self.diagnostics["graphql_requests"] += 1
            self.diagnostics["last_http_status"] = None
            try:
                async with session.post(
                    self.graphql_url,
                    json=request_body,
                    allow_redirects=False,
                ) as response:
                    status = int(response.status)
                    self.diagnostics["last_http_status"] = status
                    if status != 200:
                        if status in {408, 425, 429, 500, 502, 503, 504}:
                            raise RuntimeError(f"GRAPHQL_HTTP_{status}")
                        self.diagnostics["graphql_errors"] += 1
                        self._record_search_failure(search, current_page, f"GRAPHQL_HTTP_{status}")
                        return None
                    payload = await self._read_json(response)

                errors = payload.get("errors") or []
                products = (payload.get("data") or {}).get("products")
                if errors or not isinstance(products, dict):
                    self.diagnostics["graphql_errors"] += 1
                    messages = [
                        clean_text(item.get("message"))
                        for item in errors
                        if isinstance(item, dict)
                    ]
                    error_text = (
                        "GRAPHQL_ERRORS:" + " | ".join(messages[:3])
                        if messages
                        else "GRAPHQL_PRODUCTS_MISSING"
                    )
                    self._record_search_failure(search, current_page, error_text)
                    return None

                if not isinstance(products.get("items"), list):
                    self.diagnostics["graphql_errors"] += 1
                    self._record_search_failure(search, current_page, "GRAPHQL_ITEMS_INVALID")
                    return None

                # Validate pagination inside the request error boundary so a
                # malformed result cannot be counted as a successful page.
                total_count = int(products.get("total_count") or 0)
                page_info = products.get("page_info") or {}
                total_pages = int(page_info.get("total_pages") or 1)
                if total_count < 0 or total_pages < 1:
                    raise ValueError("MAGENTO_GRAPHQL_PAGINATION_INVALID")

                self.diagnostics["graphql_successful"] += 1
                self.diagnostics["pages_successful"] += 1
                if attempt > 1:
                    self.diagnostics["graphql_retry_recoveries"] += 1
                    print(
                        "MAGENTO GRAPHQL RETRY RECOVERED | "
                        f"Store={self.store_name} | Search={search} | "
                        f"Page={current_page} | Attempt={attempt}"
                    )
                if not self.diagnostics["failed_searches"]:
                    self.diagnostics["last_error"] = None
                return products
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.diagnostics["graphql_errors"] += 1
                error_text = f"{type(error).__name__}:{error}"
                if (
                    attempt >= MAX_GRAPHQL_ATTEMPTS
                    or str(error) == "MAGENTO_GRAPHQL_BODY_TOO_LARGE"
                ):
                    print(
                        "MAGENTO GRAPHQL RETRY EXHAUSTED | "
                        f"Store={self.store_name} | Search={search} | "
                        f"Page={current_page} | Error={type(error).__name__}:{error}"
                    )
                    self._record_search_failure(search, current_page, error_text)
                    return None

                self.diagnostics["graphql_retries"] += 1
                print(
                    "MAGENTO GRAPHQL RETRY | "
                    f"Store={self.store_name} | Search={search} | "
                    f"Page={current_page} | Attempt={attempt} | "
                    f"Error={type(error).__name__}:{error}"
                )
                await asyncio.sleep(GRAPHQL_RETRY_DELAY * attempt)

        return None

    def _record_search_failure(self, search: str, page: int, error: str) -> None:
        error = clean_text(error)[:500]
        self.diagnostics["failed_searches"][search] = {
            "page": page,
            "error": error,
            "http_status": self.diagnostics["last_http_status"],
        }
        self.diagnostics["searches_failed"] = len(self.diagnostics["failed_searches"])
        self.diagnostics["last_error"] = f"Search={search}; Page={page}; Error={error}"
        print(
            "MAGENTO SEARCH FAILED | "
            f"Store={self.store_name} | Search={search} | Page={page} | Error={error}",
            flush=True,
        )

    async def fetch_products(self) -> list[dict[str, Any]]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT, connect=8)
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            limit=3,
            limit_per_host=2,
        )
        collected: dict[str, dict[str, Any]] = {}

        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
            connector=connector,
            cookie_jar=aiohttp.DummyCookieJar(),
        ) as session:
            await self._resolve_origin(session)

            for search in self.search_terms:
                self.diagnostics["searches_attempted"] += 1
                search_completed = False

                for current_page in range(1, self.max_pages_per_search + 1):
                    products = await self._query_catalog(
                        session,
                        search=search,
                        current_page=current_page,
                    )
                    if products is None:
                        search_completed = False
                        break

                    search_completed = True
                    items = products.get("items") or []
                    if not isinstance(items, list):
                        break

                    if current_page == 1:
                        total_count = int(products.get("total_count") or 0)
                        self.diagnostics["search_result_counts"][search] = total_count
                        if total_count == 0:
                            self.diagnostics["empty_searches"] += 1

                    self.diagnostics["raw_products_seen"] += len(items)
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        identity = clean_text(item.get("sku")) or clean_text(item.get("url_key"))
                        if not identity:
                            continue
                        collected[identity.lower()] = item

                    page_info = products.get("page_info") or {}
                    total_pages = int(page_info.get("total_pages") or 1)
                    if not items or current_page >= total_pages:
                        break

                    if self.request_delay:
                        await asyncio.sleep(self.request_delay)

                if search_completed:
                    self.diagnostics["searches_completed"] += 1

                if self.request_delay:
                    await asyncio.sleep(self.request_delay)

        self.diagnostics["products_deduplicated"] = max(
            self.diagnostics["raw_products_seen"] - len(collected),
            0,
        )
        self.diagnostics["catalog_products_discovered"] = len(collected)
        # Complete means all requested pages within the configured scan limits
        # succeeded; it does not claim that an uncapped catalog was downloaded.
        self.diagnostics["discovery_complete"] = not self.diagnostics["failed_searches"]
        return list(collected.values())

    async def get_normalized_products(self) -> list[dict[str, Any]]:
        products = await super().get_normalized_products()
        print(
            "MAGENTO DISCOVERY SUMMARY | "
            f"Store={self.store_name} | "
            f"SearchCounts={self.diagnostics.get('search_result_counts')} | "
            f"Raw={self.diagnostics.get('raw_products_seen')} | "
            f"Catalog={self.diagnostics.get('catalog_products_discovered')} | "
            f"Accepted={self.diagnostics.get('products_accepted')} | "
            f"Rejected={self.diagnostics.get('products_rejected')} | "
            f"CompletedSearches={self.diagnostics['searches_completed']}/"
            f"{self.diagnostics['searches_attempted']} | "
            f"FailedSearches={self.diagnostics['failed_searches']} | "
            f"DiscoveryComplete={self.diagnostics['discovery_complete']}",
            flush=True,
        )
        if self.diagnostics["failed_searches"]:
            failed_pages = "; ".join(
                f"{search}[page={details['page']}]:{details['error']}"
                for search, details in self.diagnostics["failed_searches"].items()
            )
            # The existing monitor catches this before database updates or
            # event publication. Final activation validation remains blocked
            # with the actual failed search, rather than an empty-URL reason.
            raise MagentoIncompleteDiscoveryError(
                f"MAGENTO_DISCOVERY_INCOMPLETE:{failed_pages}"
            )
        return products

    def normalize_product(self, product: Any) -> RetailerProduct | None:
        if not isinstance(product, dict):
            self.diagnostics["products_rejected"] += 1
            return None

        title = clean_text(product.get("name"))
        sku = clean_text(product.get("sku")) or None
        url_key = clean_text(product.get("url_key")).strip("/")
        rewrites = product.get("url_rewrites") or []
        rewrite_url = ""
        if isinstance(rewrites, list):
            for rewrite in rewrites:
                if isinstance(rewrite, dict) and clean_text(rewrite.get("url")):
                    rewrite_url = clean_text(rewrite.get("url"))
                    break
        relative_url = rewrite_url or (f"{url_key}.html" if url_key else "")
        url = urljoin(self.base_url.rstrip("/") + "/", relative_url)
        if not title or not url:
            self.diagnostics["products_rejected"] += 1
            return None

        game = classify_game(title) if _is_supported_tcg_product(title) else None
        if not game:
            self.diagnostics["products_rejected"] += 1
            samples = self.diagnostics.get("rejection_samples")
            if isinstance(samples, list) and len(samples) < 20 and title:
                samples.append(title[:140])
            return None

        price, currency, price_source = _price_from_item(product)
        if price is None:
            self.diagnostics["missing_prices"] += 1

        available, availability_known, availability_state = _availability_from_item(product)
        if not availability_known:
            self.diagnostics["unknown_availability"] += 1
        elif available:
            self.diagnostics["in_stock_products"] += 1
        else:
            self.diagnostics["out_of_stock_products"] += 1

        category = classify_product_category(title)
        family = classify_product_family(title)
        product_state = {
            "IN_STOCK": "STOCK_AVAILABLE",
            "OUT_OF_STOCK": "SOLD_OUT",
        }.get(availability_state, "PAGE_LIVE")
        capability = (
            "FULL_AVAILABILITY"
            if availability_known
            else "DISCOVERY_PRICE_ONLY" if price is not None else "DISCOVERY_ONLY"
        )

        image = product.get("small_image") or {}
        image_url = clean_text(image.get("url")) if isinstance(image, dict) else ""
        external_id = sku or url_key
        platform_data = {
            "adapter": "magento",
            "adapter_version": VERSION,
            "source": "PUBLIC_MAGENTO_GRAPHQL",
            "availability_known": availability_known,
            "availability_state": availability_state,
            "availability_source": (
                "MAGENTO_GRAPHQL_STOCK_STATUS" if availability_known else "UNKNOWN"
            ),
            "availability_confidence": "HIGH" if availability_known else "LOW",
            "availability_capability": capability,
            "price_source": price_source,
        }

        self.diagnostics["products_accepted"] += 1
        print(
            "MAGENTO TCG ACCEPTED | "
            f"Store={self.store_name} | Game={game} | Category={category} | "
            f"Family={family} | Price={price} {currency} | "
            f"Availability={availability_state} | "
            f"AvailabilitySource={platform_data['availability_source']} | "
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
            product_type=infer_product_type(title),
            product_category=category,
            product_family=family,
            product_state=product_state,
            image_url=image_url or None,
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
