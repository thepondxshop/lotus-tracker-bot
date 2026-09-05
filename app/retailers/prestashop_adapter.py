"""
Lotus Tracker Bot / PonDeX Trackers
PrestaShop Universal Retailer Adapter
Version 1.0.4
Step 6J-3C2 — Universal Scan Performance Bounds

Safety:
- Public storefront pages, robots.txt, and public sitemap GETs only
- No authentication guessing or private PrestaShop Webservice access
- No login, cart mutation, or checkout automation
- No CAPTCHA / queue / anti-bot bypass
- Conservative bounded discovery and request pacing
- Availability is trusted only from explicit product-scoped public signals
- Unknown availability never means sold out
- Non-positive/missing prices are treated as unknown
- Product family/language is never inferred from currency
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from urllib.parse import urljoin, urlparse, urlunparse

import aiohttp

from app.retailer_adapter import RetailerAdapter, RetailerProduct, normalize_price
from app.retailer_registry import retailer_adapter


VERSION = "1.0.4"
USER_AGENT = "LotusTracker/1.0.4 (PonDeX Trackers; public retailer monitor)"
DEFAULT_TIMEOUT = 15
DEFAULT_REQUEST_DELAY = 0.70

MAX_SITEMAPS = 25
MAX_DISCOVERY_PAGES = 40
MAX_DISCOVERED_URLS = 12000
MAX_PRODUCT_PAGES = 200
MAX_LINKS_PER_PAGE = 2500

SITEMAP_PATHS = (
    "/1_index_sitemap.xml",
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/index_sitemap.xml",
)

HTML_DISCOVERY_PATHS = (
    "/",
    "/sitemap",
    "/en/sitemap",
    "/es/sitemap",
    "/fr/sitemap",
    "/it/sitemap",
    "/sv/sitemap",
    "/site-map",
    "/plan-du-site",
    "/mapa-del-sitio",
    "/new-products",
    "/best-sales",
)

TCG_PRIORITY = (
    "pokemon",
    "pokémon",
    "one-piece",
    "onepiece",
    "one_piece",
    "gundam",
    "fusion-world",
    "fusion_world",
    "riftbound",
    "palworld",
    "naruto",
    "cyberpunk",
    "azuki",
    "hellbreak",
    "booster",
    "deck",
    "tcg",
    "trading-card",
    "trading_card",
    "card-game",
    "card_game",
    "single",
    "preorder",
    "pre-order",
    "preventa",
)

DISCOVERY_PRIORITY = TCG_PRIORITY + (
    "new-products",
    "best-sales",
    "preventa",
    "preorder",
    "pre-order",
    "trading-card",
    "trading_card",
    "card-game",
    "card_game",
    "cards",
    "cartes",
    "pokemon-tcg",
    "one-piece-card-game",
)

UNSUPPORTED = (
    "magic the gathering",
    "magic: the gathering",
    "magic-the-gathering",
    "yu-gi-oh",
    "yugioh",
    "lorcana",
    "digimon",
    "weiss schwarz",
    "weiss-schwarz",
    "union arena",
    "union-arena",
    "flesh and blood",
    "flesh-and-blood",
    "star wars unlimited",
    "star-wars-unlimited",
    "warhammer",
    "games workshop",
    "games-workshop",
)

GAME_TERMS = {
    "Gundam": (
        "gundam card game",
        "gundam tcg",
        "gundam-card-game",
        "gundam-tcg",
    ),
    "Dragon Ball Fusion World": (
        "dragon ball fusion world",
        "fusion world tcg",
        "dbscg fusion world",
        "dragon-ball-fusion-world",
        "fusion-world-tcg",
        "dbscg-fusion-world",
    ),
    "Riftbound": (
        "riftbound",
        "riftbound league of legends",
        "riftbound-tcg",
    ),
    "Palworld": (
        "palworld tcg",
        "palworld card game",
        "palworld-tcg",
        "palworld-card-game",
    ),
    "Naruto": (
        "naruto tcg",
        "naruto card game",
        "naruto-tcg",
        "naruto-card-game",
    ),
    "Cyberpunk TCG": (
        "cyberpunk tcg",
        "cyberpunk trading card game",
        "cyberpunk-tcg",
        "cyberpunk-trading-card-game",
    ),
    "Azuki TCG": (
        "azuki tcg",
        "azuki trading card game",
        "azuki-tcg",
        "azuki-trading-card-game",
    ),
    "Hellbreak TCG": (
        "hellbreak tcg",
        "hellbreak trading card game",
        "hellbreak-tcg",
        "hellbreak-trading-card-game",
    ),
}

SEALED_TERMS = (
    "booster box",
    "booster display",
    "display box",
    "booster pack",
    "booster bundle",
    "elite trainer box",
    " etb",
    "starter deck",
    "battle deck",
    "structure deck",
    "collection box",
    "collection set",
    "special collection",
    "premium collection",
    "figure collection",
    "v box",
    "vstar box",
    "v star",
    "world championship deck",
    "world championships deck",
    "build & battle stadium",
    "build and battle stadium",
    "deluxe box",
    "deluxe pack",
    "double pack",
    "blister",
    "mini tin",
    " tin",
    "case",
    "display",
    "gift collection",
    "gift set",
    "illustration box",
    "special pack set",
    "deck set",
    "boite de",
    "boîte de",
    "lot de boosters",
    "pack 2 boosters",
    "pack 3 boosters",
    "sobres",
    "mazos",
)

SINGLE_TERMS = (
    "single card",
    "tcg single",
    "card single",
    "singles",
    "individual card",
    "black star promo",
    "promo card",
    "carte à l'unité",
    "carte a l'unite",
)

ACCESSORY_TERMS = (
    "sleeves",
    "deck box",
    "binder",
    "playmat",
    "play mat",
    "portfolio",
    "toploader",
    "top loader",
    "fundas",
    "tapete",
    "classeur",
)

ONE_PIECE_CARD_CODE = re.compile(
    r"\b(?:OP|EB|PRB|ST|EX)\d{1,2}-\d{2,4}\b",
    re.I,
)

ONE_PIECE_SET_CODE = re.compile(
    r"\b(?:OP|EB|PRB|ST|EX)[\s-]?\d{1,2}\b",
    re.I,
)

POKEMON_NUMBER = re.compile(
    r"\b\d{1,4}\s*/\s*\d{1,4}\b"
)

JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)

LOC = re.compile(
    r"<loc>\s*(.*?)\s*</loc>",
    re.I | re.S,
)

HREF = re.compile(
    r'''href\s*=\s*["']([^"']+)["']''',
    re.I,
)

OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)

OG_TITLE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
    re.I,
)

OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)

OG_IMAGE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.I,
)

TITLE = re.compile(
    r"<title[^>]*>(.*?)</title>",
    re.I | re.S,
)

H1 = re.compile(
    r"<h1[^>]*>(.*?)</h1>",
    re.I | re.S,
)

SKU_PATTERNS = (
    re.compile(
        r'''itemprop=["']sku["'][^>]+content=["']([^"']+)["']''',
        re.I,
    ),
    re.compile(
        r'''content=["']([^"']+)["'][^>]+itemprop=["']sku["']''',
        re.I,
    ),
    re.compile(
        r'''["']sku["']\s*:\s*["']([^"']+)["']''',
        re.I,
    ),
    re.compile(
        r"(?:Reference|Référence|Referencia|Artikelnummer)\s*:?\s*</?[^>]*>?\s*([A-Za-z0-9_.:/-]{1,80})",
        re.I,
    ),
)

PRICE_PATTERNS = (
    re.compile(
        r'''itemprop=["']price["'][^>]{0,250}?content=["']([0-9][0-9\s.,]*)["']''',
        re.I,
    ),
    re.compile(
        r'''content=["']([0-9][0-9\s.,]*)["'][^>]{0,250}?itemprop=["']price["']''',
        re.I,
    ),
    re.compile(
        r'''property=["']product:price:amount["'][^>]{0,250}?content=["']([0-9][0-9\s.,]*)["']''',
        re.I,
    ),
    re.compile(
        r'''content=["']([0-9][0-9\s.,]*)["'][^>]{0,250}?property=["']product:price:amount["']''',
        re.I,
    ),
    re.compile(
        r'''class=["'][^"']*(?:current-price-value|product-price|current-price)[^"']*["'][^>]{0,300}?(?:content=["']([0-9][0-9\s.,]*)["']|>\s*([0-9][0-9\s.,]*))''',
        re.I | re.S,
    ),
)

CURRENCY_PATTERNS = (
    re.compile(
        r'''itemprop=["']priceCurrency["'][^>]{0,250}?content=["']([A-Z]{3})["']''',
        re.I,
    ),
    re.compile(
        r'''content=["']([A-Z]{3})["'][^>]{0,250}?itemprop=["']priceCurrency["']''',
        re.I,
    ),
    re.compile(
        r'''property=["']product:price:currency["'][^>]{0,250}?content=["']([A-Z]{3})["']''',
        re.I,
    ),
    re.compile(
        r'''["']priceCurrency["']\s*:\s*["']([A-Z]{3})["']''',
        re.I,
    ),
)

SCHEMA_AVAILABILITY = re.compile(
    r'''(?:itemprop=["']availability["'][^>]{0,300}?(?:href|content)=["']([^"']+)["']|(?:href|content)=["']([^"']+)["'][^>]{0,300}?itemprop=["']availability["'])''',
    re.I,
)

PRODUCT_AVAILABILITY_META = re.compile(
    r'''property=["']product:availability["'][^>]{0,250}?content=["']([^"']+)["']''',
    re.I,
)

PRODUCT_AVAILABILITY_BLOCK = re.compile(
    r'''<(?:span|div|p)[^>]+(?:id|class)=["'][^"']*(?:product-availability|availability)[^"']*["'][^>]*>(.*?)</(?:span|div|p)>''',
    re.I | re.S,
)

REGION_CURRENCY = {
    "AT": "EUR",
    "BE": "EUR",
    "DE": "EUR",
    "ES": "EUR",
    "FI": "EUR",
    "FR": "EUR",
    "IE": "EUR",
    "IT": "EUR",
    "NL": "EUR",
    "PT": "EUR",
    "SE": "SEK",
    "NO": "NOK",
    "DK": "DKK",
    "GB": "GBP",
    "UK": "GBP",
    "CA": "CAD",
    "US": "USD",
    "AU": "AUD",
    "JP": "JPY",
    "KR": "KRW",
}


def clean(value):

    if value is None:
        return ""

    value = html_lib.unescape(
        str(value)
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def normalize_domain(value):

    value = re.sub(
        r"^https?://",
        "",
        str(
            value
            or ""
        ).strip(),
        flags=re.I,
    )

    return value.strip("/")


def normalize_url(url):

    try:

        parsed = urlparse(
            str(
                url
                or ""
            ).strip()
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            return ""

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path
                or "/",
                "",
                "",
                "",
            )
        )

    except Exception:

        return ""


def same_domain(
    url,
    domain,
):

    try:

        host = (
            urlparse(
                url
            )
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
            or
            host.endswith(
                "." + dom
            )
            or
            dom.endswith(
                "." + host
            )
        )

    except Exception:

        return False


def url_path(url):

    try:

        return (
            urlparse(
                url
            ).path
            or "/"
        ).lower()

    except Exception:

        return ""


def is_asset_or_account_url(url):

    path = url_path(
        url
    )

    if not path:
        return True

    blocked_suffixes = (
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
        ".xml",
    )

    if path.endswith(
        blocked_suffixes
    ):
        return True

    blocked_terms = (
        "/login",
        "/signin",
        "/sign-in",
        "/my-account",
        "/account",
        "/cart",
        "/basket",
        "/checkout",
        "/order",
        "/contact",
        "/privacy",
        "/terms",
        "/cookie",
        "/module/",
        "/search",
        "/manufacturer/",
        "/supplier/",
        "/brand/",
        "/stores",
        "/our-stores",
    )

    return any(
        term in path
        for term in blocked_terms
    )


def url_priority(url):

    lowered = str(
        url
        or ""
    ).lower()

    score = sum(
        10
        for term in TCG_PRIORITY
        if term in lowered
    )

    path = url_path(
        url
    )

    if path.endswith(
        ".html"
    ):
        score += 8

    if re.search(
        r"/\d{2,}-[^/]+\.html$",
        path,
    ):
        score += 15

    if any(
        part in path
        for part in (
            "/product/",
            "/products/",
            "/produit/",
            "/produkt/",
        )
    ):
        score += 15

    return score


def looks_like_tcg_discovery_url(url):

    path = url_path(
        url
    )

    if is_asset_or_account_url(
        url
    ):
        return False

    return any(
        term in path
        for term in DISCOVERY_PRIORITY
    )


def looks_like_product_url(url):

    path = url_path(
        url
    )

    if is_asset_or_account_url(
        url
    ):
        return False

    if re.search(
        r"/\d{2,}-[^/]+\.html$",
        path,
    ):
        return True

    if (
        path.endswith(
            ".html"
        )
        and
        any(
            term in path
            for term in TCG_PRIORITY
        )
    ):
        return True

    if any(
        part in path
        for part in (
            "/product/",
            "/products/",
            "/produit/",
            "/produkt/",
        )
    ):
        return True

    game_path_terms = (
        "/pokemon/",
        "/pokemon-tcg/",
        "/one-piece/",
        "/one-piece-card-game/",
        "/gundam/",
        "/gundam-card-game/",
        "/riftbound/",
        "/palworld/",
        "/cyberpunk/",
        "/fusion-world/",
        "/dragon-ball-fusion-world/",
        "/naruto/",
        "/azuki/",
        "/hellbreak/",
    )

    if any(
        term in path
        for term in game_path_terms
    ):

        parts = [
            part
            for part in path.split("/")
            if part
        ]

        return len(parts) >= 2

    return False


def extract_links(
    text,
    page_url,
    domain,
):

    output = []
    seen = set()

    for raw_href in HREF.findall(
        text
        or ""
    )[:MAX_LINKS_PER_PAGE]:

        href = html_lib.unescape(
            raw_href
        ).strip()

        if (
            not href
            or
            href.startswith(
                (
                    "#",
                    "mailto:",
                    "tel:",
                    "javascript:",
                )
            )
        ):
            continue

        absolute = normalize_url(
            urljoin(
                page_url,
                href,
            )
        )

        if (
            not absolute
            or
            absolute in seen
            or
            not same_domain(
                absolute,
                domain,
            )
        ):
            continue

        seen.add(
            absolute
        )

        output.append(
            absolute
        )

    return output


def classify_game(
    title,
    url="",
):

    title_text = clean(
        title
    ).lower()

    url_text = (
        str(
            url
            or ""
        )
        .lower()
        .replace(
            "_",
            "-",
        )
    )

    combined = (
        f" {title_text} "
        f"{url_text} "
    )

    if not title_text:
        return None

    if any(
        term in combined
        for term in UNSUPPORTED
    ):
        return None

    if (
        "one piece card game"
        in combined

        or
        "one piece tcg"
        in combined

        or
        "one-piece-card-game"
        in combined

        or
        "one-piece-tcg"
        in combined

        or
        ONE_PIECE_CARD_CODE.search(
            title
            or ""
        )
    ):
        return "One Piece"

    pokemon_direct = (
        "pokemon tcg",
        "pokémon tcg",
        "pokemon trading card",
        "pokémon trading card",
        "pokemon card game",
        "pokémon card game",
        "pokemon-tcg",
    )

    if any(
        term in combined
        for term in pokemon_direct
    ):
        return "Pokemon"

    if (
        "pokemon"
        in url_text

        or
        "pokémon"
        in url_text
    ):

        safe_url_context = any(
            term in url_text
            for term in (
                "booster",
                "cartes",
                "card",
                "tcg",
                "/pokemon/",
                "pokemon-",
            )
        )

        if safe_url_context:
            return "Pokemon"

    for (
        game,
        terms,
    ) in GAME_TERMS.items():

        if any(
            term in combined
            for term in terms
        ):
            return game

    return None


def product_category(title):

    text = clean(
        title
    ).lower()

    if ONE_PIECE_CARD_CODE.search(
        title
        or ""
    ):
        return "SINGLE"

    if (
        POKEMON_NUMBER.search(
            title
            or ""
        )
        and
        (
            "pokemon"
            in text

            or
            "pokémon"
            in text
        )
    ):
        return "SINGLE"

    if any(
        term in text
        for term in SINGLE_TERMS
    ):
        return "SINGLE"

    if any(
        term in text
        for term in SEALED_TERMS
    ):
        return "SEALED"

    if any(
        term in text
        for term in ACCESSORY_TERMS
    ):
        return "ACCESSORY"

    return "UNKNOWN"


def product_type(title):

    category = product_category(
        title
    )

    if category == "SINGLE":
        return "Single Card"

    text = clean(
        title
    ).lower()

    mapping = (
        (
            (
                "elite trainer box",
                " etb",
            ),
            "Elite Trainer Box",
        ),
        (
            (
                "booster box",
                "booster display",
                "display box",
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
                "starter deck display",
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
                "premium card collection",
            ),
            "Premium Collection",
        ),
        (
            (
                "double pack",
                "double-pack",
            ),
            "Double Pack",
        ),
        (
            (
                "illustration box",
            ),
            "Illustration Box",
        ),
        (
            (
                "gift collection",
                "gift set",
            ),
            "Gift Collection",
        ),
        (
            (
                "special pack set",
            ),
            "Special Pack Set",
        ),
        (
            (
                "mini tin",
            ),
            "Mini Tin",
        ),
        (
            (
                " tin",
            ),
            "Tin",
        ),
        (
            (
                "playmat",
                "play mat",
                "tapete",
            ),
            "Playmat",
        ),
        (
            (
                "sleeves",
                "fundas",
            ),
            "Sleeves",
        ),
        (
            (
                "binder",
                "portfolio",
                "classeur",
            ),
            "Binder",
        ),
        (
            (
                "deck box",
            ),
            "Deck Box",
        ),
        (
            (
                "case",
            ),
            "Case",
        ),
    )

    for (
        terms,
        label,
    ) in mapping:

        if any(
            term in text
            for term in terms
        ):
            return label

    return "TCG Product"


def product_family(title):

    text = (
        f" {clean(title).lower()} "
    )

    jp_terms = (
        " japanese ",
        " japan ",
        " jp version ",
        " jp edition ",
        " jp ",
        " japonés ",
        " japones ",
        " japonais ",
        " giapponese ",
        " japansk ",
        " japanska ",
    )

    kr_terms = (
        " korean ",
        " korea ",
        " kr version ",
        " kr edition ",
        " kr ",
        " coreano ",
        " coréen ",
        " coreen ",
        " koreansk ",
        " koreanska ",
    )

    cn_terms = (
        " simplified chinese ",
        " chinese ",
        " china ",
        " cn version ",
        " cn edition ",
        " cn ",
        " chino ",
        " chinois ",
        " kinesisk ",
        " kinesiska ",
    )

    import_terms = (
        " import ",
        " imported ",
        " importado ",
        " importé ",
        " importe ",
    )

    if any(
        term in text
        for term in jp_terms
    ):
        return "JP"

    if any(
        term in text
        for term in kr_terms
    ):
        return "KR"

    if any(
        term in text
        for term in cn_terms
    ):
        return "CN"

    if any(
        term in text
        for term in import_terms
    ):
        return "UNKNOWN"

    return "GLOBAL_STANDARD"


def family_language(family):

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
        family,
        "Unknown",
    )


def jsonld_objects(text):

    output = []

    for match in JSON_LD.finditer(
        text
        or ""
    ):

        raw = html_lib.unescape(
            match.group(
                1
            ).strip()
        )

        try:

            parsed = json.loads(
                raw
            )

        except Exception:

            continue

        output.extend(
            parsed
            if isinstance(
                parsed,
                list,
            )
            else [
                parsed
            ]
        )

    return output


def product_schema(text):

    queue = list(
        jsonld_objects(
            text
        )
    )

    while queue:

        item = queue.pop(
            0
        )

        if isinstance(
            item,
            list,
        ):
            queue.extend(
                item
            )

            continue

        if not isinstance(
            item,
            dict,
        ):
            continue

        raw_type = item.get(
            "@type"
        )

        types = (
            {
                str(value).lower()
                for value in raw_type
            }
            if isinstance(
                raw_type,
                list,
            )
            else {
                str(
                    raw_type
                    or ""
                ).lower()
            }
        )

        if "product" in types:
            return item

        graph = item.get(
            "@graph"
        )

        if isinstance(
            graph,
            list,
        ):
            queue.extend(
                graph
            )

    return None


def first_offer(schema):

    offers = (
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
        offers,
        list,
    ):

        return next(
            (
                offer
                for offer in offers
                if isinstance(
                    offer,
                    dict,
                )
            ),
            None,
        )

    return (
        offers
        if isinstance(
            offers,
            dict,
        )
        else None
    )


def parse_decimal_text(raw):

    value = (
        clean(
            raw
        )
        .replace(
            "\xa0",
            " ",
        )
        .replace(
            " ",
            "",
        )
    )

    if not value:
        return None

    if (
        ","
        in value
        and
        "."
        in value
    ):

        if (
            value.rfind(
                ","
            )
            >
            value.rfind(
                "."
            )
        ):

            value = (
                value
                .replace(
                    ".",
                    "",
                )
                .replace(
                    ",",
                    ".",
                )
            )

        else:

            value = value.replace(
                ",",
                "",
            )

    elif "," in value:

        tail = value.rsplit(
            ",",
            1,
        )[-1]

        if len(
            tail
        ) in {
            1,
            2,
        }:

            value = (
                value
                .replace(
                    ".",
                    "",
                )
                .replace(
                    ",",
                    ".",
                )
            )

        else:

            value = value.replace(
                ",",
                "",
            )

    price = normalize_price(
        value
    )

    if (
        price is not None
        and
        price <= 0
    ):
        return None

    return price


def region_currency(region):

    return REGION_CURRENCY.get(
        clean(
            region
        ).upper(),
        "USD",
    )


def parse_price(
    schema,
    offer,
    text,
    region,
):

    fallback_currency = region_currency(
        region
    )

    if isinstance(
        offer,
        dict,
    ):

        raw = (
            offer.get(
                "price"
            )
            or
            offer.get(
                "lowPrice"
            )
        )

        currency = (
            clean(
                offer.get(
                    "priceCurrency"
                )
            ).upper()
            or
            fallback_currency
        )

        price = parse_decimal_text(
            raw
        )

        if price is not None:

            return (
                price,
                currency,
                "JSON_LD_OFFER_PRICE",
            )

    html_price = None

    for pattern in PRICE_PATTERNS:

        match = pattern.search(
            text
            or ""
        )

        if not match:
            continue

        raw = next(
            (
                group
                for group in match.groups()
                if group
            ),
            "",
        )

        html_price = parse_decimal_text(
            raw
        )

        if html_price is not None:
            break

    currency = ""

    for pattern in CURRENCY_PATTERNS:

        match = pattern.search(
            text
            or ""
        )

        if match:

            currency = clean(
                match.group(
                    1
                )
            ).upper()

            break

    if not currency:

        currency = fallback_currency

    if html_price is not None:

        return (
            html_price,
            currency,
            "PUBLIC_PRODUCT_PRICE_MARKUP",
        )

    return (
        None,
        currency,
        "UNKNOWN",
    )


def normalize_availability_token(raw):

    compact = re.sub(
        r"[^a-z]",
        "",
        clean(
            raw
        ).lower(),
    )

    if (
        "instock"
        in compact

        or
        "limitedavailability"
        in compact
    ):
        return (
            True,
            True,
            "IN_STOCK",
        )

    if (
        "outofstock"
        in compact

        or
        "soldout"
        in compact

        or
        "discontinued"
        in compact
    ):
        return (
            False,
            True,
            "OUT_OF_STOCK",
        )

    if (
        "preorder"
        in compact

        or
        "presale"
        in compact
    ):
        return (
            True,
            True,
            "PREORDER",
        )

    if (
        "backorder"
        in compact

        or
        "backordered"
        in compact
    ):
        return (
            False,
            True,
            "BACKORDER",
        )

    return (
        False,
        False,
        "UNKNOWN",
    )


def parse_availability(
    schema,
    offer,
    text,
):

    raw = ""

    if isinstance(
        offer,
        dict,
    ):

        raw = clean(
            offer.get(
                "availability"
            )
            or
            offer.get(
                "itemAvailability"
            )
        )

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
        )

    if raw:

        (
            available,
            known,
            state,
        ) = normalize_availability_token(
            raw
        )

        if known:

            return (
                available,
                known,
                state,
                "JSON_LD_OFFER_AVAILABILITY",
                "HIGH",
            )

    match = SCHEMA_AVAILABILITY.search(
        text
        or ""
    )

    if match:

        raw = next(
            (
                group
                for group in match.groups()
                if group
            ),
            "",
        )

        (
            available,
            known,
            state,
        ) = normalize_availability_token(
            raw
        )

        if known:

            return (
                available,
                known,
                state,
                "SCHEMA_ORG_AVAILABILITY_MARKUP",
                "HIGH",
            )

    match = PRODUCT_AVAILABILITY_META.search(
        text
        or ""
    )

    if match:

        (
            available,
            known,
            state,
        ) = normalize_availability_token(
            match.group(
                1
            )
        )

        if known:

            return (
                available,
                known,
                state,
                "PRODUCT_AVAILABILITY_META",
                "HIGH",
            )

    block = PRODUCT_AVAILABILITY_BLOCK.search(
        text
        or ""
    )

    if block:

        block_text = clean(
            block.group(
                1
            )
        ).lower()

        if any(
            term in block_text
            for term in (
                "out of stock",
                "sold out",
                "stock épuisé",
                "stock epuise",
                "rupture de stock",
                "agotado",
                "sin stock",
                "slutsåld",
                "slutsald",
                "slut i lager",
            )
        ):

            return (
                False,
                True,
                "OUT_OF_STOCK",
                "PRODUCT_AVAILABILITY_BLOCK",
                "MEDIUM",
            )

        if any(
            term in block_text
            for term in (
                "pre-order",
                "preorder",
                "précommande",
                "precommande",
                "preventa",
                "förbeställ",
                "forbestall",
            )
        ):

            return (
                True,
                True,
                "PREORDER",
                "PRODUCT_AVAILABILITY_BLOCK",
                "MEDIUM",
            )

        if any(
            term in block_text
            for term in (
                "in stock",
                "en stock",
                "available",
                "disponible",
                "i lager",
            )
        ):

            return (
                True,
                True,
                "IN_STOCK",
                "PRODUCT_AVAILABILITY_BLOCK",
                "MEDIUM",
            )

    plain = clean(
        text
    ).lower()

    quantity_match = re.search(
        r"(?:quantit[eé]\s+en\s+stock|quantity\s+in\s+stock|stock\s+quantity)\s*:?\s*(\d+)",
        plain,
        re.I,
    )

    if quantity_match:

        quantity = int(
            quantity_match.group(
                1
            )
        )

        if quantity > 0:

            return (
                True,
                True,
                "IN_STOCK",
                "EXPLICIT_PRODUCT_STOCK_QUANTITY",
                "MEDIUM",
            )

        return (
            False,
            True,
            "OUT_OF_STOCK",
            "EXPLICIT_PRODUCT_STOCK_QUANTITY",
            "MEDIUM",
        )

    if any(
        term in plain
        for term in (
            "produkten är tyvärr slut i lager",
            "produkten ar tyvarr slut i lager",
            "0 disponible stock épuisé",
            "0 disponible stock epuise",
        )
    ):

        return (
            False,
            True,
            "OUT_OF_STOCK",
            "EXPLICIT_PRODUCT_STATUS_TEXT",
            "MEDIUM",
        )

    status_match = re.search(
        r"product status\s*:?\s*(pre[- ]?order|available|backorder)",
        plain,
        re.I,
    )

    if status_match:

        status = (
            status_match
            .group(
                1
            )
            .lower()
            .replace(
                " ",
                "-",
            )
        )

        if status in {
            "pre-order",
            "preorder",
        }:

            return (
                True,
                True,
                "PREORDER",
                "EXPLICIT_PRODUCT_STATUS_FIELD",
                "MEDIUM",
            )

        if status == "available":

            return (
                True,
                True,
                "IN_STOCK",
                "EXPLICIT_PRODUCT_STATUS_FIELD",
                "MEDIUM",
            )

        if status == "backorder":

            return (
                False,
                True,
                "BACKORDER",
                "EXPLICIT_PRODUCT_STATUS_FIELD",
                "MEDIUM",
            )

    return (
        False,
        False,
        "UNKNOWN",
        "UNKNOWN",
        "LOW",
    )


def parse_title(
    schema,
    text,
):

    title = (
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

    if title:
        return title

    for pattern in (
        OG_TITLE,
        OG_TITLE_REVERSED,
        H1,
        TITLE,
    ):

        match = pattern.search(
            text
            or ""
        )

        if match:

            return clean(
                match.group(
                    1
                )
            )

    return ""


def parse_image(
    schema,
    text,
):

    image = (
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
            image,
            str,
        )
        and
        image.strip()
    ):
        return image.strip()

    if isinstance(
        image,
        list,
    ):

        for item in image:

            if (
                isinstance(
                    item,
                    str,
                )
                and
                item.strip()
            ):
                return item.strip()

            if (
                isinstance(
                    item,
                    dict,
                )
                and
                clean(
                    item.get(
                        "url"
                    )
                )
            ):

                return clean(
                    item.get(
                        "url"
                    )
                )

    if (
        isinstance(
            image,
            dict,
        )
        and
        clean(
            image.get(
                "url"
            )
        )
    ):

        return clean(
            image.get(
                "url"
            )
        )

    for pattern in (
        OG_IMAGE,
        OG_IMAGE_REVERSED,
    ):

        match = pattern.search(
            text
            or ""
        )

        if match:

            return clean(
                match.group(
                    1
                )
            )

    return None


def parse_sku(
    schema,
    text,
):

    if isinstance(
        schema,
        dict,
    ):

        sku = clean(
            schema.get(
                "sku"
            )
            or
            schema.get(
                "mpn"
            )
        )

        if sku:
            return sku

    for pattern in SKU_PATTERNS:

        match = pattern.search(
            text
            or ""
        )

        if match:

            value = clean(
                match.group(
                    1
                )
            )

            if value:
                return value

    return None


def has_product_page_evidence(
    schema,
    text,
    url,
):

    if isinstance(
        schema,
        dict,
    ):
        return True

    sku = parse_sku(
        None,
        text,
    )

    if sku:
        return True

    if looks_like_product_url(
        url
    ):

        for pattern in PRICE_PATTERNS[
            :4
        ]:

            if pattern.search(
                text
                or ""
            ):
                return True

    return False


@retailer_adapter(
    "prestashop"
)
class PrestaShopAdapter(
    RetailerAdapter
):

    platform = "prestashop"

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

        self.domain = normalize_domain(
            self.domain
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

        self._reset_diagnostics()


    def _reset_diagnostics(
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

            "rejected_products":
                0,

            "adapter_unknown_availability":
                0,

            "adapter_missing_prices":
                0,

            "backorder_products":
                0,

            "sitemaps_seen":
                0,

            "html_discovery_pages":
                0,

            "xml_product_candidates":
                0,

            "html_product_candidates":
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

            ) as response:

                if response.status >= 400:

                    self.diagnostics[
                        "pages_failed"
                    ] += 1

                    return (
                        None,
                        None,
                    )

                self.diagnostics[
                    "pages_successful"
                ] += 1

                final_url = (
                    normalize_url(
                        str(
                            response.url
                        )
                    )
                    or
                    normalize_url(
                        url
                    )
                )

                return (
                    await response.text(
                        errors="ignore"
                    ),
                    final_url,
                )

        except (
            asyncio.TimeoutError,
            aiohttp.ClientError,
        ) as error:

            self.diagnostics[
                "pages_failed"
            ] += 1

            self.diagnostics[
                "last_error"
            ] = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            return (
                None,
                None,
            )


    async def _discover_xml(
        self,
        session,
    ):

        queue = [

            urljoin(
                self.base_url + "/",
                path.lstrip(
                    "/"
                ),
            )

            for path in SITEMAP_PATHS
        ]

        visited = set()

        candidates = set()

        robots_url = urljoin(
            self.base_url + "/",
            "robots.txt",
        )

        robots_text, _ = (
            await self._get(
                session,
                robots_url,
            )
        )

        if robots_text:

            for raw in re.findall(
                r"(?im)^\s*Sitemap\s*:\s*(\S+)",
                robots_text,
            ):

                sitemap_url = normalize_url(
                    html_lib.unescape(
                        raw
                    )
                )

                if (
                    sitemap_url
                    and
                    same_domain(
                        sitemap_url,
                        self.domain,
                    )
                    and
                    sitemap_url not in queue
                ):

                    queue.append(
                        sitemap_url
                    )

        while (
            queue
            and
            len(
                visited
            ) < MAX_SITEMAPS
            and
            len(
                candidates
            ) < MAX_DISCOVERED_URLS
        ):

            sitemap_url = queue.pop(
                0
            )

            if sitemap_url in visited:
                continue

            visited.add(
                sitemap_url
            )

            text, final_url = (
                await self._get(
                    session,
                    sitemap_url,
                )
            )

            if not text:
                continue

            locations = [

                clean(
                    value
                )

                for value in LOC.findall(
                    text
                )
            ]

            if not locations:
                continue

            self.diagnostics[
                "sitemaps_seen"
            ] += 1

            for location in locations:

                location = normalize_url(
                    location
                )

                if (
                    not location
                    or
                    not same_domain(
                        location,
                        self.domain,
                    )
                ):
                    continue

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
                        location not in visited
                        and
                        location not in queue
                    ):

                        queue.append(
                            location
                        )

                elif not is_asset_or_account_url(
                    location
                ):

                    candidates.add(
                        location
                    )

                    if (
                        len(
                            candidates
                        )
                        >= MAX_DISCOVERED_URLS
                    ):
                        break

            await asyncio.sleep(
                self.request_delay
            )

        self.diagnostics[
            "xml_product_candidates"
        ] = len(
            candidates
        )

        return candidates


    async def _discover_html(
        self,
        session,
    ):

        seed_urls = [

            urljoin(
                self.base_url + "/",
                path.lstrip(
                    "/"
                ),
            )

            for path in HTML_DISCOVERY_PATHS
        ]

        queue = []

        queued = set()

        for url in seed_urls:

            normalized = normalize_url(
                url
            )

            if (
                normalized
                and
                normalized not in queued
            ):

                queue.append(
                    (
                        normalized,
                        0,
                    )
                )

                queued.add(
                    normalized
                )

        visited = set()

        candidates = set()

        while (
            queue
            and
            len(
                visited
            ) < MAX_DISCOVERY_PAGES
            and
            len(
                candidates
            ) < MAX_DISCOVERED_URLS
        ):

            page_url, depth = (
                queue.pop(
                    0
                )
            )

            if page_url in visited:
                continue

            visited.add(
                page_url
            )

            text, final_url = (
                await self._get(
                    session,
                    page_url,
                )
            )

            if not text:
                continue

            self.diagnostics[
                "html_discovery_pages"
            ] += 1

            effective_url = (
                final_url
                or
                page_url
            )

            for link in extract_links(

                text,

                effective_url,

                self.domain,

            ):

                if looks_like_product_url(
                    link
                ):

                    candidates.add(
                        link
                    )

                    if (
                        len(
                            candidates
                        )
                        >= MAX_DISCOVERED_URLS
                    ):
                        break

                if depth >= 2:
                    continue

                if (
                    looks_like_tcg_discovery_url(
                        link
                    )
                    and
                    link not in visited
                    and
                    link not in queued
                ):

                    queue.append(
                        (
                            link,
                            depth + 1,
                        )
                    )

                    queued.add(
                        link
                    )

            await asyncio.sleep(
                self.request_delay
            )

        self.diagnostics[
            "html_product_candidates"
        ] = len(
            candidates
        )

        return candidates


    async def _discover(
        self,
        session,
    ):

        xml_candidates = (
            await self._discover_xml(
                session
            )
        )

        html_candidates = (
            await self._discover_html(
                session
            )
        )

        product_urls = set(
            xml_candidates
        )

        product_urls.update(
            html_candidates
        )

        ranked = sorted(

            product_urls,

            key=lambda value: (
                value
                in self.known_product_urls,
                -url_priority(
                    value
                ),
                value,
            ),
        )

        selected = ranked[
            :self.max_product_pages
        ]

        self.diagnostics[
            "product_urls_discovered"
        ] = len(
            product_urls
        )

        print(
            (
                "PRESTASHOP DISCOVERY | "
                f"Store={self.store_name} | "
                f"XmlSitemaps="
                f"{self.diagnostics['sitemaps_seen']} | "
                f"HtmlDiscoveryPages="
                f"{self.diagnostics['html_discovery_pages']} | "
                f"XmlCandidates="
                f"{self.diagnostics['xml_product_candidates']} | "
                f"HtmlCandidates="
                f"{self.diagnostics['html_product_candidates']} | "
                f"TotalCandidates={len(product_urls)} | "
                f"SelectedForFetch={len(selected)}"
            )
        )

        return selected


    async def fetch_products(
        self,
    ):

        self._reset_diagnostics()

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

        raw_products = []

        async with aiohttp.ClientSession(

            headers=headers,

            connector=(
                aiohttp.TCPConnector(
                    limit=4,
                    limit_per_host=2,
                )
            ),

        ) as session:

            product_urls = (
                await self._discover(
                    session
                )
            )

            for url in product_urls:

                text, final_url = (
                    await self._get(
                        session,
                        url,
                    )
                )

                if not text:
                    continue

                effective_url = (
                    final_url
                    or
                    url
                )

                schema = product_schema(
                    text
                )

                if not has_product_page_evidence(
                    schema,
                    text,
                    effective_url,
                ):
                    continue

                raw_products.append(
                    {
                        "url":
                            effective_url,

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
                "PRESTASHOP FETCH COMPLETE | "
                f"Store={self.store_name} | "
                f"ProductURLs="
                f"{self.diagnostics['product_urls_discovered']} | "
                f"ProductPages="
                f"{self.diagnostics['product_pages_successful']} | "
                f"RawProducts={len(raw_products)}"
            )
        )

        return raw_products


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

        self._reset_diagnostics()

        unique_urls = []

        seen = set()

        for url in (
            urls
            or []
        ):

            clean_url = normalize_url(
                str(
                    url
                    or ""
                ).strip()
            )

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

            unique_urls.append(
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

            "Accept-Language":
                "en-US,en;q=0.8",
        }

        raw_products = []

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

                    text, final_url = (
                        await self._get(
                            session,
                            url,
                        )
                    )

                    if text:

                        effective_url = (
                            final_url
                            or
                            url
                        )

                        schema = product_schema(
                            text
                        )

                        if has_product_page_evidence(
                            schema,
                            text,
                            effective_url,
                        ):

                            raw_products.append(
                                {
                                    "url":
                                        effective_url,

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

                    for url in unique_urls
                )
            )

        self.diagnostics[
            "product_urls_discovered"
        ] = len(
            unique_urls
        )

        print(
            (
                "PRESTASHOP FAST REFRESH COMPLETE | "
                f"Store={self.store_name} | "
                f"KnownURLs={len(unique_urls)} | "
                f"ProductPages="
                f"{self.diagnostics['product_pages_successful']}"
            )
        )

        return raw_products


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
        raw_product,
    ):

        if not isinstance(
            raw_product,
            dict,
        ):

            self.diagnostics[
                "products_rejected"
            ] += 1

            self.diagnostics[
                "rejected_products"
            ] += 1

            return None

        url = clean(
            raw_product.get(
                "url"
            )
        )

        text = (
            raw_product.get(
                "html"
            )
            or ""
        )

        schema = raw_product.get(
            "schema"
        )

        if (
            schema is not None
            and
            not isinstance(
                schema,
                dict,
            )
        ):
            schema = None

        if (
            not url
            or
            not has_product_page_evidence(
                schema,
                text,
                url,
            )
        ):

            self.diagnostics[
                "products_rejected"
            ] += 1

            self.diagnostics[
                "rejected_products"
            ] += 1

            return None

        title = parse_title(
            schema,
            text,
        )

        game = classify_game(
            title,
            url=url,
        )

        if not game:

            self.diagnostics[
                "products_rejected"
            ] += 1

            self.diagnostics[
                "rejected_products"
            ] += 1

            return None

        offer = first_offer(
            schema
        )

        (
            price,
            currency,
            price_source,
        ) = parse_price(

            schema,

            offer,

            text,

            self.region,
        )

        if price is None:

            self.diagnostics[
                "adapter_missing_prices"
            ] += 1

        (
            available,
            availability_known,
            availability_state,
            availability_source,
            availability_confidence,
        ) = parse_availability(

            schema,

            offer,

            text,
        )

        if not availability_known:

            self.diagnostics[
                "adapter_unknown_availability"
            ] += 1

        if availability_state == "BACKORDER":

            self.diagnostics[
                "backorder_products"
            ] += 1

        category = product_category(
            title
        )

        ptype = product_type(
            title
        )

        family = product_family(
            title
        )

        image = parse_image(
            schema,
            text,
        )

        sku = parse_sku(
            schema,
            text,
        )

        product_state = {

            "IN_STOCK":
                "STOCK_AVAILABLE",

            "OUT_OF_STOCK":
                "SOLD_OUT",

            "PREORDER":
                "PREORDER",

            "BACKORDER":
                "BACKORDER",

        }.get(
            availability_state,
            "PAGE_LIVE",
        )

        external_id = None

        if isinstance(
            schema,
            dict,
        ):

            external_id = (
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

        if not external_id:

            external_id = (
                sku
            )

        capability = (
            "FULL_AVAILABILITY"

            if availability_known

            else (
                "DISCOVERY_PRICE_ONLY"

                if price is not None

                else "DISCOVERY_ONLY"
            )
        )

        platform_data = {

            "adapter":
                "prestashop",

            "adapter_step":
                "6J-3C2",

            "availability_known":
                availability_known,

            "availability_state":
                availability_state,

            "availability_source":
                availability_source,

            "availability_confidence":
                availability_confidence,

            "availability_capability":
                capability,

            "price_source":
                price_source,

            "language":
                family_language(
                    family
                ),

            "structured_data":
                (
                    "JSON_LD_PRODUCT"

                    if isinstance(
                        schema,
                        dict,
                    )

                    else "PUBLIC_PRODUCT_MARKUP"
                ),
        }

        self.diagnostics[
            "products_accepted"
        ] += 1

        print(
            (
                "PRESTASHOP TCG ACCEPTED | "
                f"Store={self.store_name} | "
                f"Game={game} | "
                f"Category={category} | "
                f"Family={family} | "
                f"Price={price} {currency} | "
                f"PriceKnown={price is not None} | "
                f"PriceSource={price_source} | "
                f"Availability={availability_state} | "
                f"AvailabilitySource={availability_source} | "
                f"AvailabilityCapability={capability} | "
                f"Title={title}"
            )
        )

        return RetailerProduct(

            external_id=external_id,

            title=title,

            game=game,

            url=url,

            price=price,

            currency=currency,

            available=available,

            product_type=ptype,

            product_category=category,

            product_family=family,

            product_state=product_state,

            image_url=image,

            vendor=(
                self.store_name
            ),

            tags=None,

            sku=sku,

            external_product_id=external_id,

            offer_id=None,

            variant_id=None,

            purchase_limit=None,

            cart_base_url=None,

            platform_data=(
                platform_data
            ),
        )
