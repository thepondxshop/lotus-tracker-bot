"""
Lotus Tracker Bot
PonDeX Trackers

Universal Retailer Lightweight Delta Discovery
Version: 1.0.0

Step 6J-3D1 — Fast New-Product Discovery

Purpose:
- Find NEW public product URLs quickly.
- Never replace the normal known-product fast refresh.
- Never run a full storefront crawl.
- Never perform checkout/cart probing.
- Never bypass CAPTCHA, queues, rate limits, or anti-bot systems.

Supported platforms:
- PrestaShop
- BigCommerce
- Square / Weebly

Design:
- Small number of public discovery pages.
- Small sitemap budget.
- Known URLs removed before product-page fetching.
- Candidate count is tightly bounded.
- Returned URLs are validated later by the store's existing adapter.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
)

import aiohttp


VERSION = "1.0.0"

logger = logging.getLogger(
    "lotus.delta_discovery"
)


# =========================================================
# SAFETY / PERFORMANCE BOUNDS
# =========================================================

REQUEST_TIMEOUT_SECONDS = 10

MAX_SOURCE_PAGES = 6

MAX_SITEMAP_DOCUMENTS = 4

MAX_RAW_CANDIDATES = 120

MAX_NEW_CANDIDATES = 12

REQUEST_CONCURRENCY = 3


USER_AGENT = (
    "LotusTracker/1.0 "
    "(PonDeX Trackers; public retailer discovery monitor)"
)


# =========================================================
# REGEX
# =========================================================

HREF_PATTERN = re.compile(
    r'''href\s*=\s*["']([^"']+)["']''',
    re.IGNORECASE,
)

LOC_PATTERN = re.compile(
    r"<loc>\s*(.*?)\s*</loc>",
    re.IGNORECASE | re.DOTALL,
)

ROBOTS_SITEMAP_PATTERN = re.compile(
    r"(?im)^\s*Sitemap\s*:\s*(\S+)"
)

SQUARE_PRODUCT_PATH_PATTERN = re.compile(
    r"/product/[^/?#]+/\d+(?:[/?#]|$)",
    re.IGNORECASE,
)


# =========================================================
# PRIORITY TERMS
# =========================================================

TCG_PRIORITY_TERMS = (
    "pokemon",
    "pokémon",
    "one-piece",
    "onepiece",
    "one_piece",
    "one piece",
    "gundam",
    "fusion-world",
    "fusion_world",
    "fusion world",
    "riftbound",
    "palworld",
    "naruto",
    "cyberpunk",
    "azuki",
    "hellbreak",
    "booster",
    "deck",
    "starter",
    "display",
    "collection",
    "tcg",
    "trading-card",
    "trading_card",
    "trading card",
    "card-game",
    "card_game",
    "card game",
    "preorder",
    "pre-order",
    "preventa",
    "new-product",
    "new-products",
)


# =========================================================
# PLATFORM SOURCE PATHS
# =========================================================

PRESTASHOP_HTML_PATHS = (
    "/new-products",
    "/",
    "/preorder",
    "/pre-order",
    "/preventa",
    "/pokemon",
)

PRESTASHOP_SITEMAP_PATHS = (
    "/1_index_sitemap.xml",
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/index_sitemap.xml",
)


BIGCOMMERCE_HTML_PATHS = (
    "/",
    "/new-products/",
    "/new-products",
    "/pre-order/",
    "/preorder/",
)

BIGCOMMERCE_SITEMAP_PATHS = (
    "/xmlsitemap.php",
    "/sitemap.xml",
    "/sitemap_index.xml",
)


SQUARE_HTML_PATHS = (
    "/",
    "/shop",
    "/store",
    "/s/shop",
    "/new",
    "/new-products",
)

SQUARE_SITEMAP_PATHS = (
    "/sitemap.xml",
)


# =========================================================
# RESULT
# =========================================================

@dataclass
class DeltaDiscoveryResult:

    platform: str

    domain: str

    source_pages_checked: int

    source_pages_successful: int

    sitemap_documents_checked: int

    raw_candidates: int

    new_candidates: list[str]

    timed_out_requests: int

    failed_requests: int

    last_error: str | None = None

    def to_dict(
        self,
    ) -> dict:

        return {
            "platform":
                self.platform,

            "domain":
                self.domain,

            "source_pages_checked":
                self.source_pages_checked,

            "source_pages_successful":
                self.source_pages_successful,

            "sitemap_documents_checked":
                self.sitemap_documents_checked,

            "raw_candidates":
                self.raw_candidates,

            "new_candidates":
                list(
                    self.new_candidates
                ),

            "new_candidate_count":
                len(
                    self.new_candidates
                ),

            "timed_out_requests":
                self.timed_out_requests,

            "failed_requests":
                self.failed_requests,

            "last_error":
                self.last_error,
        }


# =========================================================
# URL HELPERS
# =========================================================

def normalize_domain(
    value,
) -> str:

    value = str(
        value
        or ""
    ).strip()

    value = re.sub(
        r"^https?://",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip(
        "/"
    )


def normalize_platform(
    value,
) -> str:

    value = (
        str(
            value
            or ""
        )
        .strip()
        .lower()
    )

    aliases = {
        "presta":
            "prestashop",

        "presta-shop":
            "prestashop",

        "presta_shop":
            "prestashop",

        "big-commerce":
            "bigcommerce",

        "big_commerce":
            "bigcommerce",

        "square":
            "square_weebly",

        "weebly":
            "square_weebly",

        "square-weebly":
            "square_weebly",
    }

    return aliases.get(
        value,
        value,
    )


def canonicalize_url(
    value,
) -> str:

    value = html.unescape(
        str(
            value
            or ""
        ).strip()
    )

    if not value:
        return ""

    try:

        parsed = urlparse(
            value
        )

    except Exception:

        return ""

    if parsed.scheme not in {
        "http",
        "https",
    }:

        return ""

    host = (
        parsed.netloc
        .lower()
        .split(
            ":"
        )[0]
    )

    if not host:
        return ""

    path = (
        parsed.path
        or "/"
    )

    # Discovery URLs should not be duplicated because of
    # tracking, sorting, faceting, or session parameters.
    return urlunparse(
        (
            parsed.scheme.lower(),
            host,
            path,
            "",
            "",
            "",
        )
    )


def same_domain(
    url,
    domain,
) -> bool:

    try:

        host = (
            urlparse(
                url
            )
            .netloc
            .lower()
            .split(
                ":"
            )[0]
        )

        domain = (
            normalize_domain(
                domain
            )
            .lower()
            .split(
                ":"
            )[0]
        )

        return (
            host == domain
            or
            host.endswith(
                "." + domain
            )
            or
            domain.endswith(
                "." + host
            )
        )

    except Exception:

        return False


def absolute_url(
    base_url,
    candidate,
) -> str:

    candidate = html.unescape(
        str(
            candidate
            or ""
        ).strip()
    )

    if not candidate:
        return ""

    try:

        combined = urljoin(
            base_url,
            candidate,
        )

    except Exception:

        return ""

    return canonicalize_url(
        combined
    )


def path_lower(
    url,
) -> str:

    try:

        return (
            urlparse(
                url
            )
            .path
            .lower()
        )

    except Exception:

        return ""


# =========================================================
# FILTERS
# =========================================================

def is_asset_url(
    url,
) -> bool:

    path = path_lower(
        url
    )

    asset_extensions = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
        ".css",
        ".js",
        ".woff",
        ".woff2",
        ".ttf",
        ".pdf",
        ".zip",
        ".mp4",
        ".webm",
    )

    return path.endswith(
        asset_extensions
    )


def is_account_or_checkout_url(
    url,
) -> bool:

    path = path_lower(
        url
    )

    blocked = (
        "/login",
        "/signin",
        "/sign-in",
        "/account",
        "/my-account",
        "/cart",
        "/basket",
        "/checkout",
        "/order",
        "/orders",
        "/wishlist",
        "/password",
        "/register",
        "/authentication",
    )

    return any(
        item in path
        for item in blocked
    )


def is_safe_candidate_url(
    url,
    domain,
) -> bool:

    if not url:
        return False

    if not same_domain(
        url,
        domain,
    ):
        return False

    if is_asset_url(
        url
    ):
        return False

    if is_account_or_checkout_url(
        url
    ):
        return False

    return True


# =========================================================
# PRODUCT URL HEURISTICS
# =========================================================

def looks_like_prestashop_product(
    url,
) -> bool:

    path = path_lower(
        url
    )

    if not path:
        return False

    # Common classic PrestaShop pattern:
    # /123-product-name.html
    if re.search(
        r"/\d+[-_][^/]+(?:\.html)?/?$",
        path,
        re.IGNORECASE,
    ):
        return True

    if re.search(
        r"/\d+/[^/]+/?$",
        path,
        re.IGNORECASE,
    ):
        return True

    product_markers = (
        "/product/",
        "/produit/",
        "/producto/",
        "/produkt/",
    )

    return any(
        marker in path
        for marker in product_markers
    )


def looks_like_bigcommerce_product(
    url,
) -> bool:

    path = path_lower(
        url
    )

    if not path:
        return False

    blocked = (
        "/categories/",
        "/category/",
        "/pages/",
        "/blog/",
        "/brands/",
        "/search",
        "/contact",
    )

    if any(
        marker in path
        for marker in blocked
    ):

        return False

    if path.endswith(
        ".xml"
    ):
        return False

    # BigCommerce product pages are frequently clean
    # one- or two-segment SEO URLs.
    segments = [
        segment
        for segment in path.split(
            "/"
        )
        if segment
    ]

    if not segments:
        return False

    if any(
        term in path
        for term in TCG_PRIORITY_TERMS
    ):

        return True

    return (
        len(
            segments
        )
        <= 3
        and
        "-" in segments[-1]
    )


def looks_like_square_product(
    url,
) -> bool:

    path = path_lower(
        url
    )

    if not path:
        return False

    if SQUARE_PRODUCT_PATH_PATTERN.search(
        path
    ):

        return True

    return (
        "/product/"
        in path
    )


def looks_like_product_url(
    platform,
    url,
) -> bool:

    platform = normalize_platform(
        platform
    )

    if platform == "prestashop":

        return looks_like_prestashop_product(
            url
        )

    if platform == "bigcommerce":

        return looks_like_bigcommerce_product(
            url
        )

    if platform == "square_weebly":

        return looks_like_square_product(
            url
        )

    return False


# =========================================================
# PRIORITY
# =========================================================

def candidate_priority(
    url,
) -> int:

    lowered = (
        str(
            url
            or ""
        )
        .lower()
    )

    score = 0

    for term in TCG_PRIORITY_TERMS:

        if term in lowered:

            score += 10

    if any(
        term in lowered
        for term in (
            "new-product",
            "new-products",
            "preorder",
            "pre-order",
            "preventa",
        )
    ):

        score += 30

    return score


# =========================================================
# SOURCE CONFIG
# =========================================================

def get_platform_sources(
    platform,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
]:

    platform = normalize_platform(
        platform
    )

    if platform == "prestashop":

        return (
            PRESTASHOP_HTML_PATHS,
            PRESTASHOP_SITEMAP_PATHS,
        )

    if platform == "bigcommerce":

        return (
            BIGCOMMERCE_HTML_PATHS,
            BIGCOMMERCE_SITEMAP_PATHS,
        )

    if platform == "square_weebly":

        return (
            SQUARE_HTML_PATHS,
            SQUARE_SITEMAP_PATHS,
        )

    return (
        (),
        (),
    )


# =========================================================
# FETCH STATE
# =========================================================

class FetchStats:

    def __init__(
        self,
    ):

        self.checked = 0

        self.successful = 0

        self.timeouts = 0

        self.failed = 0

        self.last_error = None


# =========================================================
# PUBLIC FETCH
# =========================================================

async def fetch_text(
    session,
    url,
    stats: FetchStats,
) -> tuple[
    str | None,
    str | None,
]:

    stats.checked += 1

    try:

        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(
                total=(
                    REQUEST_TIMEOUT_SECONDS
                )
            ),
            allow_redirects=True,
        ) as response:

            if response.status >= 400:

                stats.failed += 1

                stats.last_error = (
                    f"HTTP_{response.status}"
                )

                return (
                    None,
                    None,
                )

            text = (
                await response.text(
                    errors="ignore"
                )
            )

            final_url = (
                canonicalize_url(
                    str(
                        response.url
                    )
                )
                or
                canonicalize_url(
                    url
                )
            )

            stats.successful += 1

            return (
                text,
                final_url,
            )

    except asyncio.TimeoutError:

        stats.timeouts += 1

        stats.last_error = (
            "REQUEST_TIMEOUT"
        )

        return (
            None,
            None,
        )

    except aiohttp.ClientError as error:

        stats.failed += 1

        stats.last_error = (
            f"{type(error).__name__}: "
            f"{error}"
        )

        return (
            None,
            None,
        )

    except Exception as error:

        stats.failed += 1

        stats.last_error = (
            f"{type(error).__name__}: "
            f"{error}"
        )

        return (
            None,
            None,
        )


# =========================================================
# LINK EXTRACTION
# =========================================================

def extract_html_candidates(
    *,
    platform,
    domain,
    source_url,
    text,
) -> set[str]:

    candidates = set()

    if not text:
        return candidates

    decoded = html.unescape(
        text
    )

    decoded = decoded.replace(
        r"\/",
        "/",
    )

    decoded = decoded.replace(
        r"\u002F",
        "/",
    )

    decoded = decoded.replace(
        r"\u002f",
        "/",
    )

    for match in HREF_PATTERN.finditer(
        decoded
    ):

        candidate = absolute_url(
            source_url,
            match.group(
                1
            ),
        )

        if not is_safe_candidate_url(
            candidate,
            domain,
        ):

            continue

        if looks_like_product_url(
            platform,
            candidate,
        ):

            candidates.add(
                candidate
            )

            if (
                len(
                    candidates
                )
                >=
                MAX_RAW_CANDIDATES
            ):

                break

    # Square frequently serializes product URLs inside
    # HTML/JavaScript rather than normal anchor tags.
    if platform == "square_weebly":

        for match in (
            SQUARE_PRODUCT_PATH_PATTERN
            .finditer(
                decoded
            )
        ):

            candidate = absolute_url(
                source_url,
                match.group(
                    0
                ),
            )

            if not is_safe_candidate_url(
                candidate,
                domain,
            ):

                continue

            candidates.add(
                candidate
            )

            if (
                len(
                    candidates
                )
                >=
                MAX_RAW_CANDIDATES
            ):

                break

    return candidates


def extract_sitemap_locations(
    *,
    domain,
    text,
) -> list[str]:

    output = []

    seen = set()

    for raw in LOC_PATTERN.findall(
        text
        or ""
    ):

        candidate = canonicalize_url(
            html.unescape(
                raw
            )
        )

        if not candidate:

            continue

        if not same_domain(
            candidate,
            domain,
        ):

            continue

        if candidate in seen:

            continue

        seen.add(
            candidate
        )

        output.append(
            candidate
        )

    return output


# =========================================================
# DELTA DISCOVERY
# =========================================================

async def discover_new_product_urls(
    *,
    platform,
    domain,
    known_urls: Iterable[str] | None = None,
    limit: int = MAX_NEW_CANDIDATES,
) -> DeltaDiscoveryResult:

    platform = normalize_platform(
        platform
    )

    domain = normalize_domain(
        domain
    )

    limit = max(
        1,
        min(
            int(
                limit
            ),
            MAX_NEW_CANDIDATES,
        ),
    )

    if platform not in {
        "prestashop",
        "bigcommerce",
        "square_weebly",
    }:

        return DeltaDiscoveryResult(
            platform=platform,
            domain=domain,
            source_pages_checked=0,
            source_pages_successful=0,
            sitemap_documents_checked=0,
            raw_candidates=0,
            new_candidates=[],
            timed_out_requests=0,
            failed_requests=0,
            last_error=(
                "UNSUPPORTED_PLATFORM"
            ),
        )

    if not domain:

        return DeltaDiscoveryResult(
            platform=platform,
            domain=domain,
            source_pages_checked=0,
            source_pages_successful=0,
            sitemap_documents_checked=0,
            raw_candidates=0,
            new_candidates=[],
            timed_out_requests=0,
            failed_requests=0,
            last_error=(
                "NO_DOMAIN"
            ),
        )

    base_url = (
        f"https://{domain}"
    )

    known = set()

    for value in (
        known_urls
        or []
    ):

        normalized = canonicalize_url(
            value
        )

        if normalized:

            known.add(
                normalized
            )

    (
        html_paths,
        sitemap_paths,
    ) = get_platform_sources(
        platform
    )

    stats = FetchStats()

    candidates = set()

    sitemap_documents_checked = 0

    headers = {
        "User-Agent":
            USER_AGENT,

        "Accept":
            (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),

        "Accept-Language":
            "en-US,en;q=0.8",
    }

    connector = aiohttp.TCPConnector(
        limit=(
            REQUEST_CONCURRENCY
            +
            1
        ),
        limit_per_host=(
            REQUEST_CONCURRENCY
        ),
    )

    async with aiohttp.ClientSession(
        headers=headers,
        connector=connector,
    ) as session:

        # =================================================
        # 1. HIGH-YIELD HTML SOURCES
        # =================================================

        source_urls = []

        seen_sources = set()

        for path in (
            html_paths[
                :MAX_SOURCE_PAGES
            ]
        ):

            source_url = absolute_url(
                base_url + "/",
                path,
            )

            if (
                source_url
                and
                source_url
                not in seen_sources
            ):

                source_urls.append(
                    source_url
                )

                seen_sources.add(
                    source_url
                )

        semaphore = asyncio.Semaphore(
            REQUEST_CONCURRENCY
        )

        async def inspect_html_source(
            source_url,
        ):

            async with semaphore:

                text, final_url = (
                    await fetch_text(
                        session,
                        source_url,
                        stats,
                    )
                )

                if not text:

                    return

                effective_url = (
                    final_url
                    or
                    source_url
                )

                found = (
                    extract_html_candidates(
                        platform=platform,
                        domain=domain,
                        source_url=effective_url,
                        text=text,
                    )
                )

                candidates.update(
                    found
                )

        await asyncio.gather(
            *(
                inspect_html_source(
                    source_url
                )
                for source_url
                in source_urls
            )
        )

        # =================================================
        # 2. ROBOTS.TXT SITEMAP DECLARATIONS
        # =================================================

        sitemap_queue = []

        sitemap_seen = set()

        for path in sitemap_paths:

            sitemap_url = absolute_url(
                base_url + "/",
                path,
            )

            if (
                sitemap_url
                and
                sitemap_url
                not in sitemap_queue
            ):

                sitemap_queue.append(
                    sitemap_url
                )

        robots_url = absolute_url(
            base_url + "/",
            "/robots.txt",
        )

        robots_text, _ = (
            await fetch_text(
                session,
                robots_url,
                stats,
            )
        )

        if robots_text:

            for raw in (
                ROBOTS_SITEMAP_PATTERN
                .findall(
                    robots_text
                )
            ):

                sitemap_url = (
                    canonicalize_url(
                        raw
                    )
                )

                if not sitemap_url:

                    continue

                if not same_domain(
                    sitemap_url,
                    domain,
                ):

                    continue

                if (
                    sitemap_url
                    not in sitemap_queue
                ):

                    sitemap_queue.append(
                        sitemap_url
                    )

        # =================================================
        # 3. SHALLOW SITEMAP DISCOVERY
        # =================================================

        while (
            sitemap_queue
            and
            len(
                sitemap_seen
            )
            <
            MAX_SITEMAP_DOCUMENTS
        ):

            sitemap_url = (
                sitemap_queue.pop(
                    0
                )
            )

            if sitemap_url in sitemap_seen:

                continue

            sitemap_seen.add(
                sitemap_url
            )

            sitemap_documents_checked += 1

            text, _ = (
                await fetch_text(
                    session,
                    sitemap_url,
                    stats,
                )
            )

            if not text:

                continue

            locations = (
                extract_sitemap_locations(
                    domain=domain,
                    text=text,
                )
            )

            for location in locations:

                lowered = (
                    location.lower()
                )

                if (
                    lowered.endswith(
                        ".xml"
                    )
                    or
                    "sitemap"
                    in lowered
                ):

                    if (
                        location
                        not in sitemap_seen
                        and
                        location
                        not in sitemap_queue
                    ):

                        # Product/new sitemap documents are
                        # checked before generic sitemap files.
                        if any(
                            term in lowered
                            for term in (
                                "product",
                                "products",
                                "produit",
                                "producto",
                                "produkt",
                                "new",
                                "shop",
                            )
                        ):

                            sitemap_queue.insert(
                                0,
                                location,
                            )

                        else:

                            sitemap_queue.append(
                                location
                            )

                    continue

                if not is_safe_candidate_url(
                    location,
                    domain,
                ):

                    continue

                if not looks_like_product_url(
                    platform,
                    location,
                ):

                    continue

                candidates.add(
                    location
                )

                if (
                    len(
                        candidates
                    )
                    >=
                    MAX_RAW_CANDIDATES
                ):

                    break

            if (
                len(
                    candidates
                )
                >=
                MAX_RAW_CANDIDATES
            ):

                break

    # =====================================================
    # REMOVE EVERYTHING LOTUS ALREADY KNOWS
    # =====================================================

    new_candidates = [
        candidate
        for candidate in candidates
        if candidate not in known
    ]

    # =====================================================
    # TCG / NEW PRODUCT PRIORITY
    # =====================================================

    new_candidates.sort(
        key=lambda candidate: (
            -candidate_priority(
                candidate
            ),
            candidate.lower(),
        )
    )

    new_candidates = (
        new_candidates[
            :limit
        ]
    )

    result = DeltaDiscoveryResult(
        platform=platform,
        domain=domain,

        source_pages_checked=(
            stats.checked
        ),

        source_pages_successful=(
            stats.successful
        ),

        sitemap_documents_checked=(
            sitemap_documents_checked
        ),

        raw_candidates=(
            len(
                candidates
            )
        ),

        new_candidates=(
            new_candidates
        ),

        timed_out_requests=(
            stats.timeouts
        ),

        failed_requests=(
            stats.failed
        ),

        last_error=(
            stats.last_error
        ),
    )

    logger.info(
        (
            "UNIVERSAL DELTA DISCOVERY COMPLETE | "
            "Platform=%s | Domain=%s | "
            "KnownURLs=%s | "
            "SourcePagesChecked=%s | "
            "SourcePagesSuccessful=%s | "
            "SitemapDocuments=%s | "
            "RawCandidates=%s | "
            "NewCandidates=%s | "
            "RequestTimeouts=%s | "
            "RequestFailures=%s"
        ),
        platform,
        domain,
        len(
            known
        ),
        result.source_pages_checked,
        result.source_pages_successful,
        result.sitemap_documents_checked,
        result.raw_candidates,
        len(
            result.new_candidates
        ),
        result.timed_out_requests,
        result.failed_requests,
    )

    return result
