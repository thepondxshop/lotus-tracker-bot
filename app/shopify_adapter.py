import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET

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
# Component Version 1.0.6-C1
# Step 6K-2C1 - Shopify Rate-Limit + Large-Catalog Hardening
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
    r"deck\s*set|"
    r"special\s*set|"
    r"premium\s*set|"
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

    # Set codes overlap across games (for example Gundam EB02).
    # Use the One Piece code fallback only after explicit game matches.
    if (
        ONE_PIECE_SET_PATTERN.search(
            title
        )

        and
        SEALED_CONTEXT_PATTERN.search(
            title
        )
    ):

        return (
            "One Piece"
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
    # Pokemon collector numbers and explicit reverse-holo card titles.
    # Sealed packaging must not become a single merely by mentioning a card.
    if (
        "pokemon" in combined
        and not SEALED_CONTEXT_PATTERN.search(title_text)
        and not any(keyword in title_text for keyword in ACCESSORY_KEYWORDS)
        and (
            re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", title_text)
            or re.search(r"\breverse[\s-]+holo(?:foil)?\b", title_text)
        )
    ):
        return True

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


def infer_additional_sealed_format(title):
    """Recognize specific packaging names observed in store alerts."""
    text = normalize_text(title)
    if any(keyword in text for keyword in ACCESSORY_KEYWORDS):
        return None
    patterns = (
        (r"\bbooster\s+pack\s+display\b", "Booster Box"),
        (r"\bbooster\s*\(\s*24\s*ct\s+display\s*\)", "Booster Box"),
        (r"\bevent\s+kit\b", "Event Kit"),
        (r"\bshowdown\s+decks?\b", "Showdown Deck"),
        (r"\bchampion\s+deck\b", "Champion Deck"),
        (r"\bstarter\s*\(\s*st[-\s]?\d{1,2}\s*\)", "Starter Deck"),
    )
    for pattern, label in patterns:
        if re.search(pattern, text):
            return label
    return None


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

    additional_format = infer_additional_sealed_format(title)
    if additional_format:
        return additional_format

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
                "deck set",
            ),
            "Deck Set",
        ),

        (
            (
                "special set",
                "premium set",
            ),
            "Special Set",
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
    "deck set",
    "special set",
    "premium set",
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

    if infer_additional_sealed_format(title):
        return "SEALED"

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
# STEP 6K-2C1 — SHOPIFY RATE-LIMIT + LARGE-CATALOG HARDENING
#
# Goals:
# - serialize requests per storefront/domain
# - respectful pacing + Retry-After / exponential 429 backoff
# - scan high-value collections before the giant general feed
# - cache collection discovery so large stores are not rediscovered
#   every minute
# - periodically refresh the general product feed rather than hammering it
# - detect products newly entering an already-baselined priority collection
# - never use missing data as a sold-out signal
# =========================================================

SHOPIFY_COMPONENT_VERSION = "1.0.6-C4"
_STORE_CURRENCY_CACHE = {}
STORE_CURRENCY_CACHE_SECONDS = 3600
SHOPIFY_REQUEST_DELAY_SECONDS = 0.75
SHOPIFY_MAX_429_RETRIES = 3
SHOPIFY_MAX_5XX_RETRIES = 2
SHOPIFY_MAX_BACKOFF_SECONDS = 30.0
SHOPIFY_COLLECTION_CACHE_SECONDS = 30 * 60
SHOPIFY_GENERAL_REFRESH_SECONDS = 30
MAX_PRIORITY_COLLECTIONS = 12
MAX_COLLECTION_PAGES = 2
MAX_COLLECTION_SITEMAPS = 8
MAX_COLLECTION_JSON_PAGES = 8

PRIORITY_COLLECTION_TERMS = (
    "preorder", "pre-order", "pre order",
    "coming soon", "coming-soon",
    "new arrivals", "new-arrivals",
    "new products", "new-products",
    "one piece", "one-piece", "onepiece",
    "pokemon", "pokémon",
    "gundam",
    "dragon ball", "fusion world", "fusion-world",
    "riftbound", "palworld", "naruto",
    "cyberpunk", "azuki", "hellbreak",
    "tcg", "trading card", "card game",
)

# Per-process coordination. The monitor also has scan-level locks; these
# domain locks are the final protection against a health probe/manual scan
# hitting the same Shopify storefront while another request is in flight.
_DOMAIN_REQUEST_LOCKS = {}
_DOMAIN_LAST_REQUEST_AT = {}
_PRIORITY_COLLECTION_CACHE = {}
_GENERAL_FEED_LAST_ATTEMPT_AT = {}
_GENERAL_FEED_CURSOR = {}
GENERAL_PAGES_PER_PASS = 2
_COLLECTION_MEMBERSHIP_CACHE = {}


class ShopifyHTTPError(RuntimeError):
    def __init__(self, status, message, *, url=None, purpose=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.purpose = purpose


class ShopifyRateLimitError(ShopifyHTTPError):
    pass


def _append_discovery_source(product, source):
    if not isinstance(product, dict):
        return
    sources = product.get("_lotus_discovery_sources")
    if not isinstance(sources, list):
        sources = []
    if source not in sources:
        sources.append(source)
    product["_lotus_discovery_sources"] = sources


def _append_new_collection_membership(product, handle):
    if not isinstance(product, dict):
        return
    memberships = product.get("_lotus_new_collection_memberships")
    if not isinstance(memberships, list):
        memberships = []
    handle = str(handle or "").strip()
    if handle and handle not in memberships:
        memberships.append(handle)
    product["_lotus_new_collection_memberships"] = memberships


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


def _xml_locations(xml_text):
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    locations = []
    for element in root.iter():
        if str(element.tag).lower().endswith("loc") and element.text:
            value = str(element.text).strip()
            if value:
                locations.append(value)
    return locations


def _collection_handle_from_url(url):
    try:
        path = urlparse(str(url or "")).path
    except Exception:
        return None
    marker = "/collections/"
    if marker not in path:
        return None
    handle = path.split(marker, 1)[1].strip("/").split("/", 1)[0]
    return handle or None


def _collection_score(handle, title=""):
    probe = normalize_text(f"{title or ''} {handle or ''}")
    if not probe:
        return 0

    score = 0
    if "preorder" in probe or "pre-order" in probe or "pre order" in probe:
        score += 120
    if "coming soon" in probe or "coming-soon" in probe:
        score += 100
    if "new arrivals" in probe or "new-arrivals" in probe:
        score += 45
    if "new products" in probe or "new-products" in probe:
        score += 40

    game_terms = (
        "one piece", "one-piece", "onepiece",
        "pokemon", "pokémon", "gundam",
        "dragon ball", "fusion world", "fusion-world",
        "riftbound", "palworld", "naruto", "cyberpunk",
        "azuki", "hellbreak",
    )
    for term in game_terms:
        if term in probe:
            score += 35

    if "tcg" in probe or "trading card" in probe or "card game" in probe:
        score += 15

    return score


def _retry_after_seconds(value, attempt):
    try:
        if value is not None:
            parsed = float(str(value).strip())
            if parsed >= 0:
                return min(max(parsed, 1.0), SHOPIFY_MAX_BACKOFF_SECONDS)
    except (TypeError, ValueError):
        pass
    # Respectful exponential fallback when Retry-After is absent/non-numeric.
    return min(2.0 ** (attempt + 1), SHOPIFY_MAX_BACKOFF_SECONDS)


class ShopifyAdapter:

    def __init__(
        self,
        domain,
        region="US",
    ):
        self.domain = normalize_shopify_domain(domain)
        self.region = (region or "US").upper()
        self.base_url = f"https://{self.domain}"
        self.currency = REGION_CURRENCY.get(self.region, "USD")
        self.diagnostics = {
            "requests_attempted": 0,
            "http_200": 0,
            "http_429": 0,
            "http_5xx": 0,
            "http_other": 0,
            "retries": 0,
            "backoff_seconds": 0.0,
            "rate_limit_exhausted": 0,
            "priority_collection_cache_hit": 0,
            "collection_sitemaps_checked": 0,
            "collection_index_pages": 0,
            "collections_seen": 0,
            "priority_collections": 0,
            "priority_collection_handles": [],
            "collection_pages_successful": 0,
            "collection_products_seen": 0,
            "new_collection_memberships": 0,
            "general_pages_successful": 0,
            "general_products_seen": 0,
            "general_feed_skipped": 0,
            "partial_due_to_rate_limit": 0,
        }

    def get_diagnostics(self):
        return dict(self.diagnostics)

    def _domain_lock(self):
        lock = _DOMAIN_REQUEST_LOCKS.get(self.domain)
        if lock is None:
            lock = asyncio.Lock()
            _DOMAIN_REQUEST_LOCKS[self.domain] = lock
        return lock

    async def _request(self, session, url, *, purpose, expect_json, required):
        lock = self._domain_lock()

        async with lock:
            retry_429 = 0
            retry_5xx = 0

            while True:
                last_request_at = _DOMAIN_LAST_REQUEST_AT.get(self.domain, 0.0)
                elapsed = time.monotonic() - last_request_at
                if elapsed < SHOPIFY_REQUEST_DELAY_SECONDS:
                    await asyncio.sleep(SHOPIFY_REQUEST_DELAY_SECONDS - elapsed)

                self.diagnostics["requests_attempted"] += 1

                try:
                    async with session.get(url, allow_redirects=True) as response:
                        status = int(response.status)
                        body = await response.text()
                        _DOMAIN_LAST_REQUEST_AT[self.domain] = time.monotonic()

                        if status == 200:
                            self.diagnostics["http_200"] += 1
                            if not expect_json:
                                return body
                            try:
                                return json.loads(body)
                            except Exception as error:
                                if required:
                                    raise ShopifyHTTPError(
                                        200,
                                        f"Shopify returned invalid JSON for {purpose}: {type(error).__name__}",
                                        url=url,
                                        purpose=purpose,
                                    )
                                return None

                        if status == 429:
                            self.diagnostics["http_429"] += 1
                            if retry_429 < SHOPIFY_MAX_429_RETRIES:
                                wait_seconds = _retry_after_seconds(
                                    response.headers.get("Retry-After"),
                                    retry_429,
                                )
                                retry_429 += 1
                                self.diagnostics["retries"] += 1
                                self.diagnostics["backoff_seconds"] += wait_seconds
                                print(
                                    "SHOPIFY RATE LIMIT BACKOFF | "
                                    f"Store={self.domain} | Purpose={purpose} | "
                                    f"Retry={retry_429}/{SHOPIFY_MAX_429_RETRIES} | "
                                    f"Wait={wait_seconds:.1f}s"
                                )
                                await asyncio.sleep(wait_seconds)
                                continue

                            self.diagnostics["rate_limit_exhausted"] += 1
                            self.diagnostics["partial_due_to_rate_limit"] = 1
                            message = (
                                f"Shopify HTTP 429 after {SHOPIFY_MAX_429_RETRIES} retries "
                                f"for {purpose}"
                            )
                            if required:
                                raise ShopifyRateLimitError(
                                    429,
                                    message,
                                    url=url,
                                    purpose=purpose,
                                )
                            print(
                                "SHOPIFY OPTIONAL REQUEST RATE LIMITED | "
                                f"Store={self.domain} | Purpose={purpose}"
                            )
                            return None

                        if 500 <= status <= 599:
                            self.diagnostics["http_5xx"] += 1
                            if retry_5xx < SHOPIFY_MAX_5XX_RETRIES:
                                wait_seconds = min(
                                    2.0 ** (retry_5xx + 1),
                                    SHOPIFY_MAX_BACKOFF_SECONDS,
                                )
                                retry_5xx += 1
                                self.diagnostics["retries"] += 1
                                self.diagnostics["backoff_seconds"] += wait_seconds
                                await asyncio.sleep(wait_seconds)
                                continue

                        self.diagnostics["http_other"] += 1
                        if required:
                            raise ShopifyHTTPError(
                                status,
                                f"Shopify HTTP {status} for {purpose}",
                                url=url,
                                purpose=purpose,
                            )
                        return None

                except asyncio.CancelledError:
                    raise
                except (ShopifyHTTPError, ShopifyRateLimitError):
                    raise
                except Exception as error:
                    if required:
                        raise ShopifyHTTPError(
                            None,
                            f"Shopify request failed for {purpose}: {type(error).__name__}: {error}",
                            url=url,
                            purpose=purpose,
                        )
                    return None

    async def _get_json(self, session, url, *, purpose, required=False):
        return await self._request(
            session,
            url,
            purpose=purpose,
            expect_json=True,
            required=required,
        )

    async def _get_text(self, session, url, *, purpose, required=False):
        return await self._request(
            session,
            url,
            purpose=purpose,
            expect_json=False,
            required=required,
        )

    async def fetch_store_currency(self):
        cached = _STORE_CURRENCY_CACHE.get(self.domain)
        if cached and time.monotonic() - cached[0] < STORE_CURRENCY_CACHE_SECONDS:
            self.currency = cached[1]
            return self.currency
        url = f"{self.base_url}/cart.js"
        timeout = aiohttp.ClientTimeout(total=20)
        headers = {
            "Accept": "application/json",
            "User-Agent": "PonDeX-Trackers/1.0.6-C1",
        }

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                data = await self._get_json(
                    session,
                    url,
                    purpose="STORE_CURRENCY",
                    required=False,
                )
                if isinstance(data, dict):
                    currency = data.get("currency")
                    if currency:
                        self.currency = str(currency).strip().upper()
                        _STORE_CURRENCY_CACHE[self.domain] = (time.monotonic(), self.currency)
        except Exception as error:
            print(
                "SHOPIFY CURRENCY DETECTION ERROR | "
                f"{self.domain} | {type(error).__name__}: {error}"
            )

        return self.currency

    async def probe_storefront(self):
        """One lightweight public request used by store-health recovery."""
        timeout = aiohttp.ClientTimeout(total=20)
        headers = {
            "Accept": "application/json",
            "User-Agent": "PonDeX-Trackers/1.0.6-C1",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            data = await self._get_json(
                session,
                f"{self.base_url}/products.json?limit=1&page=1",
                purpose="HEALTH_PROBE",
                required=True,
            )
            if not isinstance(data, dict):
                raise ShopifyHTTPError(
                    200,
                    "Shopify health probe returned an unexpected payload",
                    purpose="HEALTH_PROBE",
                )
        return True

    async def _discover_priority_collections(self, session):
        now = time.monotonic()
        cached = _PRIORITY_COLLECTION_CACHE.get(self.domain)
        if cached and now - cached[0] < SHOPIFY_COLLECTION_CACHE_SECONDS:
            self.diagnostics["priority_collection_cache_hit"] = 1
            collections = list(cached[1])
            self.diagnostics["priority_collections"] = len(collections)
            self.diagnostics["priority_collection_handles"] = [c[1] for c in collections]
            return collections

        candidates = {}

        def add_candidate(handle, title=""):
            handle = str(handle or "").strip()
            if not handle:
                return
            score = _collection_score(handle, title)
            if score <= 0:
                return
            previous = candidates.get(handle)
            row = (-score, handle, normalize_text(title) or handle)
            if previous is None or row < previous:
                candidates[handle] = row

        # Preferred path: Shopify's public sitemap points directly to the
        # collection sitemap(s), which is far cheaper than walking a giant
        # /collections.json catalog page-by-page.
        root_xml = await self._get_text(
            session,
            f"{self.base_url}/sitemap.xml",
            purpose="SITEMAP_ROOT",
            required=False,
        )
        collection_sitemaps = []
        for location in _xml_locations(root_xml):
            if "sitemap_collections" in location.lower():
                collection_sitemaps.append(location)

        for sitemap_url in collection_sitemaps[:MAX_COLLECTION_SITEMAPS]:
            xml_text = await self._get_text(
                session,
                sitemap_url,
                purpose="SITEMAP_COLLECTIONS",
                required=False,
            )
            if not xml_text:
                continue
            self.diagnostics["collection_sitemaps_checked"] += 1
            for location in _xml_locations(xml_text):
                handle = _collection_handle_from_url(location)
                if handle:
                    self.diagnostics["collections_seen"] += 1
                    add_candidate(handle, handle.replace("-", " "))

        # Fallback for stores whose sitemap doesn't expose collection URLs.
        if not candidates:
            for page in range(1, MAX_COLLECTION_JSON_PAGES + 1):
                data = await self._get_json(
                    session,
                    f"{self.base_url}/collections.json?limit=250&page={page}",
                    purpose=f"COLLECTION_INDEX_PAGE_{page}",
                    required=False,
                )
                if not isinstance(data, dict):
                    break
                collections = data.get("collections", []) or []
                self.diagnostics["collection_index_pages"] += 1
                self.diagnostics["collections_seen"] += len(collections)
                if not collections:
                    break
                for collection in collections:
                    if not isinstance(collection, dict):
                        continue
                    add_candidate(
                        collection.get("handle"),
                        collection.get("title"),
                    )
                if len(collections) < 250:
                    break

        ranked = sorted(candidates.values())[:MAX_PRIORITY_COLLECTIONS]
        # Never cache an empty discovery result. An empty result may simply
        # mean a transient 429/5xx response; caching it would blind the fast
        # lane for the full cache window.
        if ranked:
            _PRIORITY_COLLECTION_CACHE[self.domain] = (now, list(ranked))
        self.diagnostics["priority_collections"] = len(ranked)
        self.diagnostics["priority_collection_handles"] = [row[1] for row in ranked]
        return ranked

    async def fetch_products(self, max_pages=20, *, on_batch=None):
        products_by_key = {}
        anonymous_products = []

        timeout = aiohttp.ClientTimeout(total=45)
        headers = {
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "PonDeX-Trackers/1.0.6-C1",
        }

        async def merge_products(page_products, source):
            for incoming in page_products or []:
                if not isinstance(incoming, dict):
                    continue
                product = dict(incoming)
                _append_discovery_source(product, source)
                key = _product_dedupe_key(product)

                if key is None:
                    anonymous_products.append(product)
                    continue

                existing = products_by_key.get(key)
                if existing is None:
                    products_by_key[key] = product
                    continue

                existing_sources = list(existing.get("_lotus_discovery_sources") or [])
                incoming_sources = list(product.get("_lotus_discovery_sources") or [])
                existing_memberships = list(existing.get("_lotus_new_collection_memberships") or [])
                incoming_memberships = list(product.get("_lotus_new_collection_memberships") or [])

                for value in incoming_sources:
                    if value not in existing_sources:
                        existing_sources.append(value)
                for value in incoming_memberships:
                    if value not in existing_memberships:
                        existing_memberships.append(value)

                existing.update(product)
                existing["_lotus_discovery_sources"] = existing_sources
                if existing_memberships:
                    existing["_lotus_new_collection_memberships"] = existing_memberships

        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
            connector=aiohttp.TCPConnector(limit=4, limit_per_host=2),
        ) as session:
            # =================================================
            # 1. FAST LANE — PRIORITY COLLECTIONS FIRST
            # =================================================
            priority_collections = await self._discover_priority_collections(session)

            for _, handle, title in priority_collections:
                source_label = "COLLECTION:" + handle
                membership_key = (self.domain, handle)
                previous_members = _COLLECTION_MEMBERSHIP_CACHE.get(membership_key)
                current_members = set()
                collection_complete = True
                successful_pages = 0

                for page in range(1, MAX_COLLECTION_PAGES + 1):
                    data = await self._get_json(
                        session,
                        (
                            f"{self.base_url}/collections/{handle}/products.json"
                            f"?limit=250&page={page}"
                        ),
                        purpose=f"PRIORITY_COLLECTION:{handle}:PAGE:{page}",
                        required=False,
                    )
                    if not isinstance(data, dict):
                        collection_complete = False
                        break

                    page_products = data.get("products", []) or []
                    successful_pages += 1
                    self.diagnostics["collection_pages_successful"] += 1
                    self.diagnostics["collection_products_seen"] += len(page_products)

                    if not page_products:
                        break

                    prepared = []
                    for raw_product in page_products:
                        if not isinstance(raw_product, dict):
                            continue
                        product = dict(raw_product)
                        key = _product_dedupe_key(product)
                        if key:
                            current_members.add(key)
                            if previous_members is not None and key not in previous_members:
                                _append_new_collection_membership(product, handle)
                                self.diagnostics["new_collection_memberships"] += 1
                        prepared.append(product)

                    await merge_products(prepared, source_label)

                    if len(page_products) < 250:
                        break
                    if page == MAX_COLLECTION_PAGES:
                        # We intentionally cap large collections. The first
                        # 500 entries remain useful, but do not pretend this
                        # was a complete membership snapshot.
                        collection_complete = False

                if successful_pages and collection_complete:
                    _COLLECTION_MEMBERSHIP_CACHE[membership_key] = current_members
                elif successful_pages and previous_members is None:
                    # Baseline the observed slice only; additions to that
                    # slice can still be detected on later scans.
                    _COLLECTION_MEMBERSHIP_CACHE[membership_key] = current_members

            # Finish merging collection memberships before publishing them.
            # Each product is processed once per pass, even across overlaps.
            delivered_keys = set()
            if on_batch is not None:
                priority_products = list(products_by_key.values()) + anonymous_products
                for offset in range(0, len(priority_products), 100):
                    await on_batch(priority_products[offset:offset + 100], "PRIORITY_COLLECTIONS")
                delivered_keys.update(products_by_key)

            # =================================================
            # 2. GENERAL PRODUCT FEED — THIRTY-SECOND REFRESH TARGET
            # =================================================
            now = time.monotonic()
            last_general = _GENERAL_FEED_LAST_ATTEMPT_AT.get(self.domain, 0.0)
            cursor = _GENERAL_FEED_CURSOR.get(self.domain, 1) if on_batch is not None else 1
            run_general = (
                (on_batch is not None and cursor > 1)
                or max_pages <= 1
                or not last_general
                or now - last_general >= SHOPIFY_GENERAL_REFRESH_SECONDS
            )

            general_pages = 0
            if run_general:
                # Set this before requesting so a rate-limited general scan is
                # not immediately retried by the next scheduled scan.
                if on_batch is None:
                    _GENERAL_FEED_LAST_ATTEMPT_AT[self.domain] = now
                pages = (range(cursor, cursor + GENERAL_PAGES_PER_PASS)
                         if on_batch is not None else range(1, max_pages + 1))
                for page in pages:
                    existing_product_count = len(products_by_key) + len(anonymous_products)
                    data = await self._get_json(
                        session,
                        f"{self.base_url}/products.json?limit=250&page={page}",
                        purpose=f"GENERAL_PRODUCTS_PAGE_{page}",
                        required=(existing_product_count == 0 and page == 1),
                    )
                    if not isinstance(data, dict):
                        break

                    page_products = data.get("products", []) or []
                    if not page_products:
                        if on_batch is not None:
                            _GENERAL_FEED_CURSOR[self.domain] = 1
                            _GENERAL_FEED_LAST_ATTEMPT_AT[self.domain] = time.monotonic()
                            self.diagnostics["general_sweep_complete"] = True
                        break

                    general_pages += 1
                    self.diagnostics["general_pages_successful"] += 1
                    self.diagnostics["general_products_seen"] += len(page_products)
                    general_source = ("PRODUCTS_JSON_BACKFILL" if on_batch is not None and page > max_pages else "PRODUCTS_JSON")
                    await merge_products(page_products, general_source)
                    if on_batch is not None:
                        fresh = []
                        for raw in page_products:
                            if not isinstance(raw, dict):
                                continue
                            key = _product_dedupe_key(raw)
                            if key is not None and key not in delivered_keys:
                                fresh.append(products_by_key[key])
                                delivered_keys.add(key)
                            elif key is None:
                                product = dict(raw)
                                _append_discovery_source(product, general_source)
                                fresh.append(product)
                        for offset in range(0, len(fresh), 100):
                            await on_batch(fresh[offset:offset + 100], f"GENERAL_PAGE_{page}")
                        # Advance only after every callback for this page succeeds.
                        _GENERAL_FEED_CURSOR[self.domain] = page + 1
                    if len(page_products) < 250:
                        if on_batch is not None:
                            _GENERAL_FEED_CURSOR[self.domain] = 1
                            _GENERAL_FEED_LAST_ATTEMPT_AT[self.domain] = time.monotonic()
                            self.diagnostics["general_sweep_complete"] = True
                        break
            else:
                self.diagnostics["general_feed_skipped"] = 1

        if on_batch is not None:
            self.diagnostics["general_next_page"] = _GENERAL_FEED_CURSOR.get(self.domain, 1)
            print(f"SHOPIFY CATALOG PROGRESS | Store={self.domain} | "
                  f"NextPage={self.diagnostics['general_next_page']} | "
                  f"SweepComplete={bool(self.diagnostics.get('general_sweep_complete'))}")
        products = list(products_by_key.values()) + anonymous_products

        if not products and self.diagnostics["rate_limit_exhausted"]:
            raise ShopifyRateLimitError(
                429,
                "Shopify rate limit prevented a usable product scan",
                purpose="FETCH_PRODUCTS",
            )

        print(
            "SHOPIFY DISCOVERY COMPLETE | "
            f"Store={self.domain} | "
            f"PriorityCollections={self.diagnostics['priority_collections']} | "
            f"CollectionProductsSeen={self.diagnostics['collection_products_seen']} | "
            f"GeneralPages={general_pages} | "
            f"GeneralProductsSeen={self.diagnostics['general_products_seen']} | "
            f"GeneralSkipped={self.diagnostics['general_feed_skipped']} | "
            f"HTTP429={self.diagnostics['http_429']} | "
            f"Retries={self.diagnostics['retries']} | "
            f"BackoffSeconds={self.diagnostics['backoff_seconds']:.1f} | "
            f"Partial={self.diagnostics['partial_due_to_rate_limit']} | "
            f"UniqueProducts={len(products)}"
        )

        return products


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

        discovery_sources = list(
            product.get(
                "_lotus_discovery_sources",
                ["PRODUCTS_JSON"],
            )
            or ["PRODUCTS_JSON"]
        )

        discovery_probe = normalize_text(
            " ".join(str(value or "") for value in discovery_sources)
        )

        # A collection explicitly labeled non-pre-order is not preorder
        # evidence. Keep other positive sources and product-title signals.
        discovery_probe = re.sub(
            r"\b(?:non|not|no)[\s_-]+pre[\s_-]*orders?\b",
            " ",
            discovery_probe,
            flags=re.IGNORECASE,
        )

        preorder_signal = (
            "preorder" in lower_title
            or "pre-order" in lower_title
            or "pre order" in lower_title
            or "preorder" in discovery_probe
            or "pre-order" in discovery_probe
            or "pre order" in discovery_probe
        )

        coming_soon_signal = (
            "coming soon" in lower_title
            or "coming-soon" in lower_title
            or "coming soon" in discovery_probe
            or "coming-soon" in discovery_probe
        )

        if preorder_signal:

            product_state = (
                "PREORDER_LIVE"
                if available
                else "PREORDER_PAGE"
            )

        elif coming_soon_signal and not available:

            product_state = (
                "COMING_SOON"
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
                    f"DiscoverySources={discovery_sources}"
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

            # Public Shopify catalog timestamps are used only as a
            # freshness guard for collection-only discovery. They do not
            # affect game/category/family classification.
            "published_at":
                product.get("published_at"),

            "created_at":
                product.get("created_at"),

            "updated_at":
                product.get("updated_at"),

            "discovery_sources":
                discovery_sources,

            "new_collection_memberships":
                list(
                    product.get(
                        "_lotus_new_collection_memberships",
                        [],
                    )
                    or []
                ),
        }
