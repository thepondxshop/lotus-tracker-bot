from urllib.parse import (
    urlparse,
)

import aiohttp


# =========================================================
# LOTUS SHOPIFY ADAPTER
# PonDeX Trackers
# Version 0.7.7
#
# Shopify Products API
# Native Currency Detection
# TCG Classification
# Product Images
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

    "JP":
        "JPY",

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
# GAME KEYWORDS
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


def classify_game(
    product,
):

    combined = " ".join(
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
        ]
    ).lower()

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
# TYPE
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
                            "PonDeX-Trackers/0.7.7",
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
                "PonDeX-Trackers/0.7.7",
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

        prices = []

        for variant in variants:

            raw_price = (
                variant.get(
                    "price"
                )
            )

            try:

                if raw_price is not None:

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
        }