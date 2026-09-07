"""
Lotus Tracker Bot / PonDeX Trackers
Universal Retailer Platform Detector
Version: 1.0.1

Step 6J-3E3 — Automatic Retailer Platform Fingerprinting

Purpose:
- Detect the storefront platform before a universal retailer is staged.
- Distinguish WooCommerce, Square/Weebly, BigCommerce, PrestaShop,
  and Shopify using bounded public storefront signals.
- Treat Square payment references as weak evidence so a WooCommerce
  store that merely uses Square for payments is not misclassified.
- Return confidence + diagnostics so main.py can refuse ambiguous stores.

Safety:
- Public GET requests only.
- No login, authentication guessing, cart mutation, or checkout automation.
- No CAPTCHA / queue / anti-bot bypass.
- Bounded response reads, timeouts, redirects, and request count.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import aiohttp


VERSION = "1.0.2"
USER_AGENT = (
    "LotusTracker/1.0.4 "
    "(PonDeX Trackers; public retailer platform fingerprinting)"
)

REQUEST_TIMEOUT_SECONDS = 15
MAX_BODY_BYTES = 1_250_000
MAX_JSON_PROBE_BYTES = 8_000_000

AUTO_STAGE_PLATFORMS = {
    "square_weebly",
    "woocommerce",
    "bigcommerce",
    "prestashop",
}

PLATFORM_LABELS = {
    "square_weebly": "Square / Weebly",
    "woocommerce": "WooCommerce",
    "bigcommerce": "BigCommerce",
    "prestashop": "PrestaShop",
    "shopify": "Shopify",
    "unknown": "Unknown",
}


@dataclass
class PlatformFingerprintResult:
    domain: str
    platform: str
    confidence: str
    score: int
    runner_up_platform: str | None
    runner_up_score: int
    homepage_url: str | None
    homepage_status: int | None
    signals: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    signal_map: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def auto_stage_allowed(self) -> bool:
        return (
            self.platform in AUTO_STAGE_PLATFORMS
            and self.confidence in {"HIGH", "MEDIUM"}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "platform": self.platform,
            "confidence": self.confidence,
            "score": self.score,
            "runner_up_platform": self.runner_up_platform,
            "runner_up_score": self.runner_up_score,
            "homepage_url": self.homepage_url,
            "homepage_status": self.homepage_status,
            "signals": list(self.signals),
            "scores": dict(self.scores),
            "signal_map": {
                key: list(value)
                for key, value in self.signal_map.items()
            },
            "errors": list(self.errors),
            "auto_stage_allowed": self.auto_stage_allowed,
        }


def platform_display_name(platform: str | None) -> str:
    key = str(platform or "unknown").strip().lower()
    return PLATFORM_LABELS.get(key, key or "Unknown")


def normalize_domain(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path).strip().lower()

    if "@" in host:
        host = host.rsplit("@", 1)[-1]

    host = host.split(":", 1)[0]

    if host.startswith("www."):
        host = host[4:]

    return host.strip("./")


def _initial_scores() -> dict[str, int]:
    return {
        "woocommerce": 0,
        "square_weebly": 0,
        "bigcommerce": 0,
        "prestashop": 0,
        "shopify": 0,
    }


def _initial_signal_map() -> dict[str, list[str]]:
    return {
        "woocommerce": [],
        "square_weebly": [],
        "bigcommerce": [],
        "prestashop": [],
        "shopify": [],
    }


def _add_signal(
    scores: dict[str, int],
    signal_map: dict[str, list[str]],
    platform: str,
    points: int,
    signal: str,
) -> None:
    scores[platform] = scores.get(platform, 0) + max(int(points), 0)
    entries = signal_map.setdefault(platform, [])
    if signal not in entries:
        entries.append(signal)


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def score_homepage_signals(
    *,
    html: str,
    final_url: str | None,
    headers: dict[str, str] | None,
    scores: dict[str, int],
    signal_map: dict[str, list[str]],
) -> None:
    """Score only public storefront HTML/headers/final URL."""

    lowered = (html or "").lower()
    compact = re.sub(r"\s+", " ", lowered)
    final_lower = str(final_url or "").lower()
    headers_lower = {
        str(key).lower(): str(value).lower()
        for key, value in (headers or {}).items()
    }

    # -----------------------------------------------------
    # WooCommerce
    # -----------------------------------------------------
    if "wp-content/plugins/woocommerce" in lowered:
        _add_signal(
            scores,
            signal_map,
            "woocommerce",
            35,
            "WooCommerce plugin asset paths",
        )

    if _contains_any(
        lowered,
        (
            "woocommerce-page",
            "woocommerce-js",
            "woocommerce-layout",
            "wc-block-components",
            "wc-blocks",
        ),
    ):
        _add_signal(
            scores,
            signal_map,
            "woocommerce",
            25,
            "WooCommerce storefront classes/scripts",
        )

    if "woocommerce" in compact:
        _add_signal(
            scores,
            signal_map,
            "woocommerce",
            12,
            "WooCommerce text/code marker",
        )

    if "/wp-json/wc/" in lowered:
        _add_signal(
            scores,
            signal_map,
            "woocommerce",
            20,
            "WooCommerce REST/Store API reference",
        )

    # -----------------------------------------------------
    # Shopify
    # -----------------------------------------------------
    if "myshopify.com" in final_lower:
        _add_signal(
            scores,
            signal_map,
            "shopify",
            90,
            "Final storefront host is myshopify.com",
        )

    if _contains_any(
        lowered,
        (
            "cdn.shopify.com",
            "/cdn/shop/",
            "shopify.theme",
            "shopify.routes",
            "shopify-payment-button",
        ),
    ):
        _add_signal(
            scores,
            signal_map,
            "shopify",
            55,
            "Shopify storefront assets/runtime",
        )

    if "shopify" in compact:
        _add_signal(
            scores,
            signal_map,
            "shopify",
            15,
            "Shopify text/code marker",
        )

    # -----------------------------------------------------
    # BigCommerce
    # -----------------------------------------------------
    if re.search(r"cdn\d*\.bigcommerce\.com", lowered):
        _add_signal(
            scores,
            signal_map,
            "bigcommerce",
            70,
            "BigCommerce CDN assets",
        )

    if _contains_any(
        lowered,
        (
            "stencil-utils",
            "stencilbootstrap",
            "bigcommerce.com/stencil",
        ),
    ):
        _add_signal(
            scores,
            signal_map,
            "bigcommerce",
            45,
            "BigCommerce Stencil storefront runtime",
        )

    if "bigcommerce" in compact:
        _add_signal(
            scores,
            signal_map,
            "bigcommerce",
            18,
            "BigCommerce text/code marker",
        )

    # -----------------------------------------------------
    # PrestaShop
    # -----------------------------------------------------
    if re.search(
        r'<meta[^>]+name=["\']generator["\'][^>]+content=["\'][^"\']*prestashop',
        lowered,
    ) or re.search(
        r'<meta[^>]+content=["\'][^"\']*prestashop[^"\']*["\'][^>]+name=["\']generator',
        lowered,
    ):
        _add_signal(
            scores,
            signal_map,
            "prestashop",
            85,
            "PrestaShop generator meta tag",
        )

    if _contains_any(
        lowered,
        (
            "prestashop.page",
            "prestashop.urls",
            "var prestashop",
            "window.prestashop",
        ),
    ):
        _add_signal(
            scores,
            signal_map,
            "prestashop",
            55,
            "PrestaShop JavaScript runtime",
        )

    if "prestashop" in compact:
        _add_signal(
            scores,
            signal_map,
            "prestashop",
            20,
            "PrestaShop text/code marker",
        )

    if (
        "/modules/" in lowered
        and "/themes/" in lowered
        and "wp-content" not in lowered
    ):
        _add_signal(
            scores,
            signal_map,
            "prestashop",
            18,
            "PrestaShop-style modules + themes asset layout",
        )

    # -----------------------------------------------------
    # Square / Weebly
    # -----------------------------------------------------
    # Strong storefront evidence. These are materially different
    # from a generic Square payment badge.
    if _contains_any(
        lowered,
        (
            "cdn2.editmysite.com",
            "editmysite.com/js/",
            "weebly.com/uploads/",
            "weeblycloud.com",
        ),
    ):
        _add_signal(
            scores,
            signal_map,
            "square_weebly",
            80,
            "Weebly/EditMySite storefront assets",
        )

    if _contains_any(
        lowered,
        (
            "wsite-header",
            "wsite-menu",
            "wsite-elements",
            "wsite-com-product",
        ),
    ):
        _add_signal(
            scores,
            signal_map,
            "square_weebly",
            60,
            "Weebly wsite storefront markup",
        )

    if "square.site" in final_lower:
        _add_signal(
            scores,
            signal_map,
            "square_weebly",
            100,
            "Final storefront host is square.site",
        )

    if "square.site" in lowered:
        _add_signal(
            scores,
            signal_map,
            "square_weebly",
            45,
            "Square Online storefront reference",
        )

    if "weebly" in compact:
        _add_signal(
            scores,
            signal_map,
            "square_weebly",
            25,
            "Weebly text/code marker",
        )

    # Critical Carnage Cards safeguard:
    # Square may only be the payment processor. Payment-only references
    # intentionally receive too little weight to auto-classify a store.
    if _contains_any(
        compact,
        (
            "powered by square",
            "squareup.com",
            "square payments",
            "square payment",
        ),
    ):
        _add_signal(
            scores,
            signal_map,
            "square_weebly",
            5,
            "Square payment reference only (weak signal)",
        )

    # -----------------------------------------------------
    # Response headers
    # -----------------------------------------------------
    powered_by = headers_lower.get("x-powered-by", "")
    server = headers_lower.get("server", "")

    if "prestashop" in powered_by:
        _add_signal(
            scores,
            signal_map,
            "prestashop",
            70,
            "HTTP x-powered-by reports PrestaShop",
        )

    if "shopify" in powered_by or "shopify" in server:
        _add_signal(
            scores,
            signal_map,
            "shopify",
            35,
            "HTTP headers reference Shopify",
        )


def _confidence_for_scores(
    scores: dict[str, int],
) -> tuple[str, str, int, str | None, int]:
    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], item[0]),
    )

    top_platform, top_score = ranked[0]
    runner_platform, runner_score = ranked[1]
    margin = top_score - runner_score

    if top_score < 35:
        return "UNKNOWN", "unknown", top_score, runner_platform, runner_score

    if top_score >= 85 and margin >= 25:
        confidence = "HIGH"
    elif top_score >= 55 and margin >= 15:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return (
        confidence,
        top_platform,
        top_score,
        runner_platform,
        runner_score,
    )


async def _read_bounded_text(
    response: aiohttp.ClientResponse,
) -> str:
    raw = await response.content.read(MAX_BODY_BYTES)
    encoding = response.charset or "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


async def _fetch_homepage(
    session: aiohttp.ClientSession,
    domain: str,
) -> tuple[str | None, int | None, str, dict[str, str], list[str]]:
    errors: list[str] = []

    for scheme in ("https", "http"):
        url = f"{scheme}://{domain}/"
        try:
            async with session.get(
                url,
                allow_redirects=True,
            ) as response:
                text = await _read_bounded_text(response)
                headers = {
                    key: value
                    for key, value in response.headers.items()
                }
                return (
                    str(response.url),
                    int(response.status),
                    text,
                    headers,
                    errors,
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            errors.append(
                f"HOMEPAGE_{scheme.upper()}:{type(error).__name__}:{error}"
            )

    return None, None, "", {}, errors


async def _probe_json_endpoint(
    session: aiohttp.ClientSession,
    url: str,
) -> tuple[bool, Any, str | None]:
    """
    Fetch a public JSON endpoint conservatively.

    Step 6J-3E3.1 compatibility fix:
    - Uses a larger but still bounded JSON probe read. Some WooCommerce
      stores return unexpectedly large Store API responses even when
      `per_page=1` is requested. The old 1.25 MB detector limit could
      truncate valid JSON and report INVALID_JSON.
    - Handles UTF BOMs and unusual charset declarations.
    - Callers use a fresh DummyCookieJar session so homepage cookies do
      not influence REST/API fingerprint probes.
    """
    try:
        async with session.get(
            url,
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                return False, None, f"HTTP_{response.status}"

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_JSON_PROBE_BYTES:
                        return False, None, "JSON_BODY_TOO_LARGE"
                except (TypeError, ValueError):
                    pass

            raw = await response.content.read(
                MAX_JSON_PROBE_BYTES + 1
            )

            if len(raw) > MAX_JSON_PROBE_BYTES:
                return False, None, "JSON_BODY_TOO_LARGE"

            # Prefer the response charset when it is valid, otherwise
            # use UTF-8. UTF-8-SIG removes a leading BOM safely.
            charset = str(response.charset or "utf-8").lower()
            try:
                if charset in {"utf-8", "utf8"}:
                    text = raw.decode("utf-8-sig", errors="replace")
                else:
                    text = raw.decode(charset, errors="replace")
            except (LookupError, UnicodeError):
                text = raw.decode("utf-8-sig", errors="replace")

            text = text.lstrip("\ufeff").strip()

            # Some public endpoints prepend an anti-XSSI marker.
            if text.startswith(")]}'"):
                newline = text.find("\n")
                if newline >= 0:
                    text = text[newline + 1 :].lstrip()

            try:
                payload = json.loads(text)
                return True, payload, None
            except Exception:
                content_type = str(
                    response.headers.get("Content-Type") or "unknown"
                ).split(";", 1)[0]
                return (
                    False,
                    None,
                    f"INVALID_JSON_CONTENT_TYPE_{content_type}",
                )

    except asyncio.CancelledError:
        raise
    except Exception as error:
        return False, None, f"{type(error).__name__}:{error}"


async def _probe_woocommerce_with_production_adapter(
    base_url: str,
) -> tuple[bool, str | None, str | None]:
    """
    Probe WooCommerce using the exact production adapter logic.

    Step 6J-3E3.2:
    The fingerprint detector must not maintain a second, subtly different
    WooCommerce JSON implementation. Carnage Cards proved that the
    production adapter could successfully parse the public Store API while
    the standalone detector reported INVALID_JSON. This helper therefore
    delegates endpoint selection to WooCommerceAdapter itself.

    This performs public GET requests only and does not fetch a whole catalog.
    WooCommerceAdapter._select_store_api_path requests at most the two known
    public Store API product endpoints with per_page=1.
    """
    try:
        # Import lazily to avoid forcing retailer adapter imports during
        # module initialization and to keep detector startup lightweight.
        from app.retailers.woocommerce_adapter import (
            WooCommerceAdapter,
            USER_AGENT as WOO_USER_AGENT,
        )

        parsed = urlparse(base_url)
        domain = str(parsed.netloc or parsed.path or "").strip().strip("/")
        if not domain:
            return False, None, "INVALID_WOO_PROBE_DOMAIN"

        adapter = WooCommerceAdapter(
            domain=domain,
            region="US",
            store_name="Lotus Platform Fingerprint Probe",
            max_pages=1,
        )

        headers = {
            "User-Agent": WOO_USER_AGENT,
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        connector = aiohttp.TCPConnector(
            limit=4,
            limit_per_host=2,
        )

        async with aiohttp.ClientSession(
            headers=headers,
            connector=connector,
        ) as woo_session:
            path = await adapter._select_store_api_path(woo_session)

        if path:
            return True, str(path), None

        diagnostics = adapter.get_diagnostics()
        reason = str(
            diagnostics.get("last_error")
            or "PUBLIC_STORE_API_NOT_FOUND"
        )
        return False, None, reason

    except asyncio.CancelledError:
        raise
    except Exception as error:
        return (
            False,
            None,
            f"{type(error).__name__}:{error}",
        )


async def _probe_platform_apis(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    scores: dict[str, int],
    signal_map: dict[str, list[str]],
    errors: list[str],
) -> None:
    base_url = base_url.rstrip("/")

    # =====================================================
    # WooCommerce — production-adapter truth first
    # =====================================================
    #
    # If Lotus's real WooCommerce adapter can select a public Store API
    # endpoint, that is decisive evidence. This keeps platform detection
    # aligned with the exact HTTP/JSON behavior used by production scans.
    # =====================================================

    woo_detected, woo_path, woo_adapter_error = (
        await _probe_woocommerce_with_production_adapter(
            base_url
        )
    )

    if woo_detected:
        _add_signal(
            scores,
            signal_map,
            "woocommerce",
            140,
            (
                "Production WooCommerce adapter confirmed public "
                f"Store API endpoint {woo_path}"
            ),
        )

    else:
        if woo_adapter_error:
            errors.append(
                f"WOO_PRODUCTION_PROBE:{woo_adapter_error}"
            )

        # Fallback namespace fingerprint. This remains useful for stores
        # whose product collection endpoint is temporarily filtered but
        # whose WordPress REST index still advertises wc/store routes.
        ok, payload, error = await _probe_json_endpoint(
            session,
            f"{base_url}/wp-json/",
        )
        if ok and isinstance(payload, dict):
            namespaces = payload.get("namespaces")
            routes = payload.get("routes")

            namespace_hit = False
            if isinstance(namespaces, list):
                namespace_hit = any(
                    str(item).lower().startswith("wc/store")
                    for item in namespaces
                )

            route_hit = False
            if isinstance(routes, dict):
                route_hit = any(
                    str(route).lower().startswith("/wc/store/")
                    for route in routes.keys()
                )

            if namespace_hit or route_hit:
                _add_signal(
                    scores,
                    signal_map,
                    "woocommerce",
                    120,
                    "WordPress REST index exposes WooCommerce Store API namespace",
                )
        elif error and error not in {"HTTP_401", "HTTP_403", "HTTP_404"}:
            errors.append(f"WOO_INDEX_PROBE:{error}")

        # Final low-cost detector fallback. It uses the generic detector
        # JSON helper only when the production adapter could not confirm
        # WooCommerce.
        woo_paths = (
            "/wp-json/wc/store/v1/products?per_page=1&page=1",
            "/wp-json/wc/store/products?per_page=1&page=1",
        )

        for path in woo_paths:
            ok, payload, error = await _probe_json_endpoint(
                session,
                f"{base_url}{path}",
            )

            if ok and isinstance(payload, list):
                _add_signal(
                    scores,
                    signal_map,
                    "woocommerce",
                    110,
                    "Public WooCommerce Store API responded with a product collection",
                )
                break

            if error and error not in {"HTTP_401", "HTTP_403", "HTTP_404"}:
                errors.append(f"WOO_PROBE:{error}")

    # Shopify's public products.json is not universally exposed, so a
    # successful Shopify-shaped payload is strong evidence while failure
    # carries no negative score.
    ok, payload, error = await _probe_json_endpoint(
        session,
        f"{base_url}/products.json?limit=1",
    )
    if ok and isinstance(payload, dict) and isinstance(payload.get("products"), list):
        products = payload.get("products") or []
        looks_shopify = False

        if not products:
            looks_shopify = True
        elif isinstance(products[0], dict):
            first_keys = {
                str(key).lower()
                for key in products[0].keys()
            }
            looks_shopify = (
                {"id", "title"}.issubset(first_keys)
                and bool(
                    first_keys
                    & {"handle", "variants", "product_type", "vendor"}
                )
            )

        if looks_shopify:
            _add_signal(
                scores,
                signal_map,
                "shopify",
                100,
                "Public Shopify products.json endpoint responded",
            )
    elif error and error not in {"HTTP_401", "HTTP_403", "HTTP_404"}:
        errors.append(f"SHOPIFY_PROBE:{error}")

    # BigCommerce Stencil storefronts commonly expose this public settings
    # endpoint. Require a dictionary payload, then score it strongly.
    ok, payload, error = await _probe_json_endpoint(
        session,
        f"{base_url}/api/storefront/store-settings",
    )
    if ok and isinstance(payload, dict):
        # Avoid scoring a random JSON endpoint unless it looks storefront-like.
        payload_keys = {str(key).lower() for key in payload.keys()}
        expected_keys = {
            "storehash",
            "store_hash",
            "channelid",
            "channel_id",
            "shoppercurrency",
            "shopper_currency",
            "storefrontsettings",
            "storefront_settings",
        }
        if payload_keys & expected_keys:
            _add_signal(
                scores,
                signal_map,
                "bigcommerce",
                95,
                "BigCommerce storefront settings endpoint responded",
            )
    elif error and error not in {"HTTP_401", "HTTP_403", "HTTP_404"}:
        errors.append(f"BIGCOMMERCE_PROBE:{error}")


async def detect_retailer_platform(
    domain: str,
) -> PlatformFingerprintResult:
    clean_domain = normalize_domain(domain)

    if not clean_domain:
        return PlatformFingerprintResult(
            domain="",
            platform="unknown",
            confidence="UNKNOWN",
            score=0,
            runner_up_platform=None,
            runner_up_score=0,
            homepage_url=None,
            homepage_status=None,
            signals=[],
            scores=_initial_scores(),
            signal_map=_initial_signal_map(),
            errors=["INVALID_DOMAIN"],
        )

    scores = _initial_scores()
    signal_map = _initial_signal_map()
    errors: list[str] = []

    timeout = aiohttp.ClientTimeout(
        total=REQUEST_TIMEOUT_SECONDS,
        connect=min(8, REQUEST_TIMEOUT_SECONDS),
        sock_read=REQUEST_TIMEOUT_SECONDS,
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.8",
        "Cache-Control": "no-cache",
    }

    # Homepage probe gets its own cookie jar/session. Some storefronts
    # set presentation or cache cookies on the homepage that can change
    # how subsequent REST requests are served. Platform API probes must
    # therefore be isolated from homepage cookies.
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as homepage_session:
        (
            homepage_url,
            homepage_status,
            html,
            response_headers,
            homepage_errors,
        ) = await _fetch_homepage(
            homepage_session,
            clean_domain,
        )

    errors.extend(homepage_errors)

    score_homepage_signals(
        html=html,
        final_url=homepage_url,
        headers=response_headers,
        scores=scores,
        signal_map=signal_map,
    )

    # Use the resolved origin for API probes when possible, so www/non-www
    # redirects and alternate storefront hosts are handled correctly.
    if homepage_url:
        parsed = urlparse(homepage_url)
        if parsed.scheme and parsed.netloc:
            base_url = f"{parsed.scheme}://{parsed.netloc}"
        else:
            base_url = f"https://{clean_domain}"
    else:
        base_url = f"https://{clean_domain}"

    # Match the production WooCommerce adapter's JSON-first request profile
    # and deliberately isolate API probing from homepage cookies.
    probe_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    connector = aiohttp.TCPConnector(
        limit=4,
        limit_per_host=2,
    )

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=probe_headers,
        connector=connector,
        cookie_jar=aiohttp.DummyCookieJar(),
    ) as probe_session:
        await _probe_platform_apis(
            session=probe_session,
            base_url=base_url,
            scores=scores,
            signal_map=signal_map,
            errors=errors,
        )

    (
        confidence,
        platform,
        score,
        runner_up_platform,
        runner_up_score,
    ) = _confidence_for_scores(scores)

    signals = (
        list(signal_map.get(platform, []))
        if platform != "unknown"
        else []
    )

    return PlatformFingerprintResult(
        domain=clean_domain,
        platform=platform,
        confidence=confidence,
        score=score,
        runner_up_platform=runner_up_platform,
        runner_up_score=runner_up_score,
        homepage_url=homepage_url,
        homepage_status=homepage_status,
        signals=signals,
        scores=scores,
        signal_map=signal_map,
        errors=errors,
    )
