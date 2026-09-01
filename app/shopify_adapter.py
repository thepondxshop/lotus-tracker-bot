import re

from urllib.parse import (
    urlparse,
)

import aiohttp

from app.product_family import (
    detect_product_family,
)


# =========================================================
# LOTUS SHOPIFY ADAPTER
# PonDeX Trackers
# Version 1.0.4
# Step 6G-C - Shopify Preorder Lifecycle + Priority Discovery
#
# Strict Structured TCG Classification
# Product Family Detection
# Product Category Detection
# Native Currency
# Product Images
# Smart Cart Metadata
# Dynamic Purchasable Variant Selection
# Variant-Type Matching
# Purchase Limit Detection
# Public Inventory Quantity Detection
# Priority Preorder / Coming-Soon Collection Discovery
# Discovery Source Diagnostics
# Smart Cart Quantity Guard Metadata
#
# IMPORTANT:
# Game classification does NOT use body_html.
# =========================================================


REGION_CURRENCY = {

    "US": "USD",
    "CA": "CAD",
    "UK": "GBP",
    "GB": "GBP",
    "EU": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "NL": "EUR",
    "BE": "EUR",
    "AT": "EUR",
    "IE": "EUR",
    "PT": "EUR",
    "JP": "JPY",
    "KR": "KRW",
    "CN": "CNY",
    "AU": "AUD",
    "NZ": "NZD",
}


def normalize_shopify_domain(
    value: str,
):

    if not value:

        raise ValueError(
            "Shopify domain is empty."
        )

    value = (
        value.strip()
    )

    if not value.startswith(
        (
            "http://",
            "https://",
        )
    ):

        value = (
            "https://"
            + value
        )

    parsed = (
        urlparse(
            value
        )
    )

    hostname = (
        parsed.hostname
        or ""
    ).lower()

    if hostname.startswith(
        "www."
    ):

        hostname = (
            hostname[
                4:
            ]
        )

    if not hostname:

        raise ValueError(
            "Invalid Shopify domain."
        )

    return hostname


def normalize_text(
    value,
):

    if value is None:

        return ""

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):

        value = " ".join(
            str(item)
            for item in value
        )

    value = str(
        value
    )

    value = value.replace(
        "\u00e9",
        "e",
    )

    value = value.lower()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return (
        value.strip()
    )


# =========================================================
# STRUCTURED CLASSIFICATION TEXT
#
# body_html is intentionally EXCLUDED.
#
# We use only structured catalog identity:
# title, vendor, product_type, tags, handle.
# =========================================================

def build_classification_text(
    product,
):

    fields = (

        "title",
        "vendor",
        "product_type",
        "tags",
        "handle",
    )

    parts = []

    for field in fields:

        value = (
            product.get(
                field
            )
        )

        if value is None:

            continue

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):

            parts.extend(
                str(item)
                for item in value
            )

        else:

            parts.append(
                str(
                    value
                )
            )

    return (
        normalize_text(
            " ".join(
                parts
            )
        )
    )


# =========================================================
# LIMIT / METADATA TEXT
#
# body_html may be used for purchase-limit wording only.
# It is NOT used for TCG game classification.
# =========================================================

def build_limit_text(
    product,
):

    fields = (

        "title",
        "vendor",
        "product_type",
        "tags",
        "body_html",
    )

    parts = []

    for field in fields:

        value = (
            product.get(
                field
            )
        )

        if value is None:

            continue

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):

            parts.extend(
                str(item)
                for item in value
            )

        else:

            parts.append(
                str(
                    value
                )
            )

    return (
        normalize_text(
            " ".join(
                parts
            )
        )
    )


SEALED_CONTEXT_PATTERN = re.compile(
    r"\b("
    r"booster\s*box|"
    r"booster\s*bundle|"
    r"booster\s*pack|"
    r"booster\s*display|"
    r"display\s*box|"
    r"display|"
    r"starter\s*deck|"
    r"structure\s*deck|"
    r"collection\s*box|"
    r"collection\s*set|"
    r"gift\s*collection|"
    r"double\s*pack|"
    r"premium\s*collection|"
    r"special\s*collection|"
    r"elite\s*trainer\s*box|"
    r"etb|"
    r"blister|"
    r"case|"
    r"tin"
    r")\b",
    re.IGNORECASE,
)


