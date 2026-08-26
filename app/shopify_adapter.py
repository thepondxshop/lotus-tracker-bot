import aiohttp


# =========================================================
# LOTUS SHOPIFY ADAPTER
# PonDeX Trackers
# Version 0.6
#
# Uses publicly accessible Shopify product data only.
# Does not bypass CAPTCHA, queues, rate limits,
# authentication, or anti-bot protections.
# =========================================================


def normalize_shopify_domain(
    domain: str,
) -> str:

    domain = domain.strip()

    domain = domain.replace(
        "https://",
        "",
    )

    domain = domain.replace(
        "http://",
        "",
    )

    domain = domain.rstrip("/")

    return domain.lower()


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
                "PonDeX-Trackers/0.6",
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
                                f"not accessible: HTTP "
                                f"{response.status}"
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

                    data = (
                        await response.json()
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

                    # Some stores may return the
                    # same page repeatedly.
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

        available = any(
            variant.get(
                "available",
                False,
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

        handle = (
            product.get(
                "handle"
            )
        )

        if handle:

            product_url = (
                f"{self.base_url}"
                f"/products/{handle}"
            )

        else:

            product_url = (
                self.base_url
            )

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
                classify_shopify_game(
                    product
                ),
        }