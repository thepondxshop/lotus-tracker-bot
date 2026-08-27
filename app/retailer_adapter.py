from abc import (
    ABC,
    abstractmethod,
)

from dataclasses import (
    dataclass,
    field,
)

from typing import (
    Any,
)


# =========================================================
# LOTUS UNIVERSAL RETAILER ADAPTER
# PonDeX Trackers
# Version 1.0.4
#
# Common interface for non-Shopify retailers.
# =========================================================


SUPPORTED_PRODUCT_FAMILIES = {
    "GLOBAL_STANDARD",
    "JP",
    "KR",
    "CN",
    "UNKNOWN",
}


SUPPORTED_PRODUCT_CATEGORIES = {
    "SEALED",
    "SINGLE",
    "ACCESSORY",
    "UNKNOWN",
}


# =========================================================
# NORMALIZED RETAILER PRODUCT
# =========================================================

@dataclass
class RetailerProduct:

    external_id: str | None

    title: str

    game: str | None

    url: str

    price: float | None = None

    currency: str = "USD"

    available: bool = False

    product_type: str = "TCG Product"

    product_category: str = "UNKNOWN"

    product_family: str = "UNKNOWN"

    product_state: str = "PAGE_LIVE"

    image_url: str | None = None

    vendor: str | None = None

    tags: Any = None

    sku: str | None = None

    # =====================================================
    # UNIVERSAL RETAILER IDENTIFIERS
    # =====================================================

    external_product_id: str | None = None

    offer_id: str | None = None

    # =====================================================
    # SHOPIFY-STYLE / SUPPORTED CART METADATA
    #
    # Most non-Shopify adapters will leave variant_id None.
    # =====================================================

    variant_id: str | None = None

    purchase_limit: int | None = None

    cart_base_url: str | None = None

    # =====================================================
    # OPTIONAL PLATFORM METADATA
    # =====================================================

    platform_data: dict[str, Any] = field(
        default_factory=dict
    )


    # =====================================================
    # DICT CONTRACT
    #
    # Existing Lotus monitor/event code uses dictionaries.
    # This lets universal products plug into that pipeline.
    # =====================================================

    def to_dict(
        self,
    ):

        return {

            "external_id":
                self.external_id,

            "title":
                self.title,

            "game":
                self.game,

            "url":
                self.url,

            "price":
                self.price,

            "currency":
                self.currency,

            "available":
                self.available,

            "product_type":
                self.product_type,

            "product_category":
                self.product_category,

            "product_family":
                self.product_family,

            "product_state":
                self.product_state,

            "image_url":
                self.image_url,

            "vendor":
                self.vendor,

            "tags":
                self.tags,

            "sku":
                self.sku,

            "external_product_id":
                self.external_product_id,

            "offer_id":
                self.offer_id,

            "variant_id":
                self.variant_id,

            "purchase_limit":
                self.purchase_limit,

            "cart_base_url":
                self.cart_base_url,

            "platform_data":
                dict(
                    self.platform_data
                    or {}
                ),
        }


# =========================================================
# NORMALIZATION HELPERS
# =========================================================

def normalize_string(
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

    return value


def normalize_price(
    value,
):

    if value is None:

        return None

    try:

        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


def normalize_currency(
    value,
    default="USD",
):

    value = (
        normalize_string(
            value
        )
    )

    if not value:

        return (
            default.upper()
        )

    return (
        value.upper()
    )


def normalize_product_family(
    value,
):

    value = (
        normalize_string(
            value
        )
    )

    if not value:

        return (
            "UNKNOWN"
        )

    value = (
        value.upper()
    )

    if value not in SUPPORTED_PRODUCT_FAMILIES:

        return (
            "UNKNOWN"
        )

    return value


def normalize_product_category(
    value,
):

    value = (
        normalize_string(
            value
        )
    )

    if not value:

        return (
            "UNKNOWN"
        )

    value = (
        value.upper()
    )

    if value not in SUPPORTED_PRODUCT_CATEGORIES:

        return (
            "UNKNOWN"
        )

    return value


def normalize_purchase_limit(
    value,
):

    if value is None:

        return None

    try:

        value = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return None

    if value < 1:

        return None

    if value > 100:

        return None

    return value


# =========================================================
# BASE RETAILER ADAPTER
# =========================================================

class RetailerAdapter(
    ABC
):

    platform = "custom"

    def __init__(
        self,
        *,
        domain,
        region="US",
        store_name=None,
    ):

        self.domain = (
            str(
                domain
            )
            .strip()
            .lower()
        )

        self.region = (
            str(
                region
                or "US"
            )
            .strip()
            .upper()
        )

        self.store_name = (
            store_name
            or self.domain
        )


    # =====================================================
    # FETCH
    # =====================================================

    @abstractmethod
    async def fetch_products(
        self,
    ):

        raise NotImplementedError


    # =====================================================
    # NORMALIZE
    # =====================================================

    @abstractmethod
    def normalize_product(
        self,
        product,
    ):

        raise NotImplementedError


    # =====================================================
    # OPTIONAL HEALTH PROBE
    # =====================================================

    async def health_probe(
        self,
    ):

        products = (
            await self.fetch_products()
        )

        return {

            "success":
                True,

            "products":
                len(
                    products
                    or []
                ),
        }


    # =====================================================
    # FETCH + NORMALIZE
    # =====================================================

    async def get_normalized_products(
        self,
    ):

        raw_products = (
            await self.fetch_products()
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
                        "RETAILER NORMALIZE ERROR | "
                        f"Store={self.store_name} | "
                        f"Platform={self.platform} | "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )
                )

                continue

            if normalized is None:

                continue

            if isinstance(
                normalized,
                RetailerProduct,
            ):

                item = (
                    normalized.to_dict()
                )

            elif isinstance(
                normalized,
                dict,
            ):

                item = (
                    dict(
                        normalized
                    )
                )

            else:

                print(
                    (
                        "RETAILER NORMALIZE ERROR | "
                        f"Store={self.store_name} | "
                        "Reason=INVALID_NORMALIZED_TYPE"
                    )
                )

                continue

            url = (
                normalize_string(
                    item.get(
                        "url"
                    )
                )
            )

            if not url:

                continue

            if url in seen_urls:

                continue

            seen_urls.add(
                url
            )

            item[
                "url"
            ] = (
                url
            )

            item[
                "title"
            ] = (
                normalize_string(
                    item.get(
                        "title"
                    )
                )
                or "Unknown Product"
            )

            item[
                "currency"
            ] = (
                normalize_currency(
                    item.get(
                        "currency"
                    )
                )
            )

            item[
                "price"
            ] = (
                normalize_price(
                    item.get(
                        "price"
                    )
                )
            )

            item[
                "available"
            ] = (
                bool(
                    item.get(
                        "available"
                    )
                )
            )

            item[
                "product_category"
            ] = (
                normalize_product_category(
                    item.get(
                        "product_category"
                    )
                )
            )

            item[
                "product_family"
            ] = (
                normalize_product_family(
                    item.get(
                        "product_family"
                    )
                )
            )

            item[
                "purchase_limit"
            ] = (
                normalize_purchase_limit(
                    item.get(
                        "purchase_limit"
                    )
                )
            )

            item[
                "region"
            ] = (
                self.region
            )

            item[
                "source_type"
            ] = (
                self.platform
            )

            normalized_products.append(
                item
            )

        return (
            normalized_products
        )