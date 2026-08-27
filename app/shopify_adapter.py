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
# Version 1.0.3
#
# Strict TCG Classification
# Product Family Detection
# Product Category Detection
# Native Currency
# Product Images
# Smart Cart Metadata
# Dynamic Purchasable Variant Selection
# Variant-Type Matching
# Purchase Limit Detection
# =========================================================


# =========================================================
# REGION CURRENCY FALLBACK
# =========================================================

REGION_CURRENCY = {

    "US":
        "USD",

    "CA":
        "CAD",

    "UK":
        "GBP",

    "GB":
        "GBP",

    "EU":
        "EUR",

    "DE":
        "EUR",

    "FR":
        "EUR",

    "IT":
        "EUR",

    "ES":
        "EUR",

    "NL":
        "EUR",

    "BE":
        "EUR",

    "AT":
        "EUR",

    "IE":
        "EUR",

    "PT":
        "EUR",

    "JP":
        "JPY",

    "KR":
        "KRW",

    "CN":
        "CNY",

    "AU":
        "AUD",

    "NZ":
        "NZD",
}


# =========================================================
# DOMAIN
# =========================================================

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


# =========================================================
# TEXT NORMALIZATION
# =========================================================

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
        "é",
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


def build_product_text(
    product,
):

    fields = (

        "title",
        "vendor",
        "product_type",
        "tags",
        "handle",
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
            list,
        ):

            parts.extend(
                str(item)
                for item
                in value
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
# STRICT TCG CLASSIFICATION
# =========================================================

SEALED_CONTEXT_PATTERN = re.compile(
    r"\b("
    r"booster\s*box|"
    r"booster\s*bundle|"
    r"booster\s*pack|"
    r"display|"
    r"starter\s*deck|"
    r"structure\s*deck|"
    r"deck|"
    r"case|"
    r"collection|"
    r"gift\s*collection|"
    r"double\s*pack|"
    r"premium\s*collection|"
    r"elite\s*trainer\s*box|"
    r"etb|"
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


def classify_game(
    product,
):

    text = (
        build_product_text(
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
    ):

        return (
            "One Piece"
        )

    # =====================================================
    # POKEMON
    # =====================================================

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

        "pokémon tcg"
        in text

        or

        "pokémon trading card"
        in text

        or

        (
            (
                "pokemon"
                in text

                or

                "pokémon"
                in text
            )

            and

            SEALED_CONTEXT_PATTERN.search(
                text
            )
        )
    ):

        return (
            "Pokemon"
        )

    # =====================================================
    # GUNDAM
    # =====================================================

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

    # =====================================================
    # DRAGON BALL FUSION WORLD
    # =====================================================

    if (
        "dragon ball super card game fusion world"
        in text

        or

        "dragon ball fusion world"
        in text

        or

        "fusion world"
        in text
    ):

        return (
            "Dragon Ball Fusion World"
        )

    # =====================================================
    # RIFTBOUND
    # =====================================================

    if (
        "riftbound"
        in text
    ):

        return (
            "Riftbound"
        )

    # =====================================================
    # PALWORLD
    # =====================================================

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

    # =====================================================
    # NARUTO
    # =====================================================

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

    # =====================================================
    # CYBERPUNK
    # =====================================================

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

    # =====================================================
    # AZUKI
    # =====================================================

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

    # =====================================================
    # HELLBREAK
    # =====================================================

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


# =========================================================
# PRODUCT TYPE
# =========================================================

def infer_product_type(
    title,
    raw_type=None,
):

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

        (
            (
                "deck",
            ),
            "Deck",
        ),
    ]

    for (
        keywords,
        label,
    ) in mappings:

        for keyword in keywords:

            if (
                keyword
                in text
            ):

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


# =========================================================
# PRODUCT CATEGORY
#
# SEALED
# SINGLE
# ACCESSORY
# UNKNOWN
# =========================================================

SEALED_KEYWORDS = (

    "booster box",
    "booster display",
    "booster bundle",
    "booster pack",
    "sleeved booster",
    "elite trainer box",
    "starter deck",
    "structure deck",
    "double pack",
    "collection box",
    "premium collection",
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
)


def infer_product_category(
    title,
    raw_type=None,
    tags=None,
):

    combined = (
        normalize_text(
            " ".join(
                [
                    str(
                        title
                        or ""
                    ),
                    str(
                        raw_type
                        or ""
                    ),
                    str(
                        tags
                        or ""
                    ),
                ]
            )
        )
    )

    # -----------------------------------------------------
    # Sealed wins first.
    # -----------------------------------------------------

    if any(
        keyword in combined
        for keyword
        in SEALED_KEYWORDS
    ):

        return (
            "SEALED"
        )

    # -----------------------------------------------------
    # Accessories.
    # -----------------------------------------------------

    if any(
        keyword in combined
        for keyword
        in ACCESSORY_KEYWORDS
    ):

        return (
            "ACCESSORY"
        )

    # -----------------------------------------------------
    # Explicit singles.
    # -----------------------------------------------------

    if any(
        keyword in combined
        for keyword
        in SINGLE_STRONG_KEYWORDS
    ):

        return (
            "SINGLE"
        )

    if (
        raw_type

        and

        any(
            phrase
            in normalize_text(
                raw_type
            )
            for phrase
            in (
                "single",
                "singles",
                "individual card",
            )
        )
    ):

        return (
            "SINGLE"
        )

    return (
        "UNKNOWN"
    )


# =========================================================
# IMAGE
# =========================================================

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


# =========================================================
# PURCHASE LIMIT
# =========================================================

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
        build_product_text(
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

        if (
            value >= 1
            and
            value <= 100
        ):

            return (
                value
            )

    return None


# =========================================================
# VARIANT ID
# =========================================================

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
# VARIANT TITLE
# =========================================================

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

    if not title:

        return None

    return (
        title
    )


# =========================================================
# VARIANT PRICE
# =========================================================

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


# =========================================================
# VALID CART VARIANT
#
# A Shopify cart permalink requires a usable numeric
# variant ID.
# =========================================================

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


# =========================================================
# PRODUCT TYPE -> VARIANT TITLE KEYWORDS
#
# This prevents a listing such as:
#
# Variant A: Booster Pack
# Variant B: Booster Box
# Variant C: Case
#
# from choosing the cheapest pack when the actual product
# title is clearly a Booster Box listing.
# =========================================================

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


# =========================================================
# VARIANT TYPE SCORE
# =========================================================

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

    # Shopify's standard single-variant title does not
    # provide meaningful type information.

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


# =========================================================
# CHOOSE PRIMARY VARIANT
#
# Priority:
#
# 1. Valid numeric variant ID
# 2. Available
# 3. Variant title matches product type
# 4. Lowest price
# 5. Stable original order
#
# If nothing is available, Lotus still keeps the best valid
# variant as metadata, but product availability remains
# False and Smart Cart will not be shown.
# =========================================================

def choose_primary_variant(
    variants,
    product_type=None,
):

    if not variants:

        return None

    valid_variants = [

        variant

        for variant
        in variants

        if is_valid_cart_variant(
            variant
        )
    ]

    if not valid_variants:

        return None

    available_variants = [

        variant

        for variant
        in valid_variants

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

        # Missing price should lose to any real price.

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


# =========================================================
# TRUSTED DEFAULT PRODUCT FAMILY
# =========================================================

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

    # -----------------------------------------------------
    # Standard international / English configuration.
    #
    # Foreign/import evidence in the actual product always
    # overrides this fallback.
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # A store being physically based in Japan/Korea/China
    # is not sufficient by itself to classify every item.
    # -----------------------------------------------------

    return None


# =========================================================
# SHOPIFY ADAPTER
# =========================================================

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


    # =====================================================
    # FETCH STORE CURRENCY
    # =====================================================

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
                            "PonDeX-Trackers/1.0.3",
                    },

                ) as response:

                    if (
                        response.status
                        == 200
                    ):

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


    # =====================================================
    # FETCH PRODUCTS
    # =====================================================

    async def fetch_products(
        self,
        max_pages=20,
    ):

        products = []

        timeout = (
            aiohttp.ClientTimeout(
                total=30
            )
        )

        headers = {

            "Accept":
                "application/json",

            "User-Agent":
                "PonDeX-Trackers/1.0.3",
        }

        async with aiohttp.ClientSession(

            timeout=timeout,

            headers=headers,

        ) as session:

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

                    if (
                        response.status
                        != 200
                    ):

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

                    products.extend(
                        page_products
                    )

                    if (
                        len(
                            page_products
                        )
                        < 250
                    ):

                        break

        return (
            products
        )


    # =====================================================
    # NORMALIZE PRODUCT
    # =====================================================

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


        # =================================================
        # PRODUCT TYPE
        #
        # We determine this before choosing the primary
        # variant so variant-title matching can use it.
        # =================================================

        product_type = (
            infer_product_type(

                title,

                raw_type,
            )
        )


        # =================================================
        # PRODUCT AVAILABILITY
        #
        # Product is in stock when ANY valid Shopify variant
        # is available.
        # =================================================

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

            for variant
            in variants
        )


        # =================================================
        # DYNAMIC PRIMARY VARIANT
        # =================================================

        primary_variant = (
            choose_primary_variant(

                variants,

                product_type=(
                    product_type
                ),
            )
        )


        variant_id = None

        selected_variant_title = None

        selected_variant_available = False

        selected_variant_price = None

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

            selected_variant_available = bool(
                primary_variant.get(
                    "available"
                )
            )

            selected_variant_price = (
                variant_price(
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


        # =================================================
        # DISPLAY / EVENT PRICE
        #
        # If an available cart variant exists, price follows
        # that selected purchasable variant.
        #
        # This prevents:
        #
        # Sold-out Variant A = $99
        # Available Variant B = $119
        #
        # from falsely alerting users at $99.
        # =================================================

        if (
            selected_variant_available

            and

            selected_variant_price
            is not None
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


        # =================================================
        # PRODUCT URL
        # =================================================

        url = (

            (
                f"{self.base_url}"
                f"/products/{handle}"
            )

            if handle

            else self.base_url
        )


        # =================================================
        # PRODUCT CATEGORY
        # =================================================

        product_category = (
            infer_product_category(

                title,

                raw_type,

                tags,
            )
        )


        # =================================================
        # PRODUCT FAMILY
        #
        # Product identity determines family.
        #
        # Currency does NOT determine family.
        # =================================================

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


        # =================================================
        # PURCHASE LIMIT
        # =================================================

        purchase_limit = (
            infer_purchase_limit(
                product
            )
        )


        # =================================================
        # PRODUCT STATE
        # =================================================

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


        # =================================================
        # DEBUG
        # =================================================

        if game:

            print(
                (
                    "SHOPIFY VARIANT SELECTED | "
                    f"Store={self.domain} | "
                    f"Product={title} | "
                    f"Type={product_type} | "
                    f"Variant={variant_id} | "
                    f"VariantTitle={selected_variant_title} | "
                    f"Available={selected_variant_available} | "
                    f"Price={selected_variant_price} | "
                    f"ProductAvailable={available}"
                )
            )


        # =================================================
        # NORMALIZED PRODUCT
        # =================================================

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

            # =============================================
            # SMART CART
            # =============================================

            "variant_id":
                variant_id,

            "variant_title":
                selected_variant_title,

            "variant_available":
                selected_variant_available,

            "variant_price":
                selected_variant_price,

            "purchase_limit":
                purchase_limit,

            "cart_base_url":
                self.base_url,
        }