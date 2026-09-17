"""
Lotus Tracker Bot / PonDeX Trackers
Magento 2 / Adobe Commerce Universal Retailer Adapter
Version 1.0.0

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


VERSION = "1.0.0"
USER_AGENT = "LotusTracker/1.0.4 (PonDeX Trackers; public Magento catalog monitor)"
DEFAULT_TIMEOUT = 18
DEFAULT_REQUEST_DELAY = 0.35
MAX_RESPONSE_BYTES = 8_000_000
DEFAULT_PAGE_SIZE = 24
DEFAULT_MAX_PAGES_PER_SEARCH = 2

# Searches are intentionally tied to games Lotus supports. Results still pass
# strict title classification, so a broad Magento search match is not accepted
# merely because it appeared in a response.
DEFAULT_SEARCH_TERMS = (
    "pokemon tcg",
    "one piece card game",
    "gundam card game",
    "dragon ball fusion world",
    "riftbound",
    "palworld card game",
    "naruto card game",
    "cyberpunk tcg",
    "azuki tcg",
    "hellbreak tcg",
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
            "graphql_endpoint": self.graphql_url,
            "graphql_requests": 0,
            "graphql_successful": 0,
            "graphql_errors": 0,
            "searches_attempted": 0,
            "searches_completed": 0,
            "pages_checked": 0,
            "pages_successful": 0,
            "raw_products_seen": 0,
            "products_deduplicated": 0,
            "products_accepted": 0,
            "products_rejected": 0,
            "missing_prices": 0,
            "unknown_availability": 0,
            "in_stock_products": 0,
            "out_of_stock_products": 0,
            "last_http_status": None,
            "last_error": None,
            "network_transport": "IPV4_ONLY",
        }

    def get_diagnostics(self) -> dict[str, Any]:
        return dict(self.diagnostics)

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        length = response.headers.get("Content-Length")
        if length:
            try:
                if int(length) > MAX_RESPONSE_BYTES:
                    raise ValueError("MAGENTO_GRAPHQL_BODY_TOO_LARGE")
            except (TypeError, ValueError) as error:
                if str(error) == "MAGENTO_GRAPHQL_BODY_TOO_LARGE":
                    raise

        raw = await response.content.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("MAGENTO_GRAPHQL_BODY_TOO_LARGE")
        payload = json.loads(raw.decode("utf-8-sig", errors="replace"))
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
        self.diagnostics["graphql_requests"] += 1
        self.diagnostics["pages_checked"] += 1
        try:
            async with session.post(
                self.graphql_url,
                json={
                    "query": CATALOG_QUERY,
                    "variables": {
                        "search": search,
                        "pageSize": self.page_size,
                        "currentPage": current_page,
                    },
                },
                allow_redirects=False,
            ) as response:
                self.diagnostics["last_http_status"] = int(response.status)
                if response.status != 200:
                    self.diagnostics["graphql_errors"] += 1
                    self.diagnostics["last_error"] = f"GRAPHQL_HTTP_{response.status}"
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
                self.diagnostics["last_error"] = (
                    "GRAPHQL_ERRORS:" + " | ".join(messages[:3])
                    if messages
                    else "GRAPHQL_PRODUCTS_MISSING"
                )
                return None

            self.diagnostics["graphql_successful"] += 1
            self.diagnostics["pages_successful"] += 1
            return products
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.diagnostics["graphql_errors"] += 1
            self.diagnostics["last_error"] = f"{type(error).__name__}:{error}"
            return None

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
                        break

                    search_completed = True
                    items = products.get("items") or []
                    if not isinstance(items, list):
                        break

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
        return list(collected.values())

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
