"""
Lotus Tracker Bot / PonDeX Trackers
BigCommerce Universal Retailer Adapter
Version 1.0.9
Star City Games bounded catalog discovery; Game Nerdz compatibility retained

Public storefront + sitemap GETs only.
No auth guessing, cart mutation, checkout automation, CAPTCHA/queue bypass.
"""

from __future__ import annotations
from app.registered_games import registered_title, registered_identity, explicit_family, GAMES as REGISTERED_GAMES

import asyncio
import html as html_lib
import json
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp

from app.mtg_products import classify_mtg, has_mtg_identity, mtg_product_details
from app.event_listing_filter import is_event_listing

from app.retailer_adapter import RetailerAdapter, RetailerProduct, normalize_price
from app.retailer_registry import retailer_adapter

VERSION = "1.0.9"
USER_AGENT = "LotusTracker/1.0.4 (PonDeX Trackers; public retailer monitor)"
DEFAULT_TIMEOUT = 15
DEFAULT_REQUEST_DELAY = 0.65
MAX_SITEMAPS = 20
MAX_DISCOVERED_URLS = 10000
MAX_PRODUCT_PAGES = 200

# Per-process, per-store progress; no database or baseline changes.
_DISCOVERY_LAST_URL = {}
_SCG_SITEMAP_CURSOR = {}
_SCG_LAST_PRODUCT = {}
SCG_DISCOVERY_SECONDS = 60
SCG_DELTA_SECONDS = 22
SCG_PRODUCT_LIMIT = 32
SCG_SEALED_URL = re.compile(r"-sld-(?:mtg|poke|rift|punk)-", re.I)


def starcity_host(domain):
    return normalize_domain(domain).lower().removeprefix("www.") == "starcitygames.com"


def starcity_sitemap_page(url):
    """Only numbered product sitemaps actually advertised by the store."""
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if (parsed.scheme not in {"http", "https"}
                or not starcity_host(parsed.hostname or "")
                or parsed.path != "/xmlsitemap.php"
                or query.get("type") != ["products"]):
            return None
        page = int(query.get("page", [""])[0])
        return page if page > 0 else None
    except (TypeError, ValueError):
        return None

SITEMAP_PATHS = ("/xmlsitemap.php", "/sitemap.xml", "/sitemap_index.xml")
TCG_PRIORITY = (
    "magic-the-gathering", "mtg",
    "pokemon","one-piece","onepiece","gundam","fusion-world","riftbound",
    "palworld","naruto","cyberpunk","azuki","hellbreak","cataclysm-arcade","cataclysm arcade","booster","deck","tcg","card","single",
)
UNSUPPORTED = (
    "magic the gathering","magic: the gathering","yu-gi-oh","yugioh","lorcana",
    "digimon","weiss schwarz","union arena","flesh and blood","star wars unlimited",
    "warhammer","games workshop",
)
GAME_TERMS = {
    "Pokemon": ("pokemon tcg","pokémon tcg","pokemon trading card","pokémon trading card","pokemon card game","pokémon card game"),
    "Gundam": ("gundam card game","gundam tcg"),
    "Dragon Ball Fusion World": ("dragon ball fusion world","fusion world tcg"),
    "Riftbound": ("riftbound",),
    "Palworld": ("palworld tcg","palworld card game"),
    "Naruto": ("naruto tcg","naruto card game"),
    "Cyberpunk TCG": ("cyberpunk tcg","cyberpunk trading card game"),
    "Azuki TCG": ("azuki tcg","azuki trading card game"),
    "Cataclysm Arcade": ("cataclysm arcade", "cataclysm-arcade"),
    "Hellbreak TCG": ("hellbreak tcg","hellbreak trading card game"),
}
SEALED = (
    "booster box","booster display","booster pack","booster bundle","elite trainer box",
    "starter deck","battle deck","battle arena deck","high class deck","structure deck",
    "build & battle","build and battle","classic trading card game",
    "collection box","collection set",
    "special collection","premium collection","figure collection","v box","vstar box",
    "v star","world championship deck","world championships deck","build & battle stadium",
    "build and battle stadium","deluxe box","deluxe pack","double pack","blister","tin","case"
)
SINGLE = ("single card","tcg single","card single","singles","individual card","black star promo","promo card")
ACCESSORY = ("sleeves","deck box","binder","playmat","play mat","portfolio","toploader","top loader")
ONE_PIECE_CODE = re.compile(r"\b(?:OP|EB|PRB|ST|EX)\d{1,2}-\d{2,4}\b", re.I)
POKEMON_NUMBER = re.compile(
    r"\b\d{1,4}\s*/\s*\d{1,4}\b"
    r"(?!\s*(?:-|–|—)?\s*(?:inch|inches|in\.|[\"”]))",
    re.I,
)
NON_TCG_MERCHANDISE = (
    re.compile(r"\bplush(?:ie|ies)?\b", re.I),
    re.compile(r"\bstuffed\s+(?:animal|toy)\b", re.I),
    re.compile(r"\bkey[\s-]*chain\b", re.I),
    re.compile(r"\bclip[\s-]*on\b", re.I),
    re.compile(r"\blanyard\b", re.I),
    re.compile(r"\bfunko\b", re.I),
    re.compile(r"\bpop!\b", re.I),
    re.compile(r"\baction\s+figure\b", re.I),
    re.compile(r"\bfigurine\b", re.I),
    re.compile(r"\bstatue\b", re.I),
    re.compile(r"\bdoll\b", re.I),
    re.compile(
        r"\b(?:t[\s-]*shirt|shirt|hoodie|sweatshirt|socks|blanket)\b",
        re.I,
    ),
    re.compile(r"\b(?:backpack|wallet|mug)\b", re.I),
)
JSON_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I|re.S)
LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I|re.S)
OG_TITLE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.I)
OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I|re.S)


