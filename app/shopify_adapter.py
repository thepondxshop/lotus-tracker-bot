import re

from urllib.parse import (
    urlparse,
)

import aiohttp


# =========================================================
# LOTUS SHOPIFY ADAPTER
# PonDeX Trackers
# Version 0.7.8-hotfix
#
# Safer TCG classification
# Sealed / Single / Accessory classification
# Native currency
# Shopify variant IDs
# Purchase limits
# Images
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
    "JP": "JPY",
    "AU": "AUD",
    "NZ": "NZD",
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
            hostname[4:]
        )

    if not hostname:

        raise ValueError(
            "Invalid Shopify domain."
        )

    return hostname


# =========================================================
# SAFE GAME CLASSIFICATION TEXT
#
# IMPORTANT:
#
# Do NOT include body_html here.
#
# Store descriptions frequently contain unrelated products,
# recommendation widgets or cross-sell terminology.
# =========================================================

def game_classification_text(
    product,
):

    tags = (
        product.get(
            "tags",
            ""
        )
    )

    if isinstance(
        tags,
        list,
    ):

        tags = " ".join(
            str(tag)
            for tag in tags
        )

    return " ".join(
        [
            str(
                product.get(
                    "title",
                    ""
                )
            ),

            str(
                product.get(
                    "vendor",
                    ""
                )
            ),

            str(
                product.get(
                    "product_type",
                    ""
                )
            ),

            str(
                tags
            ),
        ]
    ).lower()


# =========================================================
# GENERAL PRODUCT TEXT
#
# This MAY include description because it is useful for
# things such as purchase-limit detection.
# =========================================================

def full_product_text(
    product,
):

    tags = (
        product.get(
            "tags",
            ""
        )
    )

    if isinstance(
        tags,
        list,
    ):

        tags = " ".join(
            str(tag)
            for tag in tags
        )

    return " ".join(
        [
            str(
                product.get(
                    "title",
                    ""
                )
            ),

            str(
                product.get(
                    "vendor",
                    ""
                )
            ),

            str(
                product.get(
                    "product_type",
                    ""
                )
            ),

            str(
                tags
            ),

            str(
                product.get(
                    "body_html",
                    ""
                )
            ),
        ]
    )


# =========================================================
# GAME CLASSIFICATION
# =========================================================