ONE_PIECE_SET_PATTERN = re.compile(
    r"\b("
    r"op[-\s]?\d{1,2}|"
    r"eb[-\s]?\d{1,2}|"
    r"prb[-\s]?\d{1,2}|"
    r"st[-\s]?\d{1,2}|"
    r"ex[-\s]?\d{1,2}"
    r")\b",
    re.IGNORECASE,
)


ONE_PIECE_SINGLE_CARD_PATTERN = re.compile(
    r"\b(?:"
    r"(?:OP|EB|PRB|ST|EX)\s*-?\s*\d{1,2}\s*-\s*\d{3}"
    r"|"
    r"P\s*-?\s*\d{3}"
    r")\b",
    re.IGNORECASE,
)


UNSUPPORTED_GAME_TERMS = (

    "magic the gathering",
    "magic: the gathering",
    " mtg ",
    "yu-gi-oh",
    "yugioh",
    "lorcana",
    "digimon",
    "weiss schwarz",
    "union arena",
    "flesh and blood",
    "star wars unlimited",
    "warhammer",
    "games workshop",
)


def classify_game(
    product,
):

    text = (
        build_classification_text(
            product
        )
    )

    title = (
        normalize_text(
            product.get(
                "title"
            )
        )
    )

    if not text:

        return None

    padded_text = (
        f" {text} "
    )

    for unsupported in UNSUPPORTED_GAME_TERMS:

        if unsupported in padded_text:

            return None

    # =====================================================
    # ONE PIECE
    # =====================================================

    if (
        "one piece card game"
        in text

        or
        "one piece tcg"
        in text

        or
        (
            "one piece"
            in text

            and
            SEALED_CONTEXT_PATTERN.search(
                text
            )
        )

        or
        (
            ONE_PIECE_SET_PATTERN.search(
                title
            )

            and
            SEALED_CONTEXT_PATTERN.search(
                title
            )
        )

        or
        (
            "one piece"
            in text

            and
            ONE_PIECE_SINGLE_CARD_PATTERN.search(
                title
            )
        )
    ):

        return (
            "One Piece"
        )

    # =====================================================
    # POKEMON
    #
    # Structured tags/type/vendor may carry "Pokemon" even
    # when the title is only the set name.
    # =====================================================

    pokemon_context = (
        "pokemon"
        in text
        or
        "pok\u00e9mon"
        in text
    )

    if (
        "pokemon tcg"
        in text

        or
        "pokemon trading card"
        in text

        or
        "pokemon card game"
        in text

        or
        "pok\u00e9mon tcg"
        in text

        or
        "pok\u00e9mon trading card"
        in text

        or
        (
            pokemon_context

            and
            SEALED_CONTEXT_PATTERN.search(
                text
            )
        )
    ):

        return (
            "Pokemon"
        )

    if (
        "gundam card game"
        in text

        or
        "gundam tcg"
        in text
    ):

        return (
            "Gundam"
        )

    if (
        "dragon ball super card game fusion world"
        in text

        or
        "dragon ball fusion world"
        in text

        or
        "fusion world tcg"
        in text
    ):

        return (
            "Dragon Ball Fusion World"
        )

    if (
        "riftbound"
        in text
    ):

        return (
            "Riftbound"
        )

    if (
        "palworld card game"
        in text

        or
        "palworld tcg"
        in text

        or
        "palworld trading card"
        in text
    ):

        return (
            "Palworld"
        )

    if (
        "naruto card game"
        in text

        or
        "naruto tcg"
        in text

        or
        "naruto trading card"
        in text
    ):

        return (
            "Naruto"
        )

    if (
        "cyberpunk tcg"
        in text

        or
        "cyberpunk trading card"
        in text
    ):

        return (
            "Cyberpunk TCG"
        )

    if (
        "azuki tcg"
        in text

        or
        "azuki card game"
        in text
    ):

        return (
            "Azuki TCG"
        )

    if (
        "hellbreak tcg"
        in text

        or
        "hellbreak card game"
        in text
    ):

        return (
            "Hellbreak TCG"
        )

    return None


SINGLE_CARD_NUMBER_PATTERN = ONE_PIECE_SINGLE_CARD_PATTERN