def clean(v):
    if v is None:
        return ""

    v = html_lib.unescape(str(v))
    v = re.sub(r"<[^>]+>", " ", v)

    return re.sub(r"\s+", " ", v).strip()


def normalize_domain(v):
    v = re.sub(
        r"^https?://",
        "",
        str(v or "").strip(),
        flags=re.I,
    )

    return v.strip("/")


def same_domain(url, domain):
    try:
        host = (
            urlparse(url)
            .netloc
            .lower()
            .split(":")[0]
        )

        dom = (
            domain
            .lower()
            .split(":")[0]
        )

        return (
            host == dom
            or host.endswith("." + dom)
        )

    except Exception:
        return False


def is_non_tcg_merchandise(title):
    text = clean(title)

    if not text:
        return False

    return any(
        pattern.search(text)
        for pattern in NON_TCG_MERCHANDISE
    )


def classify_game(title):
    if registered_title(title):
        return registered_identity({"title": title})
    if has_mtg_identity(title):
        return classify_mtg(title)

    t = clean(title).lower()

    if not t:
        return None

    if is_non_tcg_merchandise(title):
        return None

    if any(
        x in t
        for x in UNSUPPORTED
    ):
        return None

    if (
        "one piece card game" in t
        or
        "one piece tcg" in t
        or
        ONE_PIECE_CODE.search(
            title or ""
        )
    ):
        return "One Piece"

    for game, terms in GAME_TERMS.items():
        if any(
            x in t
            for x in terms
        ):
            return game

    return None


def category(title):
    mtg = mtg_product_details(title)
    if mtg:
        return mtg[0]

    t = clean(title).lower()

    if ONE_PIECE_CODE.search(
        title or ""
    ):
        return "SINGLE"

    if (
        POKEMON_NUMBER.search(
            title or ""
        )
        and
        (
            "pokemon" in t
            or
            "pokémon" in t
        )
    ):
        return "SINGLE"

    if any(
        x in t
        for x in SINGLE
    ):
        return "SINGLE"

    if any(
        x in t
        for x in SEALED
    ):
        return "SEALED"

    if any(
        x in t
        for x in ACCESSORY
    ):
        return "ACCESSORY"

    return "UNKNOWN"


def product_type(title):
    mtg = mtg_product_details(title)
    if mtg:
        return mtg[1]

    c = category(
        title
    )

    if c == "SINGLE":
        return "Single Card"

    t = clean(
        title
    ).lower()

    mapping = (
        (
            (
                "elite trainer box",
            ),
            "Elite Trainer Box",
        ),
        (
            (
                "booster box",
                "booster display",
            ),
            "Booster Box",
        ),
        (
            (
                "booster bundle",
            ),
            "Booster Bundle",
        ),
        (
            (
                "booster pack",
            ),
            "Booster Pack",
        ),
        (
            (
                "starter deck",
            ),
            "Starter Deck",
        ),
        (
            (
                "battle deck",
            ),
            "Battle Deck",
        ),
        (
            (
                "structure deck",
            ),
            "Structure Deck",
        ),
        (
            (
                "premium collection",
            ),
            "Premium Collection",
        ),
        (
            (
                "tin",
            ),
            "Tin",
        ),
        (
            (
                "playmat",
                "play mat",
            ),
            "Playmat",
        ),
        (
            (
                "sleeves",
            ),
            "Sleeves",
        ),
        (
            (
                "binder",
            ),
            "Binder",
        ),
        (
            (
                "deck box",
            ),
            "Deck Box",
        ),
    )

    for terms, label in mapping:
        if any(
            x in t
            for x in terms
        ):
            return label

    return "TCG Product"