def classify_game(
    product,
):

    text = (
        game_classification_text(
            product
        )
    )

    # =====================================================
    # POKEMON
    # =====================================================

    pokemon_terms = [

        "pokemon tcg",
        "pokémon tcg",
        "pokemon trading card",
        "pokémon trading card",
        "pokemon card game",
        "pokémon card game",
        "elite trainer box",
        "pokemon booster",
        "pokémon booster",
    ]

    if any(
        term in text
        for term in pokemon_terms
    ):

        return (
            "Pokemon"
        )


    # =====================================================
    # ONE PIECE
    # =====================================================

    one_piece_terms = [

        "one piece card game",
        "one piece tcg",
        "one piece trading card",
        "one piece booster",
        "one piece starter deck",
    ]

    if any(
        term in text
        for term in one_piece_terms
    ):

        return (
            "One Piece"
        )

    # Strong Bandai One Piece set-code patterns.
    #
    # OP01
    # OP-13
    # EB02
    # EB-03
    # ST21
    # ST-28
    #
    # Require the code as an isolated token.

    one_piece_code_patterns = [

        r"(?<![a-z0-9])op-?\d{2}(?![a-z0-9])",

        r"(?<![a-z0-9])eb-?\d{2}(?![a-z0-9])",

        r"(?<![a-z0-9])st-?\d{2}(?![a-z0-9])",
    ]

    # A set code by itself can still occur elsewhere.
    # Require Bandai / One Piece style context as well.

    one_piece_context = any(
        term in text
        for term in [
            "bandai",
            "one piece",
            "carddass",
        ]
    )

    if one_piece_context:

        for pattern in one_piece_code_patterns:

            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):

                return (
                    "One Piece"
                )


    # =====================================================
    # GUNDAM
    # =====================================================

    if any(
        term in text
        for term in [
            "gundam card game",
            "gundam tcg",
        ]
    ):

        return (
            "Gundam"
        )


    # =====================================================
    # DRAGON BALL FUSION WORLD
    # =====================================================

    if any(
        term in text
        for term in [
            "dragon ball super card game fusion world",
            "dragon ball fusion world",
            "fusion world tcg",
        ]
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

    if any(
        term in text
        for term in [
            "palworld tcg",
            "palworld card game",
            "palworld trading card",
        ]
    ):

        return (
            "Palworld"
        )


    # =====================================================
    # NARUTO
    # =====================================================

    if any(
        term in text
        for term in [
            "naruto tcg",
            "naruto card game",
            "naruto trading card",
        ]
    ):

        return (
            "Naruto"
        )


    # =====================================================
    # CYBERPUNK
    # =====================================================

    if any(
        term in text
        for term in [
            "cyberpunk tcg",
            "cyberpunk trading card",
            "cyberpunk card game",
        ]
    ):

        return (
            "Cyberpunk TCG"
        )


    # =====================================================
    # AZUKI
    # =====================================================

    if any(
        term in text
        for term in [
            "azuki tcg",
            "azuki card game",
            "azuki trading card",
        ]
    ):

        return (
            "Azuki TCG"
        )


    # =====================================================
    # HELLBREAK
    # =====================================================

    if any(
        term in text
        for term in [
            "hellbreak tcg",
            "hellbreak card game",
            "hellbreak trading card",
        ]
    ):

        return (
            "Hellbreak TCG"
        )


    # =====================================================
    # NO MATCH
    #
    # This is intentional.
    #
    # 40K, Magic, random sleeves, board games, etc.
    # should not be forced into a configured TCG.
    # =====================================================

    return None


# =========================================================
# PRODUCT CATEGORY
# =========================================================

SEALED_KEYWORDS = [

    "booster box",
    "booster pack",
    "booster bundle",
    "elite trainer box",
    "starter deck",
    "structure deck",
    "starter set",
    "collection box",
    "premium collection",
    "special collection",
    "collector chest",
    "mini tin",
    "display box",
    "booster display",
    "sealed case",
    "case of",
    "blister",
]

ACCESSORY_KEYWORDS = [

    "playmat",
    "play mat",
    "card sleeve",
    "card sleeves",
    "sleeves",
    "binder",
    "deck box",
    "storage box",
    "card holder",
    "dice",
    "damage counter",
    "damage counters",
    "portfolio",
    "accessory",
    "accessories",
]

SINGLE_KEYWORDS = [

    "single card",
    "single",
    "parallel",
    "alt art",
    "alternate art",
    "secret rare",
    "special rare",
    "super rare",
    "promo card",
    "foil card",
    "holo card",
    "reverse holo",
    "individual card",
]


def classify_product_category(
    product,
):

    # Category can use more metadata than game detection.

    title = str(
        product.get(
            "title",
            ""
        )
    )

    raw_type = str(
        product.get(
            "product_type",
            ""
        )
    ).lower()

    tags = (
        product.get(
            "tags",
            ""
        )
    )

    if isinstance(
        tags,
        list,
    ):

        tags = " ".join(
            str(tag)
            for tag in tags
        )

    tags = str(
        tags
    ).lower()

    combined = " ".join(
        [
            title,
            raw_type,
            tags,
        ]
    ).lower()


    # Strong merchant metadata.

    if (
        "single"
        in raw_type
        or
        "singles"
        in raw_type
        or
        "single"
        in tags
        or
        "singles"
        in tags
    ):

        return (
            "SINGLE"
        )


    if (
        "accessory"
        in raw_type
        or
        "accessories"
        in raw_type
    ):

        return (
            "ACCESSORY"
        )


    for keyword in ACCESSORY_KEYWORDS:

        if keyword in combined:

            return (
                "ACCESSORY"
            )


    for keyword in SEALED_KEYWORDS:

        if keyword in combined:

            return (
                "SEALED"
            )


    for keyword in SINGLE_KEYWORDS:

        if keyword in combined:

            return (
                "SINGLE"
            )


    # =====================================================
    # CARD NUMBER DETECTION
    # =====================================================

    card_patterns = [

        # Pokémon:
        # 025/165
        r"\b\d{1,3}/\d{1,3}\b",

        # One Piece:
        # OP01-078
        # OP13-118
        r"\bOP\d{2}-\d{2,4}\b",

        # Promo:
        # P-115
        r"\bP-\d{2,4}\b",
    ]

    for pattern in card_patterns:

        if re.search(
            pattern,
            title,
            flags=re.IGNORECASE,
        ):

            return (
                "SINGLE"
            )


    return (
        "UNKNOWN"
    )


# =========================================================
# DISPLAY TYPE
# =========================================================

def infer_product_type(
    title,
    raw_type,
):

    lower = (
        title.lower()
    )

    mappings = [

        (
            "elite trainer box",
            "Elite Trainer Box",
        ),

        (
            "booster box",
            "Booster Box",
        ),

        (
            "booster bundle",
            "Booster Bundle",
        ),

        (
            "booster pack",
            "Booster Pack",
        ),

        (
            "starter deck",
            "Starter Deck",
        ),

        (
            "structure deck",
            "Structure Deck",
        ),

        (
            "collection",
            "Collection",
        ),

        (
            "tin",
            "Tin",
        ),

        (
            "case",
            "Case",
        ),
    ]

    for (
        keyword,
        label,
    ) in mappings:

        if keyword in lower:

            return label

    return (
        raw_type
        or "TCG Product"
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

            return first


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

        return image


    return None


# =========================================================
# PURCHASE LIMIT
# =========================================================

def detect_purchase_limit(
    product,
):

    text = (
        full_product_text(
            product
        )
        .lower()
        .replace(
            "&nbsp;",
            " "
        )
    )

    patterns = [

        r"limit\s*(?:of)?\s*(\d{1,2})\s*(?:per|/)\s*(?:customer|person|order|household)",

        r"maximum\s*(?:of)?\s*(\d{1,2})\s*(?:per|/)\s*(?:customer|person|order|household)",

        r"max(?:imum)?\s*(?:qty|quantity)?\s*[:\-]?\s*(\d{1,2})",

        r"(\d{1,2})\s*(?:per|/)\s*(?:customer|person|order|household)",
    ]

    for pattern in patterns:

        match = (
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
        )

        if not match:

            continue

        try:

            limit = int(
                match.group(
                    1
                )
            )

        except Exception:

            continue

        if (
            1
            <= limit
            <= 50
        ):

            return limit


    return None


# =========================================================
# PRIMARY VARIANT
# =========================================================

def select_primary_variant(
    variants,
):

    if not variants:

        return None

    for variant in variants:

        if variant.get(
            "available"
        ):

            return variant

    return (
        variants[
            0
        ]
    )


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
    # CURRENCY
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
                            "PonDeX-Trackers/0.7.8",
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
                                ).upper()
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
    # PRODUCTS
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
                "PonDeX-Trackers/0.7.8",
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


        return products


    # =====================================================
    # NORMALIZE
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

        game = (
            classify_game(
                product
            )
        )

        category = (
            classify_product_category(
                product
            )
        )

        variants = (
            product.get(
                "variants"
            )
            or []
        )

        available = any(

            bool(
                variant.get(
                    "available"
                )
            )

            for variant in variants
        )

        primary_variant = (
            select_primary_variant(
                variants
            )
        )

        variant_id = None

        sku = None


        if primary_variant:

            if (
                primary_variant.get(
                    "id"
                )
                is not None
            ):

                variant_id = str(
                    primary_variant[
                        "id"
                    ]
                )

            sku = (
                primary_variant.get(
                    "sku"
                )
            )


        prices = []

        for variant in variants:

            raw_price = (
                variant.get(
                    "price"
                )
            )

            try:

                if (
                    raw_price
                    is not None
                ):

                    prices.append(
                        float(
                            raw_price
                        )
                    )

            except (
                TypeError,
                ValueError,
            ):

                continue


        price = (

            min(
                prices
            )

            if prices

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


        product_type = (
            infer_product_type(
                title,
                product.get(
                    "product_type"
                ),
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
                category,

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

            "handle":
                handle,

            "sku":
                sku,

            "variant_id":
                variant_id,

            "purchase_limit":
                detect_purchase_limit(
                    product
                ),

            "cart_base_url":
                self.base_url,
        }