SINGLE_CARD_DESCRIPTOR_PATTERN = re.compile(
    r"\b(?:full\s*art|alternate\s*art|alt\s*art|parallel|foil|holo|"
    r"secret\s*rare|super\s*rare|leader\s*parallel|manga\s*rare)\b",
    re.IGNORECASE,
)


def has_strong_single_evidence(
    title,
    raw_type=None,
    tags=None,
):

    title_text = normalize_text(title)
    type_text = normalize_text(raw_type)
    tag_text = normalize_text(tags)
    combined = f"{title_text} {type_text} {tag_text}".strip()

    explicit_single = any(
        keyword in combined
        for keyword in SINGLE_STRONG_KEYWORDS
    ) or type_text in {
        "single",
        "singles",
        "single card",
        "tcg single",
        "card single",
        "individual card",
    }

    if explicit_single:
        return True

    # One Piece singles commonly contain a card number such as
    # OP01-001, EB01-001, ST30-004, or P-001. A sealed deck code
    # such as ST-30 does not match this pattern.
    if SINGLE_CARD_NUMBER_PATTERN.search(title_text):
        return True

    # Descriptors strengthen single-card evidence, but do not
    # classify a product as a single by themselves.
    if (
        SINGLE_CARD_DESCRIPTOR_PATTERN.search(title_text)
        and SINGLE_CARD_NUMBER_PATTERN.search(combined)
    ):
        return True

    return False


def infer_product_type(
    title,
    raw_type=None,
    tags=None,
):

    if has_strong_single_evidence(
        title,
        raw_type,
        tags,
    ):

        return (
            "Single Card"
        )

    text = (
        normalize_text(
            title
        )
    )

    mappings = [

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
                "sleeved booster",
            ),
            "Booster Pack",
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
                "starter deck",
            ),
            "Starter Deck",
        ),

        (
            (
                "structure deck",
            ),
            "Structure Deck",
        ),

        (
            (
                "deck box",
            ),
            "Deck Box",
        ),

        (
            (
                "premium collection",
            ),
            "Premium Collection",
        ),

        (
            (
                "collection box",
                "collection set",
                "special collection",
                "gift collection",
            ),
            "Collection",
        ),

        (
            (
                "case",
            ),
            "Case",
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
                "card sleeves",
            ),
            "Sleeves",
        ),

        (
            (
                "binder",
                "portfolio",
            ),
            "Binder",
        ),
    ]

    for (
        keywords,
        label,
    ) in mappings:

        for keyword in keywords:

            if keyword in text:

                return (
                    label
                )

    cleaned_raw_type = (
        str(
            raw_type
            or ""
        ).strip()
    )

    if cleaned_raw_type:

        return (
            cleaned_raw_type
        )

    return (
        "TCG Product"
    )


SEALED_KEYWORDS = (

    "booster box",
    "booster display",
    "display box",
    "booster bundle",
    "booster pack",
    "sleeved booster",
    "elite trainer box",
    "starter deck",
    "structure deck",
    "double pack",
    "double-pack",
    "collection box",
    "collection set",
    "premium collection",
    "special collection",
    "gift collection",
    "case",
    "tin",
    "blister",
)


ACCESSORY_KEYWORDS = (

    "playmat",
    "play mat",
    "sleeves",
    "card sleeves",
    "deck box",
    "binder",
    "portfolio",
    "storage box",
    "card holder",
    "card stand",
    "accessory",
    "accessories",
)


SINGLE_STRONG_KEYWORDS = (

    "single card",
    "tcg single",
    "card single",
    "singles",
    "individual card",
)