def family(title):
    if registered_title(title):
        return explicit_family({"title": title})
    t = (
        f" {clean(title).lower()} "
    )

    # Family/language is derived from explicit title metadata only.
    # Currency is intentionally never used for this decision.
    if any(
        x in t
        for x in (
            " japanese ",
            " japan ",
            " jp version ",
            " jp edition ",
            " jp ",
        )
    ):
        return "JP"

    if any(
        x in t
        for x in (
            " korean ",
            " korea ",
            " kr version ",
            " kr edition ",
            " kr ",
        )
    ):
        return "KR"

    if any(
        x in t
        for x in (
            " simplified chinese ",
            " chinese ",
            " china ",
            " cn version ",
            " cn edition ",
            " cn ",
        )
    ):
        return "CN"

    if " import " in t:
        return "UNKNOWN"

    return "GLOBAL_STANDARD"


def language(f):
    return {
        "GLOBAL_STANDARD":
            "English",

        "JP":
            "Japanese",

        "KR":
            "Korean",

        "CN":
            "Simplified Chinese",

        "UNKNOWN":
            "Unknown",

    }.get(
        f,
        "Unknown",
    )


def escape_json_string_whitespace(raw):
    """Escape literal LF/CR/TAB inside strings; leave all other syntax intact."""
    out = []
    quoted = False
    escaped = False
    for char in raw:
        if quoted and not escaped and char in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[char])
            continue
        out.append(char)
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
    return "".join(out)


def jsonld_objects(text):
    out = []

    for m in JSON_LD.finditer(
        text or ""
    ):

        try:
            raw = m.group(1).strip()
            try:
                p = json.loads(raw)
            except json.JSONDecodeError:
                p = json.loads(escape_json_string_whitespace(raw))

        except Exception:
            continue

        out.extend(
            p
            if isinstance(
                p,
                list,
            )
            else [
                p
            ]
        )

    return out


def identity_url(value):
    try:
        parsed = urlparse(str(value))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        return (parsed.hostname.lower().removeprefix("www."), parsed.path.rstrip("/"))
    except ValueError:
        return None


def schema_matches_url(schema, url):
    expected = identity_url(url)
    if not expected:
        return False
    claimed = schema.get("url")
    if claimed and identity_url(claimed) != expected:
        return False
    offers = schema.get("offers") or []
    if isinstance(offers, dict):
        offers = [offers]
    links = [o.get("url") for o in offers if isinstance(o, dict) and o.get("url")] if isinstance(offers, list) else []
    return bool((claimed or links) and all(identity_url(v) == expected for v in links))


def product_schema(text, expected_url=None):
    q = list(
        jsonld_objects(
            text
        )
    )

    products = []
    while q:
        x = q.pop(
            0
        )

        if isinstance(
            x,
            list,
        ):
            q.extend(
                x
            )

            continue

        if not isinstance(
            x,
            dict,
        ):
            continue

        typ = x.get(
            "@type"
        )

        types = (
            {
                str(v).lower()
                for v in typ
            }
            if isinstance(
                typ,
                list,
            )
            else {
                str(
                    typ
                    or ""
                ).lower()
            }
        )

        if "product" in types:
            products.append(x)

        if isinstance(
            x.get(
                "@graph"
            ),
            list,
        ):
            q.extend(
                x[
                    "@graph"
                ]
            )

    if expected_url:
        matched = [x for x in products if schema_matches_url(x, expected_url)]
        if len(matched) == 1:
            return matched[0]
        # Preserve old URL-less single-product pages, but never choose a
        # different product or an arbitrary recommendation from a graph.
        if not matched and len(products) == 1:
            x = products[0]
            offers = x.get("offers") or []
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list):
                return None
            if not x.get("url") and not any(o.get("url") for o in offers if isinstance(o, dict)):
                return x
        return None
    return products[0] if len(products) == 1 else None


def product_identity(title, schema, url):
    """Game evidence from the title or the exact product's explicit brand."""
    if is_event_listing(title, schema.get("category", ""), url) or is_non_tcg_merchandise(title):
        return None, "UNKNOWN", "TCG Product", "REJECTED"
    game = classify_game(title)
    if game:
        return game, category(title), product_type(title), "TITLE"
    if not schema_matches_url(schema, url):
        return None, "UNKNOWN", "TCG Product", "NO_PRODUCT_IDENTITY"
    cat = category(title)
    if (re.match(r"^pok[eé]mon\b", clean(title), re.I)
            and cat in {"SEALED", "ACCESSORY"}
            and not any(term in clean(title).lower() for term in UNSUPPORTED)):
        return "Pokemon", cat, product_type(title), "POKEMON_TITLE_AND_FORMAT"
    brand = schema.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    brand = clean(brand) if isinstance(brand, str) else ""
    if brand.casefold() in {"magic: the gathering", "magic the gathering", "mtg"}:
        details = mtg_product_details("MTG " + title)
        if details:
            return "MTG", details[0], details[1], "EXACT_PRODUCT_BRAND_AND_FORMAT"
    return None, "UNKNOWN", "TCG Product", "NO_SUPPORTED_GAME"


