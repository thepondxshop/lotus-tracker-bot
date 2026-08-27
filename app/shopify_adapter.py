import re

from urllib.parse import (
    urlparse,
)

import aiohttp


# =========================================================
# LOTUS SHOPIFY ADAPTER
# PonDeX Trackers
# Version 0.7.8
#
# Currency
# TCG Classification
# Sealed / Single / Accessory Classification
# Shopify Variant IDs
# Purchase-Limit Detection
# Product Images
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
# GAME CLASSIFICATION
# =========================================================

GAME_KEYWORDS = {

    "One Piece": [
        "one piece card game",
        "one piece tcg",
        "op-",
        "op01",
        "op02",
        "op03",
        "op04",
        "op05",
        "op06",
        "op07",
        "op08",
        "op09",
        "op10",
        "op11",
        "op12",
        "op13",
        "op14",
        "eb01",
        "eb02",
        "st-",
    ],

    "Pokemon": [
        "pokemon tcg",
        "pokémon tcg",
        "pokemon trading card",
        "pokémon trading card",
        "elite trainer box",
        "booster bundle",
        "pokemon booster",
        "pokémon booster",
    ],

    "Gundam": [
        "gundam card game",
        "gundam tcg",
    ],

    "Dragon Ball Fusion World": [
        "dragon ball super card game fusion world",
        "fusion world",
    ],

    "Riftbound": [
        "riftbound",
    ],

    "Palworld": [
        "palworld card",
        "palworld tcg",
    ],

    "Naruto": [
        "naruto card game",
        "naruto tcg",
    ],

    "Cyberpunk TCG": [
        "cyberpunk tcg",
        "cyberpunk trading card",
    ],

    "Azuki TCG": [
        "azuki tcg",
        "azuki card game",
    ],

    "Hellbreak TCG": [
        "hellbreak tcg",
        "hellbreak card",
    ],
}


def product_text(
    product,
):

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
                product.get(
                    "tags",
                    ""
                )
            ),

            str(
                product.get(
                    "body_html",
                    ""
                )
            ),
        ]
    )


def classify_game(
    product,
):

    combined = (
        product_text(
            product
        ).lower()
    )

    for (
        game,
        keywords,
    ) in GAME_KEYWORDS.items():

        for keyword in keywords:

            if (
                keyword.lower()
                in combined
            ):

                return game

    return None


# =========================================================
# SEALED / SINGLE / ACCESSORY CLASSIFICATION
# =========================================================

SEALED_KEYWORDS = [

    "booster box",
    "booster pack",
    "booster bundle",
    "elite trainer box",
    "etb",
    "starter deck",
    "structure deck",
    "starter set",
    "collection box",
    "premium collection",
    "special collection",
    "collector chest",
    "mini tin",
    "tin",
    "display box",
    "booster display",
    "sealed",
    "case of",
    "case ",
    "blister",
    "deck box set",
]

ACCESSORY_KEYWORDS = [

    "playmat",
    "play mat",
    "sleeves",
    "card sleeves",
    "binder",
    "deck box",
    "storage box",
    "card holder",
    "dice",
    "damage counters",
    "accessory",
    "accessories",
    "portfolio",
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

    combined = (
        product_text(
            product
        ).lower()
    )

    raw_type = str(
        product.get(
            "product_type",
            ""
        )
    ).lower()

    tags = str(
        product.get(
            "tags",
            ""
        )
    ).lower()

    # Strong Shopify merchant labels first.

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

    # Accessories before sealed because a deck box could
    # otherwise match "box".

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

    # Card-number patterns are useful for many singles:
    #
    # 025/165
    # OP01-078
    # P-115
    #
    # But don't apply them if obvious sealed terminology
    # exists.

    title = str(
        product.get(
            "title",
            ""
        )
    )

    card_patterns = [

        r"\b\d{1,3}/\d{1,3}\b",

        r"\b[A-Z]{1,4}\d{0,2}-\d{2,4}\b",

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
# PRODUCT TYPE
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
            images[0]
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
# PURCHASE LIMIT DETECTION
# =========================================================

def detect_purchase_limit(
    product,
):

    combined = (
        product_text(
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

        r"limit\s*(\d{1,2})",

        r"maximum\s*(?:of)?\s*(\d{1,2})\s*(?:per|/)\s*(?:customer|person|order|household)",

        r"max(?:imum)?\s*(?:qty|quantity)?\s*[:\-]?\s*(\d{1,2})",

        r"(\d{1,2})\s*(?:per|/)\s*(?:customer|person|order|household)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            combined,
            flags=re.IGNORECASE,
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
# SELECT BEST VARIANT
# =========================================================

def select_primary_variant(
    variants,
):

    if not variants:

        return None

    # Prefer an available variant.

    for variant in variants:

        if variant.get(
            "available"
        ):

            return variant

    return (
        variants[0]
    )


# =========================================================
# ADAPTER
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

        if (
            "preorder"
            in title.lower()
            or
            "pre-order"
            in title.lower()
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