def infer_product_category(
    title,
    raw_type=None,
    tags=None,
):

    title_text = (
        normalize_text(
            title
        )
    )

    type_text = (
        normalize_text(
            raw_type
        )
    )

    tag_text = (
        normalize_text(
            tags
        )
    )

    combined = (
        f"{title_text} "
        f"{type_text} "
        f"{tag_text}"
    ).strip()

    # =====================================================
    # STRONG SINGLE EVIDENCE WINS OVER SEALED CONTEXT
    #
    # Example:
    # Emporio.Ivankov (Full Art) (ST30-004) -
    # Starter Deck EX: Luffy & Ace Foil
    #
    # "Starter Deck" describes the card's source set.
    # ST30-004 identifies an individual card, so this must
    # be SINGLE rather than SEALED.
    # =====================================================

    if has_strong_single_evidence(
        title,
        raw_type,
        tags,
    ):

        return (
            "SINGLE"
        )

    # =====================================================
    # SEALED
    # =====================================================

    if any(
        keyword in combined
        for keyword in SEALED_KEYWORDS
    ):

        return (
            "SEALED"
        )

    # =====================================================
    # ACCESSORY
    # =====================================================

    if any(
        keyword in combined
        for keyword in ACCESSORY_KEYWORDS
    ):

        return (
            "ACCESSORY"
        )

    return (
        "UNKNOWN"
    )


def extract_image_url(
    product,
):

    images = (
        product.get(
            "images"
        )
        or []
    )

    if images:

        first = (
            images[
                0
            ]
        )

        if isinstance(
            first,
            dict,
        ):

            return (
                first.get(
                    "src"
                )
            )

        if isinstance(
            first,
            str,
        ):

            return (
                first
            )

    image = (
        product.get(
            "image"
        )
    )

    if isinstance(
        image,
        dict,
    ):

        return (
            image.get(
                "src"
            )
        )

    if isinstance(
        image,
        str,
    ):

        return (
            image
        )

    return None


PURCHASE_LIMIT_PATTERNS = [

    re.compile(
        r"\blimit\s*(?:of\s*)?(\d{1,2})\b",
        re.IGNORECASE,
    ),

    re.compile(
        r"\bmax(?:imum)?\s*(?:of\s*)?(\d{1,2})\b",
        re.IGNORECASE,
    ),

    re.compile(
        r"\b(\d{1,2})\s*per\s*(?:customer|person|household)\b",
        re.IGNORECASE,
    ),
]