def offer(schema):
    o = (
        schema.get(
            "offers"
        )
        if isinstance(
            schema,
            dict,
        )
        else None
    )

    if isinstance(
        o,
        list,
    ):
        return next(
            (
                x
                for x in o
                if isinstance(
                    x,
                    dict,
                )
            ),
            None,
        )

    return (
        o
        if isinstance(
            o,
            dict,
        )
        else None
    )


def parse_price(
    schema,
    o,
):
    raw = (
        (
            o.get(
                "price"
            )
            or
            o.get(
                "lowPrice"
            )
        )
        if isinstance(
            o,
            dict,
        )
        else None
    )

    cur = (
        o.get(
            "priceCurrency"
        )
        if isinstance(
            o,
            dict,
        )
        else None
    )

    p = normalize_price(
        raw
    )

    if (
        p is not None
        and p <= 0
    ):
        p = None

    return (
        p,
        clean(
            cur
        ).upper()
        or "USD",
    )


def parse_availability(
    schema,
    o,
):
    raw = ""

    if isinstance(
        o,
        dict,
    ):
        raw = clean(
            o.get(
                "availability"
            )
            or
            o.get(
                "itemAvailability"
            )
        ).lower()

    if (
        not raw
        and
        isinstance(
            schema,
            dict,
        )
    ):
        raw = clean(
            schema.get(
                "availability"
            )
        ).lower()

    if "instock" in raw:
        return (
            True,
            True,
            "IN_STOCK",
            "JSON_LD_OFFER_AVAILABILITY",
        )

    if (
        "outofstock" in raw
        or
        "soldout" in raw
    ):
        return (
            False,
            True,
            "OUT_OF_STOCK",
            "JSON_LD_OFFER_AVAILABILITY",
        )

    if (
        "preorder" in raw
        or
        "pre-order" in raw
    ):
        return (
            True,
            True,
            "PREORDER",
            "JSON_LD_OFFER_AVAILABILITY",
        )

    return (
        False,
        False,
        "UNKNOWN",
        "UNKNOWN",
    )


def parse_title(
    schema,
    text,
):
    t = (
        clean(
            schema.get(
                "name"
            )
        )
        if isinstance(
            schema,
            dict,
        )
        else ""
    )

    if t:
        return t

    m = OG_TITLE.search(
        text
        or ""
    )

    if m:
        return clean(
            m.group(
                1
            )
        )

    m = TITLE.search(
        text
        or ""
    )

    return (
        clean(
            m.group(
                1
            )
        )
        if m
        else ""
    )


def parse_image(
    schema,
    text,
):
    img = (
        schema.get(
            "image"
        )
        if isinstance(
            schema,
            dict,
        )
        else None
    )

    if (
        isinstance(
            img,
            str,
        )
        and
        img.strip()
    ):
        return img.strip()

    if isinstance(
        img,
        list,
    ):
        for x in img:

            if (
                isinstance(
                    x,
                    str,
                )
                and
                x.strip()
            ):
                return x.strip()

            if (
                isinstance(
                    x,
                    dict,
                )
                and
                clean(
                    x.get(
                        "url"
                    )
                )
            ):
                return clean(
                    x.get(
                        "url"
                    )
                )

    if (
        isinstance(
            img,
            dict,
        )
        and
        clean(
            img.get(
                "url"
            )
        )
    ):
        return clean(
            img.get(
                "url"
            )
        )

    m = OG_IMAGE.search(
        text or ""
    )

    return (
        clean(
            m.group(
                1
            )
        )
        if m
        else None
    )


def priority(url):
    u = str(
        url
        or ""
    ).lower()

    return sum(
        10
        for x in TCG_PRIORITY
        if x in u
    )


