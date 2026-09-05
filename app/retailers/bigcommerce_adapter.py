"""
Lotus Tracker Bot / PonDeX Trackers
BigCommerce Universal Retailer Adapter
Version 1.0.4
Step 6J-2B — BigCommerce Classification + Diagnostic Integrity

Public storefront + sitemap GETs only.
No auth guessing, cart mutation, checkout automation, CAPTCHA/queue bypass.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from urllib.parse import urljoin, urlparse

import aiohttp

from app.retailer_adapter import RetailerAdapter, RetailerProduct, normalize_price
from app.retailer_registry import retailer_adapter

VERSION = "1.0.4"
USER_AGENT = "LotusTracker/1.0.4 (PonDeX Trackers; public retailer monitor)"
DEFAULT_TIMEOUT = 15
DEFAULT_REQUEST_DELAY = 0.65
MAX_SITEMAPS = 20
MAX_DISCOVERED_URLS = 10000
MAX_PRODUCT_PAGES = 200

SITEMAP_PATHS = ("/xmlsitemap.php", "/sitemap.xml", "/sitemap_index.xml")
TCG_PRIORITY = (
    "pokemon","one-piece","onepiece","gundam","fusion-world","riftbound",
    "palworld","naruto","cyberpunk","azuki","hellbreak","booster","deck","tcg","card","single",
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
    "Hellbreak TCG": ("hellbreak tcg","hellbreak trading card game"),
}
SEALED = (
    "booster box","booster display","booster pack","booster bundle","elite trainer box",
    "starter deck","battle deck","structure deck","collection box","collection set",
    "special collection","premium collection","figure collection","v box","vstar box",
    "v star","world championship deck","world championships deck","build & battle stadium",
    "build and battle stadium","deluxe box","deluxe pack","double pack","blister","tin","case"
)
SINGLE = ("single card","tcg single","card single","singles","individual card","black star promo","promo card")
ACCESSORY = ("sleeves","deck box","binder","playmat","play mat","portfolio","toploader","top loader")
ONE_PIECE_CODE = re.compile(r"\b(?:OP|EB|PRB|ST|EX)\d{1,2}-\d{2,4}\b", re.I)
POKEMON_NUMBER = re.compile(r"\b\d{1,4}\s*/\s*\d{1,4}\b")
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


def classify_game(title):
    t = clean(title).lower()

    if not t:
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


def jsonld_objects(text):
    out = []

    for m in JSON_LD.finditer(
        text or ""
    ):

        try:
            p = json.loads(
                m.group(1).strip()
            )

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


def product_schema(text):
    q = list(
        jsonld_objects(
            text
        )
    )

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
            return x

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

    return None


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

        self._reset()


    def _reset(
        self,
    ):
        self.diagnostics = {

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


    async def _get(
        self,
        session,
        url,
    ):
        self.diagnostics[
            "pages_checked"
        ] += 1

        try:

            async with session.get(

                url,

                timeout=(
                    aiohttp.ClientTimeout(
                        total=DEFAULT_TIMEOUT
                    )
                ),

                allow_redirects=True,

            ) as r:

                if r.status >= 400:

                    self.diagnostics[
                        "pages_failed"
                    ] += 1

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

            return None


    async def _discover(
        self,
        session,
    ):
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

        selected = ranked[
            :self.max_product_pages
        ]

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
                        text
                    )
                )

                if not isinstance(
                    schema,
                    dict,
                ):
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

        return raw


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
                                text
                            )
                        )

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
                f"KnownURLs={len(unique)} | "
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

        game = (
            classify_game(
                title
            )
        )

        if not game:

            self.diagnostics[
                "products_rejected"
            ] += 1

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

        cat = (
            category(
                title
            )
        )

        ptype = (
            product_type(
                title
            )
        )

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
