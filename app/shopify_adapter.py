from urllib.parse import urlparse

import aiohttp

from app.product_intelligence import (
    classify_product_state,
)


# =========================================================
# LOTUS SHOPIFY ADAPTER
# PonDeX Trackers
# Version 0.6.2
#
# Features:
# - URL cleanup
# - Shopify catalog retrieval
# - TCG classification
# - Product-state intelligence
# =========================================================


# =========================================================
# DOMAIN NORMALIZATION
# =========================================================

def normalize_shopify_domain(
    value: str,
) -> str:

    value = value.strip()

    if not value:

        raise ValueError(
            "Store domain cannot be empty."
        )

    # -----------------------------------------------------
    # Users may paste:
    #
    # sagaconcepts.com
    #
    # https://sagaconcepts.com
    #
    # https://www.sagaconcepts.com/
    #
    # https://sagaconcepts.com/?tracking=123
    #
    # https://sagaconcepts.com/products/item
    #
    # Lotus always saves:
    #
    # sagaconcepts.com
    # -----------------------------------------------------

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

    parsed = urlparse(
        value
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

    hostname = hostname.strip(
        "."
    )

    if not hostname:

        raise ValueError(
            (
                "Could not determine "
                "a valid store domain."
            )
        )

    return hostname


# =========================================================
# GAME CLASSIFICATION
# =========================================================

def classify_shopify_game(
    product: dict,
):

    searchable = " ".join(
        [
            str(
                product.get(
                    "title",
                    "",
                )
            ),
            str(
                product.get(
                    "vendor",
                    "",
                )
            ),
            str(
                product.get(
                    "product_type",
                    "",
                )
            ),
            str(
                product.get(
                    "tags",
                    "",
                )
            ),
            str(
                product.get(
                    "body_html",
                    "",
                )
            ),
        ]
    ).lower()

    rules = [

        (
            "One Piece",
            [
                "one piece",
                "onepiece",
                "one piece card game",
            ],
        ),

        (
            "Pokemon",
            [
                "pokemon",
                "pokémon",
                "pokemon tcg",
            ],
        ),

        (
            "Gundam",
            [
                "gundam",
                "gundam card game",
            ],
        ),

        (
            "Dragon Ball Fusion World",
            [
                "dragon ball fusion world",
                "fusion world",
            ],
        ),

        (
            "Riftbound",
            [
                "riftbound",
                "league of legends tcg",
            ],
        ),

        (
            "Palworld",
            [
                "palworld",
            ],
        ),

        (
            "Naruto",
            [
                "naruto",
            ],
        ),

        (
            "Cyberpunk TCG",
            [
                "cyberpunk tcg",
                "cyberpunk trading card",
            ],
        ),

        (
            "Azuki TCG",
            [
                "azuki tcg",
                "azuki trading card",
            ],
        ),

        (
            "Hellbreak TCG",
            [
                "hellbreak",
            ],
        ),
    ]

    for game, keywords in rules:

        for keyword in keywords:

            if keyword in searchable:

                return game

    return None


# =========================================================
# SHOPIFY ADAPTER
# =========================================================

class ShopifyAdapter:

    def __init__(
        self,
        domain: str,
    ):

        self.domain = (
            normalize_shopify_domain(
                domain
            )
        )

        self.base_url = (
            f"https://{self.domain}"
        )


    # =====================================================
    # FETCH PRODUCTS
    # =====================================================

    async def fetch_products(
        self,
        max_pages: int = 10,
    ):

        timeout = (
            aiohttp.ClientTimeout(
                total=30
            )
        )

        headers = {

            "Accept":
                "application/json",

            "User-Agent":
                "PonDeX-Trackers/0.6.2",
        }

        all_products = []

        seen_product_ids = set()

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
                    f"?limit=250&page={page}"
                )

                async with session.get(
                    url
                ) as response:

                    if response.status == 429:

                        raise RuntimeError(
                            (
                                "Shopify store returned "
                                "HTTP 429 rate limit."
                            )
                        )

                    if response.status in (
                        401,
                        403,
                    ):

                        raise RuntimeError(
                            (
                                "Shopify product endpoint "
                                f"not accessible: "
                                f"HTTP {response.status}"
                            )
                        )

                    if response.status == 404:

                        raise RuntimeError(
                            (
                                "Shopify products endpoint "
                                "was not found."
                            )
                        )

                    if response.status != 200:

                        raise RuntimeError(
                            (
                                "Shopify request failed: "
                                f"HTTP {response.status}"
                            )
                        )

                    try:

                        data = (
                            await response.json()
                        )

                    except Exception as error:

                        raise RuntimeError(
                            (
                                "Shopify returned invalid "
                                "product JSON: "
                                f"{type(error).__name__}: "
                                f"{error}"
                            )
                        )

                    products = (
                        data.get(
                            "products",
                            []
                        )
                    )

                    if not products:

                        break

                    new_products_found = 0

                    for product in products:

                        product_id = (
                            product.get(
                                "id"
                            )
                        )

                        if (
                            product_id
                            in seen_product_ids
                        ):

                            continue

                        seen_product_ids.add(
                            product_id
                        )

                        all_products.append(
                            product
                        )

                        new_products_found += 1

                    # -------------------------------------
                    # Some Shopify stores may return the
                    # same page repeatedly.
                    # -------------------------------------

                    if new_products_found == 0:

                        break

                    if len(
                        products
                    ) < 250:

                        break

        return all_products


    # =====================================================
    # NORMALIZE PRODUCT
    # =====================================================

    def normalize_product(
        self,
        product: dict,
    ):

        variants = (
            product.get(
                "variants"
            )
            or []
        )

        # -------------------------------------------------
        # AVAILABILITY
        # -------------------------------------------------

        available = any(
            variant.get(
                "available",
                False,
            )
            for variant in variants
        )

        # -------------------------------------------------
        # PRICE
        # -------------------------------------------------

        prices = []

        for variant in variants:

            raw_price = (
                variant.get(
                    "price"
                )
            )

            if raw_price is None:

                continue

            try:

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

        # -------------------------------------------------
        # PRODUCT URL
        # -------------------------------------------------

        handle = (
            product.get(
                "handle"
            )
        )

        product_url = (

            (
                f"{self.base_url}"
                f"/products/{handle}"
            )

            if handle

            else self.base_url
        )

        # -------------------------------------------------
        # GAME
        # -------------------------------------------------

        game = (
            classify_shopify_game(
                product
            )
        )

        # -------------------------------------------------
        # PRODUCT INTELLIGENCE
        # -------------------------------------------------

        product_state = (
            classify_product_state(
                product,
                available,
            )
        )

        # -------------------------------------------------
        # RESULT
        # -------------------------------------------------

        return {

            "shopify_id":
                product.get(
                    "id"
                ),

            "title":
                product.get(
                    "title",
                    "Unknown Product",
                ),

            "url":
                product_url,

            "available":
                available,

            "price":
                price,

            "vendor":
                product.get(
                    "vendor"
                ),

            "product_type":
                (
                    product.get(
                        "product_type"
                    )
                    or "Unknown"
                ),

            "tags":
                product.get(
                    "tags"
                ),

            "game":
                game,

            "product_state":
                product_state,
        }