@retailer_adapter(
    "bigcommerce"
)
class BigCommerceAdapter(
    RetailerAdapter
):

    platform = "bigcommerce"

    def __init__(
        self,
        *,
        domain,
        region="US",
        store_name=None,
        request_delay=DEFAULT_REQUEST_DELAY,
        max_product_pages=MAX_PRODUCT_PAGES,
    ):
        super().__init__(

            domain=domain,

            region=region,

            store_name=store_name,
        )

        self.domain = (
            normalize_domain(
                self.domain
            )
        )

        self.base_url = (
            f"https://{self.domain}"
        )

        self.request_delay = max(
            float(
                request_delay
            ),
            0.5,
        )

        self.max_product_pages = max(
            1,
            min(
                int(
                    max_product_pages
                ),
                MAX_PRODUCT_PAGES,
            ),
        )

        self.diagnostics = {}

        self.known_product_urls = set()
        self.discovery_budget_seconds = None
        self._discovery_deadline = None
        self.uses_catalog_delta = starcity_host(self.domain)
        self._scg_delta = False
        self._scg_sources_by_url = {}
        if self.uses_catalog_delta:
            self.max_product_pages = min(self.max_product_pages, SCG_PRODUCT_LIMIT)
            self.discovery_budget_seconds = SCG_DISCOVERY_SECONDS

        self._reset()


    def _reset(
        self,
    ):
        self.diagnostics = {
            "adapter_version": VERSION,
            "discovery_profile": "SCG_SEALED_CATALOG" if self.uses_catalog_delta else "GENERIC_SITEMAP",
            "discovery_scope": "SUPPORTED_SEALED_PRODUCTS" if self.uses_catalog_delta else "GENERIC_PRODUCTS",
            "rejection_reasons": {},

            "pages_checked":
                0,

            "pages_successful":
                0,

            "pages_failed":
                0,

            "product_urls_discovered":
                0,

            "product_pages_successful":
                0,

            "products_accepted":
                0,

            "products_rejected":
                0,

            "adapter_unknown_availability":
                0,

            "adapter_missing_prices":
                0,

            "sitemaps_seen":
                0,

            "last_error":
                None,
        }


    def get_diagnostics(
        self,
    ):
        return dict(
            self.diagnostics
        )


    def _budget_expired(self):
        return (self._discovery_deadline is not None
                and time.monotonic() >= self._discovery_deadline)

    async def _get(
        self,
        session,
        url,
    ):
        if self._budget_expired():
            return None
        timeout = DEFAULT_TIMEOUT
        if self._discovery_deadline is not None:
            timeout = min(timeout, max(0.001, self._discovery_deadline - time.monotonic()))
        self.diagnostics[
            "pages_checked"
        ] += 1

        try:

            async with session.get(

                url,

                timeout=(
                    aiohttp.ClientTimeout(
                        total=timeout
                    )
                ),

                allow_redirects=True,

            ) as r:

                if r.status >= 400:

                    self.diagnostics[
                        "pages_failed"
                    ] += 1

                    print(f"BIGCOMMERCE PAGE SKIPPED | Store={self.store_name} | URL={url} | Reason=HTTP_ERROR | Status={r.status}")
                    return None

                self.diagnostics[
                    "pages_successful"
                ] += 1

                return await r.text(
                    errors="ignore"
                )

        except (
            asyncio.TimeoutError,
            aiohttp.ClientError,
        ) as e:

            self.diagnostics[
                "pages_failed"
            ] += 1

            self.diagnostics[
                "last_error"
            ] = (
                f"{type(e).__name__}: {e}"
            )

            print(f"BIGCOMMERCE PAGE SKIPPED | Store={self.store_name} | URL={url} | Reason=FETCH_ERROR | Error={type(e).__name__}")
            return None


    async def _discover_starcity(self, session):
        # The general 10,000-URL cap never reaches SCG's recent catalog.
        # Always check the highest numbered product sitemap, then rotate
        # older maps. Sitemap rank is discovery evidence, never stock evidence.
        root = await self._get(session, self.base_url + "/xmlsitemap.php")
        if not root:
            return []
        maps = {}
        for raw in LOC.findall(root):
            url = clean(raw)
            page = starcity_sitemap_page(url)
            if page is not None:
                maps[page] = url
        if not maps:
            self.diagnostics["last_error"] = "SCG_PRODUCT_SITEMAPS_NOT_FOUND"
            return []
        self.diagnostics["sitemaps_seen"] += 1
        pages = sorted(maps, reverse=True)
        self.diagnostics["catalog_sitemap_count"] = len(pages)
        self.diagnostics["catalog_head_page"] = pages[0]
        older = pages[1:]
        cursor = _SCG_SITEMAP_CURSOR.get(self.domain, 0) % max(1, len(older))
        count = min(1 if self._scg_delta else 3, len(older))
        selected = [pages[0]] + [older[(cursor + i) % len(older)] for i in range(count)]
        all_urls = set()
        candidates = []
        self._scg_sources_by_url = {}
        self.diagnostics["catalog_pages_read"] = []
        known = {identity_url(u) for u in self.known_product_urls}
        for page in selected:
            if self._budget_expired():
                break
            await asyncio.sleep(self.request_delay)
            sitemap_url = maps[page]
            body = await self._get(session, sitemap_url)
            if not body:
                continue
            self.diagnostics["sitemaps_seen"] += 1
            self.diagnostics["catalog_pages_read"].append(page)
            if page != pages[0]:
                _SCG_SITEMAP_CURSOR[self.domain] = (older.index(page) + 1) % len(older)
            batch = set()
            for raw in LOC.findall(body):
                url = clean(raw)
                ident = identity_url(url)
                if not ident or ident[0] != "starcitygames.com":
                    continue
                all_urls.add(url)
                # Known SCG SKU URL prefixes identify candidates only. Product
                # metadata must still prove the game, packaging, price/stock.
                if SCG_SEALED_URL.search(urlparse(url).path):
                    batch.add(url)
            ranked = sorted(batch, key=lambda u: (-priority(u), u))
            last = _SCG_LAST_PRODUCT.get((self.domain, sitemap_url))
            if last in ranked:
                start = ranked.index(last) + 1
                ranked = ranked[start:] + ranked[:start]
            for url in ranked:
                self._scg_sources_by_url[url] = sitemap_url
                if url not in candidates:
                    candidates.append(url)
        self.diagnostics["product_urls_discovered"] = len(all_urls)
        self.diagnostics["catalog_sealed_candidates"] = len(candidates)
        # New candidates first; delta scans leave known URLs to fast refresh.
        unseen = [u for u in candidates if identity_url(u) not in known]
        if self._scg_delta:
            candidates = unseen
        else:
            candidates = unseen + [u for u in candidates if identity_url(u) in known]
        selected_urls = candidates[:self.max_product_pages]
        print(f"BIGCOMMERCE SCG DISCOVERY | Store={self.store_name} | Adapter={VERSION} | "
              f"Scope=SUPPORTED_SEALED_PRODUCTS | CatalogSitemaps={len(pages)} | "
              f"PagesRead={self.diagnostics['catalog_pages_read']} | "
              f"URLs={len(all_urls)} | SealedCandidates={self.diagnostics['catalog_sealed_candidates']} | "
              f"Selected={len(selected_urls)} | Delta={self._scg_delta}")
        return selected_urls

    async def discover_delta_products(self, known_urls, limit=12):
        """Bounded SCG new-page discovery, using the same parser as validation."""
        if not self.uses_catalog_delta:
            return []
        old = (self.max_product_pages, self.discovery_budget_seconds, self._scg_delta,
               self.known_product_urls)
        try:
            self.set_known_product_urls(known_urls)
            self.max_product_pages = max(1, min(int(limit), 12))
            self.discovery_budget_seconds = SCG_DELTA_SECONDS
            self._scg_delta = True
            return await self.get_normalized_products()
        finally:
            (self.max_product_pages, self.discovery_budget_seconds, self._scg_delta,
             self.known_product_urls) = old

    async def _discover(
        self,
        session,
    ):
        if self.uses_catalog_delta:
            return await self._discover_starcity(session)
        queue = [

            urljoin(
                self.base_url + "/",
                p.lstrip(
                    "/"
                ),
            )

            for p in SITEMAP_PATHS
        ]

        visited = set()

        urls = set()

        while (
            queue
            and not self._budget_expired()
            and
            len(
                visited
            ) < MAX_SITEMAPS
            and
            len(
                urls
            ) < MAX_DISCOVERED_URLS
        ):

            u = queue.pop(
                0
            )

            if u in visited:
                continue

            visited.add(
                u
            )

            text = (
                await self._get(
                    session,
                    u,
                )
            )

            if not text:
                continue

            locs = [

                clean(
                    x
                )

                for x in LOC.findall(
                    text
                )
            ]

            if not locs:
                continue

            self.diagnostics[
                "sitemaps_seen"
            ] += 1

            for loc in locs:

                if (
                    not loc
                    or
                    not same_domain(
                        loc,
                        self.domain,
                    )
                ):
                    continue

                low = (
                    loc.lower()
                )

                if (
                    low.endswith(
                        ".xml"
                    )
                    or
                    "sitemap" in low
                ):

                    if (
                        loc not in visited
                        and
                        loc not in queue
                    ):
                        queue.append(
                            loc
                        )

                else:

                    urls.add(
                        loc
                    )

                    if (
                        len(
                            urls
                        )
                        >= MAX_DISCOVERED_URLS
                    ):
                        break

            await asyncio.sleep(
                self.request_delay
            )

        ranked = sorted(

            urls,

            key=lambda x: (
                x in self.known_product_urls,
                -priority(
                    x
                ),
                x,
            ),
        )

        if self.discovery_budget_seconds is not None:
            # Stable ordering prevents changing known/unknown membership from
            # moving the cursor backwards after newly discovered rows are saved.
            ranked = sorted(urls, key=lambda x: (-priority(x), x))
            last = _DISCOVERY_LAST_URL.get(self.domain)
            if last in ranked:
                start = ranked.index(last) + 1
                ranked = ranked[start:] + ranked[:start]
        selected = ranked[:self.max_product_pages]

        self.diagnostics[
            "product_urls_discovered"
        ] = len(
            urls
        )

        print(
            (
                "BIGCOMMERCE DISCOVERY | "
                f"Store={self.store_name} | "
                f"Sitemaps={self.diagnostics['sitemaps_seen']} | "
                f"TotalURLs={len(urls)} | "
                f"SelectedForFetch={len(selected)}"
            )
        )

        return selected


    async def fetch_products(
        self,
    ):
        self._reset()
        self._discovery_deadline = (
            time.monotonic() + self.discovery_budget_seconds
            if self.discovery_budget_seconds is not None else None
        )

        try:
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
            }

            raw = []

            async with aiohttp.ClientSession(

                headers=headers,

                connector=(
                    aiohttp.TCPConnector(
                        limit=4,
                        limit_per_host=2,
                    )
                ),

            ) as session:

                for url in (
                    await self._discover(
                        session
                    )
                ):

                    if self._budget_expired():
                        break
                    # Advance even after a failed fetch; retry on the next full pass.
                    if self.discovery_budget_seconds is not None:
                        _DISCOVERY_LAST_URL[self.domain] = url
                    if self.uses_catalog_delta and url in self._scg_sources_by_url:
                        _SCG_LAST_PRODUCT[(self.domain, self._scg_sources_by_url[url])] = url
                    text = (
                        await self._get(
                            session,
                            url,
                        )
                    )

                    if not text:
                        continue

                    schema = (
                        product_schema(
                            text, expected_url=url
                        )
                    )

                    if not isinstance(schema, dict):
                        print(f"BIGCOMMERCE PAGE SKIPPED | Store={self.store_name} | URL={url} | Reason=NO_PRODUCT_SCHEMA")
                        continue

                    raw.append(
                        {
                            "url":
                                url,

                            "html":
                                text,

                            "schema":
                                schema,
                        }
                    )

                    self.diagnostics[
                        "product_pages_successful"
                    ] += 1

                    await asyncio.sleep(
                        self.request_delay
                    )

            print(
                (
                    "BIGCOMMERCE FETCH COMPLETE | "
                    f"Store={self.store_name} | "
                    f"ProductURLs="
                    f"{self.diagnostics['product_urls_discovered']} | "
                    f"ProductPages="
                    f"{self.diagnostics['product_pages_successful']} | "
                    f"RawProducts={len(raw)}"
                )
            )

            print(f"BIGCOMMERCE DISCOVERY PROGRESS | Store={self.store_name} | BudgetExpired={self._budget_expired()} | ReturnedPages={len(raw)} | LastURL={_DISCOVERY_LAST_URL.get(self.domain)} | ProgressScope=PROCESS_LIFETIME")
            return raw


        finally:
            self._discovery_deadline = None


    def set_known_product_urls(
        self,
        urls,
    ):
        self.known_product_urls = {

            str(
                url
            ).strip()

            for url in (
                urls
                or []
            )

            if str(
                url
                or ""
            ).strip()
        }


    async def fetch_products_from_urls(
        self,
        urls,
    ):
        self._reset()

        unique = []

        seen = set()

        for url in (
            urls
            or []
        ):

            clean_url = str(
                url
                or ""
            ).strip()

            if (
                not clean_url
                or
                clean_url in seen
                or
                not same_domain(
                    clean_url,
                    self.domain,
                )
            ):
                continue

            seen.add(
                clean_url
            )

            unique.append(
                clean_url
            )

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
        }

        raw = []

        semaphore = (
            asyncio.Semaphore(
                3
            )
        )

        async with aiohttp.ClientSession(

            headers=headers,

            connector=(
                aiohttp.TCPConnector(
                    limit=4,
                    limit_per_host=3,
                )
            ),

        ) as session:

            async def fetch_one(
                url,
            ):

                async with semaphore:

                    text = (
                        await self._get(
                            session,
                            url,
                        )
                    )

                    if text:

                        schema = (
                            product_schema(
                                text, expected_url=url
                            )
                        )

                        if not isinstance(schema, dict):
                            print(f"BIGCOMMERCE PAGE SKIPPED | Store={self.store_name} | URL={url} | Reason=NO_PRODUCT_SCHEMA")
                        if isinstance(
                            schema,
                            dict,
                        ):

                            raw.append(
                                {
                                    "url":
                                        url,

                                    "html":
                                        text,

                                    "schema":
                                        schema,
                                }
                            )

                            self.diagnostics[
                                "product_pages_successful"
                            ] += 1

                    await asyncio.sleep(
                        self.request_delay
                    )

            await asyncio.gather(

                *(
                    fetch_one(
                        url
                    )

                    for url in unique
                )
            )

        self.diagnostics[
            "product_urls_discovered"
        ] = len(
            unique
        )

        print(
            (
                "BIGCOMMERCE FAST REFRESH COMPLETE | "
                f"Store={self.store_name} | "
                f"RequestedURLs={len(unique)} | "
                f"ProductPages="
                f"{self.diagnostics['product_pages_successful']}"
            )
        )

        return raw


    async def get_normalized_products_from_urls(
        self,
        urls,
    ):
        raw_products = (
            await self.fetch_products_from_urls(
                urls
            )
        )

        normalized_products = []

        seen_urls = set()

        for raw_product in (
            raw_products
            or []
        ):

            try:

                normalized = (
                    self.normalize_product(
                        raw_product
                    )
                )

            except Exception as error:

                print(
                    (
                        "RETAILER FAST NORMALIZE ERROR | "
                        f"Store={self.store_name} | "
                        f"Platform={self.platform} | "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )
                )

                continue

            if normalized is None:
                continue

            if hasattr(
                normalized,
                "to_dict",
            ):

                item = (
                    normalized.to_dict()
                )

            elif isinstance(
                normalized,
                dict,
            ):

                item = dict(
                    normalized
                )

            else:
                continue

            url = str(
                item.get(
                    "url"
                )
                or ""
            ).strip()

            if (
                not url
                or
                url in seen_urls
            ):
                continue

            seen_urls.add(
                url
            )

            normalized_products.append(
                item
            )

        return normalized_products


    def normalize_product(
        self,
        p,
    ):

        if not isinstance(
            p,
            dict,
        ):

            self.diagnostics[
                "products_rejected"
            ] += 1

            return None

        url = clean(
            p.get(
                "url"
            )
        )

        text = (
            p.get(
                "html"
            )
            or ""
        )

        schema = (
            p.get(
                "schema"
            )
        )

        if (
            not url
            or
            not isinstance(
                schema,
                dict,
            )
        ):

            self.diagnostics[
                "products_rejected"
            ] += 1

            return None

        title = (
            parse_title(
                schema,
                text,
            )
        )

        if is_non_tcg_merchandise(
            title
        ):
            self.diagnostics[
                "products_rejected"
            ] += 1

            print(
                (
                    "BIGCOMMERCE PAGE SKIPPED | "
                    f"Store={self.store_name} | "
                    f"URL={url} | "
                    "Reason=NON_TCG_MERCHANDISE | "
                    f"Title={title}"
                )
            )

            return None

        game, cat, ptype, game_source = product_identity(title, schema, url)

        if not game:

            self.diagnostics[
                "products_rejected"
            ] += 1

            reasons = self.diagnostics["rejection_reasons"]
            reasons[game_source] = reasons.get(game_source, 0) + 1
            print(f"BIGCOMMERCE PAGE SKIPPED | Store={self.store_name} | Adapter={VERSION} | "
                  f"URL={url} | Reason={game_source} | Title={title}")

            return None

        o = offer(
            schema
        )

        (
            price,
            currency,
        ) = (
            parse_price(
                schema,
                o,
            )
        )

        if price is None:

            self.diagnostics[
                "adapter_missing_prices"
            ] += 1

        (
            available,
            known,
            state,
            source,
        ) = (
            parse_availability(
                schema,
                o,
            )
        )

        if not known:

            self.diagnostics[
                "adapter_unknown_availability"
            ] += 1

        fam = (
            family(
                title
            )
        )

        image = (
            parse_image(
                schema,
                text,
            )
        )

        pstate = {

            "IN_STOCK":
                "STOCK_AVAILABLE",

            "OUT_OF_STOCK":
                "SOLD_OUT",

            "PREORDER":
                "PREORDER",

        }.get(
            state,
            "PAGE_LIVE",
        )

        sku = (
            clean(
                schema.get(
                    "sku"
                )
            )
            or None
        )

        ext = (
            clean(
                schema.get(
                    "productID"
                )
                or
                schema.get(
                    "mpn"
                )
                or
                sku
            )
            or None
        )

        capability = (
            "FULL_AVAILABILITY"
            if known
            else (
                "DISCOVERY_PRICE_ONLY"
                if price is not None
                else "DISCOVERY_ONLY"
            )
        )

        pdata = {
            "game_source": game_source,
            "adapter_version": VERSION,

            "adapter":
                "bigcommerce",

            "availability_known":
                known,

            "availability_state":
                state,

            "availability_source":
                source,

            "availability_capability":
                capability,

            "language":
                language(
                    fam
                ),

            "structured_data":
                "JSON_LD_PRODUCT",
        }

        self.diagnostics[
            "products_accepted"
        ] += 1

        print(
            (
                "BIGCOMMERCE TCG ACCEPTED | "
                f"Store={self.store_name} | "
                f"Game={game} | "
                f"Category={cat} | "
                f"Family={fam} | "
                f"Price={price} {currency} | "
                f"PriceKnown={price is not None} | "
                f"Availability={state} | "
                f"AvailabilitySource={source} | "
                f"AvailabilityCapability={capability} | "
                f"Title={title}"
            )
        )

        return RetailerProduct(

            external_id=ext,

            title=title,

            game=game,

            url=url,

            price=price,

            currency=currency,

            available=available,

            product_type=ptype,

            product_category=cat,

            product_family=fam,

            product_state=pstate,

            image_url=image,

            vendor=(
                self.store_name
            ),

            tags=None,

            sku=sku,

            external_product_id=ext,

            offer_id=None,

            variant_id=None,

            purchase_limit=None,

            cart_base_url=None,

            platform_data=pdata,
        )