def infer_purchase_limit(
    product,
):

    text = (
        build_limit_text(
            product
        )
    )

    for pattern in PURCHASE_LIMIT_PATTERNS:

        match = (
            pattern.search(
                text
            )
        )

        if not match:

            continue

        try:

            value = int(
                match.group(
                    1
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            continue

        if 1 <= value <= 100:

            return (
                value
            )

    return None


def normalize_variant_id(
    value,
):

    if value is None:

        return None

    value = (
        str(
            value
        ).strip()
    )

    if not value:

        return None

    if not value.isdigit():

        return None

    return (
        value
    )



# =========================================================
# PUBLIC VARIANT INVENTORY QUANTITY
#
# Shopify storefront payloads do not always expose an exact
# quantity. We only accept explicit non-negative integer
# values. Missing quantity remains UNKNOWN.
# =========================================================

PUBLIC_INVENTORY_KEYS = (
    "inventory_quantity",
    "inventoryQuantity",
    "quantity_available",
    "quantityAvailable",
    "available_quantity",
    "availableQuantity",
)


def variant_inventory_quantity(
    variant,
):

    if not isinstance(
        variant,
        dict,
    ):

        return (
            None,
            False,
        )

    for key in PUBLIC_INVENTORY_KEYS:

        if key not in variant:

            continue

        raw_value = (
            variant.get(
                key
            )
        )

        if isinstance(
            raw_value,
            bool,
        ):

            continue

        try:

            value = int(
                raw_value
            )

        except (
            TypeError,
            ValueError,
        ):

            continue

        if value < 0:

            continue

        return (
            value,
            True,
        )

    return (
        None,
        False,
    )

def variant_title(
    variant,
):

    if not isinstance(
        variant,
        dict,
    ):

        return None

    title = (
        variant.get(
            "title"
        )
    )

    if title is None:

        return None

    title = (
        str(
            title
        ).strip()
    )

    return (
        title
        or None
    )


def variant_price(
    variant,
):

    if not isinstance(
        variant,
        dict,
    ):

        return None

    raw_price = (
        variant.get(
            "price"
        )
    )

    try:

        if raw_price is None:

            return None

        return float(
            raw_price
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


def is_valid_cart_variant(
    variant,
):

    if not isinstance(
        variant,
        dict,
    ):

        return False

    return (
        normalize_variant_id(
            variant.get(
                "id"
            )
        )
        is not None
    )


PRODUCT_TYPE_VARIANT_KEYWORDS = {

    "Booster Box": (
        "booster box",
        "booster display",
        "display box",
        "display",
        "box",
    ),

    "Booster Bundle": (
        "booster bundle",
        "bundle",
    ),

    "Booster Pack": (
        "booster pack",
        "pack",
        "sleeved booster",
    ),

    "Elite Trainer Box": (
        "elite trainer box",
        "etb",
    ),

    "Starter Deck": (
        "starter deck",
        "starter",
    ),

    "Structure Deck": (
        "structure deck",
        "structure",
    ),

    "Double Pack": (
        "double pack",
        "double-pack",
    ),

    "Case": (
        "case",
    ),

    "Premium Collection": (
        "premium collection",
    ),

    "Collection": (
        "collection",
    ),

    "Tin": (
        "tin",
    ),

    "Playmat": (
        "playmat",
        "play mat",
    ),

    "Sleeves": (
        "sleeves",
    ),

    "Binder": (
        "binder",
        "portfolio",
    ),

    "Deck Box": (
        "deck box",
    ),
}


def variant_type_score(
    variant,
    product_type,
):

    title = (
        normalize_text(
            variant_title(
                variant
            )
        )
    )

    if not title:

        return 0

    if title in {
        "default title",
        "default",
    }:

        return 0

    keywords = (
        PRODUCT_TYPE_VARIANT_KEYWORDS.get(
            product_type,
            ()
        )
    )

    if not keywords:

        return 0

    score = 0

    for keyword in keywords:

        if keyword in title:

            score += 10

    return (
        score
    )


def choose_primary_variant(
    variants,
    product_type=None,
):

    if not variants:

        return None

    valid_variants = [

        variant

        for variant in variants

        if is_valid_cart_variant(
            variant
        )
    ]

    if not valid_variants:

        return None

    available_variants = [

        variant

        for variant in valid_variants

        if bool(
            variant.get(
                "available"
            )
        )
    ]

    pool = (
        available_variants
        or valid_variants
    )

    ranked = []

    for index, variant in enumerate(
        pool
    ):

        type_score = (
            variant_type_score(
                variant,
                product_type,
            )
        )

        price = (
            variant_price(
                variant
            )
        )

        price_sort = (
            price
            if price is not None
            else float(
                "inf"
            )
        )

        ranked.append(
            (
                -type_score,
                price_sort,
                index,
                variant,
            )
        )

    ranked.sort(
        key=lambda item: (
            item[
                0
            ],
            item[
                1
            ],
            item[
                2
            ],
        )
    )

    return (
        ranked[
            0
        ][
            3
        ]
    )


def default_family_for_store_region(
    region,
):

    region = (
        str(
            region
            or ""
        )
        .strip()
        .upper()
    )

    if region in {
        "US",
        "CA",
        "UK",
        "GB",
        "EU",
        "DE",
        "FR",
        "IT",
        "ES",
        "NL",
        "BE",
        "AT",
        "IE",
        "PT",
        "AU",
        "NZ",
    }:

        return (
            "GLOBAL_STANDARD"
        )

    return None


# =========================================================
# PUBLIC PRIORITY COLLECTION DISCOVERY
#
# Shopify storefronts can expose products in public collections
# before they are easy to find in the general catalog feed.
# Lotus uses only public GET endpoints and never accesses private
# Admin/App APIs or authenticated sales-channel data.
# =========================================================

PRIORITY_COLLECTION_TERMS = (
    "preorder",
    "pre-order",
    "pre order",
    "coming soon",
    "coming-soon",
    "new arrivals",
    "new-arrivals",
    "new products",
    "new-products",
    "one piece",
    "one-piece",
    "pokemon",
    "pokÃ©mon",
    "gundam",
    "riftbound",
    "fusion world",
    "fusion-world",
)

MAX_PRIORITY_COLLECTIONS = 20
MAX_COLLECTION_PAGES = 4


def _append_discovery_source(product, source):
    if not isinstance(product, dict):
        return
    sources = product.get("_lotus_discovery_sources")
    if not isinstance(sources, list):
        sources = []
    if source not in sources:
        sources.append(source)
    product["_lotus_discovery_sources"] = sources


def _product_dedupe_key(product):
    if not isinstance(product, dict):
        return None
    product_id = product.get("id")
    if product_id not in (None, ""):
        return f"id:{product_id}"
    handle = str(product.get("handle") or "").strip().lower()
    if handle:
        return f"handle:{handle}"
    return None


class ShopifyAdapter:

    def __init__(
        self,
        domain,
        region="US",
    ):

        self.domain = (
            normalize_shopify_domain(
                domain
            )
        )

        self.region = (
            region
            or "US"
        ).upper()

        self.base_url = (
            f"https://{self.domain}"
        )

        self.currency = (
            REGION_CURRENCY.get(
                self.region,
                "USD",
            )
        )


    async def fetch_store_currency(
        self,
    ):

        url = (
            f"{self.base_url}/cart.js"
        )

        timeout = (
            aiohttp.ClientTimeout(
                total=10
            )
        )

        try:

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                async with session.get(

                    url,

                    headers={
                        "Accept":
                            "application/json",

                        "User-Agent":
                            "PonDeX-Trackers/1.0.4",
                    },

                ) as response:

                    if response.status == 200:

                        data = (
                            await response.json(
                                content_type=None
                            )
                        )

                        currency = (
                            data.get(
                                "currency"
                            )
                        )

                        if currency:

                            self.currency = (
                                str(
                                    currency
                                )
                                .strip()
                                .upper()
                            )

                            return (
                                self.currency
                            )

        except Exception as error:

            print(
                (
                    "SHOPIFY CURRENCY DETECTION ERROR | "
                    f"{self.domain} | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

        return (
            self.currency
        )


    async def fetch_products(
        self,
        max_pages=20,
    ):

        products_by_key = {}
        anonymous_products = []

        timeout = (
            aiohttp.ClientTimeout(
                total=30
            )
        )

        headers = {

            "Accept":
                "application/json",

            "User-Agent":
                "PonDeX-Trackers/1.0.4",
        }

        async def merge_products(page_products, source):
            for product in page_products or []:
                if not isinstance(product, dict):
                    continue

                key = _product_dedupe_key(product)

                if key is None:
                    product = dict(product)
                    _append_discovery_source(product, source)
                    anonymous_products.append(product)
                    continue

                existing = products_by_key.get(key)

                if existing is None:
                    product = dict(product)
                    _append_discovery_source(product, source)
                    products_by_key[key] = product
                    continue

                existing_sources = list(
                    existing.get("_lotus_discovery_sources")
                    or []
                )

                incoming_sources = list(
                    product.get("_lotus_discovery_sources")
                    or []
                )

                for discovery_source in incoming_sources + [source]:
                    if discovery_source not in existing_sources:
                        existing_sources.append(discovery_source)

                # Prefer the newest public payload for ordinary Shopify
                # fields while preserving every discovery source.
                existing.update(product)
                existing["_lotus_discovery_sources"] = existing_sources

        async with aiohttp.ClientSession(

            timeout=timeout,

            headers=headers,

        ) as session:

            # =================================================
            # 1. GENERAL PUBLIC PRODUCT FEED
            # =================================================

            general_pages = 0

            for page in range(
                1,
                max_pages + 1,
            ):

                url = (
                    f"{self.base_url}"
                    f"/products.json"
                    f"?limit=250"
                    f"&page={page}"
                )

                async with session.get(

                    url,

                    allow_redirects=True,

                ) as response:

                    if response.status != 200:

                        raise RuntimeError(
                            (
                                "Shopify HTTP "
                                f"{response.status}"
                            )
                        )

                    data = (
                        await response.json(
                            content_type=None
                        )
                    )

                    page_products = (
                        data.get(
                            "products",
                            []
                        )
                    )

                    if not page_products:

                        break

                    general_pages += 1

                    await merge_products(
                        page_products,
                        "PRODUCTS_JSON",
                    )

                    if len(
                        page_products
                    ) < 250:

                        break

            # =================================================
            # 2. DISCOVER PUBLIC COLLECTIONS
            # =================================================

            priority_collections = []

            collections_url = (
                f"{self.base_url}/collections.json?limit=250"
            )

            try:
                async with session.get(
                    collections_url,
                    allow_redirects=True,
                ) as response:
                    if response.status == 200:
                        data = await response.json(
                            content_type=None
                        )
                        collections = data.get("collections", []) or []

                        ranked = []

                        for collection in collections:
                            if not isinstance(collection, dict):
                                continue

                            handle = str(
                                collection.get("handle")
                                or ""
                            ).strip()

                            title = normalize_text(
                                collection.get("title")
                            )

                            probe = normalize_text(
                                f"{title} {handle}"
                            )

                            score = 0

                            for term in PRIORITY_COLLECTION_TERMS:
                                if normalize_text(term) in probe:
                                    score += 10

                            if "preorder" in probe or "pre-order" in probe:
                                score += 50

                            if "coming soon" in probe or "coming-soon" in probe:
                                score += 40

                            if score > 0 and handle:
                                ranked.append((
                                    -score,
                                    handle,
                                    title,
                                ))

                        ranked.sort()

                        priority_collections = ranked[
                            :MAX_PRIORITY_COLLECTIONS
                        ]

            except Exception as error:
                print(
                    (
                        "SHOPIFY COLLECTION DISCOVERY ERROR | "
                        f"Store={self.domain} | "
                        f"{type(error).__name__}: {error}"
                    )
                )

            collection_products_seen = 0

            # =================================================
            # 3. PRIORITY PUBLIC COLLECTION PRODUCT FEEDS
            # =================================================

            for _, handle, title in priority_collections:

                for page in range(
                    1,
                    MAX_COLLECTION_PAGES + 1,
                ):

                    url = (
                        f"{self.base_url}"
                        f"/collections/{handle}/products.json"
                        f"?limit=250&page={page}"
                    )

                    try:
                        async with session.get(
                            url,
                            allow_redirects=True,
                        ) as response:
                            if response.status != 200:
                                break

                            data = await response.json(
                                content_type=None
                            )

                            page_products = (
                                data.get("products", [])
                                or []
                            )

                            if not page_products:
                                break

                            source_label = (
                                "COLLECTION:"
                                + handle
                            )

                            await merge_products(
                                page_products,
                                source_label,
                            )

                            collection_products_seen += len(
                                page_products
                            )

                            if len(page_products) < 250:
                                break

                    except Exception as error:
                        print(
                            (
                                "SHOPIFY COLLECTION FETCH ERROR | "
                                f"Store={self.domain} | "
                                f"Collection={handle} | "
                                f"{type(error).__name__}: {error}"
                            )
                        )
                        break

        products = (
            list(products_by_key.values())
            + anonymous_products
        )

        print(
            (
                "SHOPIFY DISCOVERY COMPLETE | "
                f"Store={self.domain} | "
                f"GeneralPages={general_pages} | "
                f"PriorityCollections={len(priority_collections)} | "
                f"CollectionProductsSeen={collection_products_seen} | "
                f"UniqueProducts={len(products)}"
            )
        )

        return (
            products
        )


    def normalize_product(
        self,
        product,
    ):

        title = (
            product.get(
                "title"
            )
            or "Unknown Product"
        )

        handle = (
            product.get(
                "handle"
            )
            or ""
        )

        raw_type = (
            product.get(
                "product_type"
            )
        )

        tags = (
            product.get(
                "tags"
            )
        )

        game = (
            classify_game(
                product
            )
        )

        variants = (
            product.get(
                "variants"
            )
            or []
        )

        product_type = (
            infer_product_type(
                title,
                raw_type,
                tags,
            )
        )

        available = any(

            bool(
                variant.get(
                    "available"
                )
            )

            and
            is_valid_cart_variant(
                variant
            )

            for variant in variants
        )

        primary_variant = (
            choose_primary_variant(
                variants,
                product_type=product_type,
            )
        )

        variant_id = None
        selected_variant_title = None
        selected_variant_available = False
        selected_variant_price = None
        selected_inventory_quantity = None
        selected_inventory_quantity_known = False
        sku = None

        if primary_variant:

            variant_id = (
                normalize_variant_id(
                    primary_variant.get(
                        "id"
                    )
                )
            )

            selected_variant_title = (
                variant_title(
                    primary_variant
                )
            )

            selected_variant_available = (
                bool(
                    primary_variant.get(
                        "available"
                    )
                )
            )

            selected_variant_price = (
                variant_price(
                    primary_variant
                )
            )

            (
                selected_inventory_quantity,
                selected_inventory_quantity_known,
            ) = (
                variant_inventory_quantity(
                    primary_variant
                )
            )

            raw_sku = (
                primary_variant.get(
                    "sku"
                )
            )

            if raw_sku:

                sku = (
                    str(
                        raw_sku
                    ).strip()
                )

        if (
            selected_variant_available

            and
            selected_variant_price is not None
        ):

            price = (
                selected_variant_price
            )

        else:

            all_valid_prices = []

            for variant in variants:

                if not is_valid_cart_variant(
                    variant
                ):

                    continue

                current_price = (
                    variant_price(
                        variant
                    )
                )

                if current_price is not None:

                    all_valid_prices.append(
                        current_price
                    )

            price = (
                min(
                    all_valid_prices
                )
                if all_valid_prices
                else None
            )

        url = (
            (
                f"{self.base_url}"
                f"/products/{handle}"
            )
            if handle
            else self.base_url
        )

        product_category = (
            infer_product_category(
                title,
                raw_type,
                tags,
            )
        )

        family_probe = dict(
            product
        )

        family_probe[
            "sku"
        ] = (
            sku
        )

        family_probe[
            "variant_title"
        ] = (
            selected_variant_title
        )

        product_family = (
            detect_product_family(

                family_probe,

                default=(
                    default_family_for_store_region(
                        self.region
                    )
                ),
            )
        )

        purchase_limit = (
            infer_purchase_limit(
                product
            )
        )

        lower_title = (
            title.lower()
        )

        if (
            "preorder"
            in lower_title

            or
            "pre-order"
            in lower_title

            or
            "pre order"
            in lower_title
        ):

            product_state = (
                "PREORDER_LIVE"
                if available
                else "PREORDER_PAGE"
            )

        elif available:

            product_state = (
                "STOCK_AVAILABLE"
            )

        else:

            product_state = (
                "PAGE_LIVE"
            )

        if game:

            classification_reason = "structured_game_match"

            if (
                game == "One Piece"
                and ONE_PIECE_SINGLE_CARD_PATTERN.search(
                    normalize_text(
                        title
                    )
                )
            ):

                classification_reason = (
                    "one_piece_single_card_number"
                )

            print(
                (
                    "SHOPIFY PRODUCT CLASSIFIED | "
                    f"Store={self.domain} | "
                    f"Reason={classification_reason} | "
                    f"Game={game} | "
                    f"Category={product_category} | "
                    f"Family={product_family} | "
                    f"Product={title} | "
                    f"Type={product_type} | "
                    f"Variant={variant_id} | "
                    f"VariantTitle={selected_variant_title} | "
                    f"VariantAvailable={selected_variant_available} | "
                    f"InventoryKnown={selected_inventory_quantity_known} | "
                    f"InventoryQuantity={selected_inventory_quantity} | "
                    f"Price={selected_variant_price} | "
                    f"ProductAvailable={available} | "
                    f"DiscoverySources={product.get('_lotus_discovery_sources', ['PRODUCTS_JSON'])}"
                )
            )

        return {

            "external_id":
                str(
                    product.get(
                        "id",
                        ""
                    )
                ),

            "title":
                title,

            "game":
                game,

            "url":
                url,

            "price":
                price,

            "currency":
                self.currency,

            "available":
                available,

            "product_type":
                product_type,

            "product_category":
                product_category,

            "product_family":
                product_family,

            "product_state":
                product_state,

            "image_url":
                extract_image_url(
                    product
                ),

            "vendor":
                product.get(
                    "vendor"
                ),

            "tags":
                tags,

            "handle":
                handle,

            "sku":
                sku,

            "variant_id":
                variant_id,

            "variant_title":
                selected_variant_title,

            "variant_available":
                selected_variant_available,

            "variant_price":
                selected_variant_price,

            "inventory_quantity":
                selected_inventory_quantity,

            "inventory_quantity_known":
                selected_inventory_quantity_known,

            "purchase_limit":
                purchase_limit,

            "cart_base_url":
                self.base_url,

            "discovery_sources":
                list(
                    product.get(
                        "_lotus_discovery_sources",
                        ["PRODUCTS_JSON"],
                    )
                    or ["PRODUCTS_JSON"]
                ),
        }