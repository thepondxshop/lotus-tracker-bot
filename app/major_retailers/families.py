"""Reusable major-retailer adapter family recommendations for Lotus Step 6K-2A."""

from __future__ import annotations

from dataclasses import asdict, dataclass

VERSION = "1.0.6"
STEP = "6K-2A"


@dataclass(frozen=True)
class MajorRetailerAdapterFamily:
    key: str
    display_name: str
    reusable: bool
    description: str

    def to_dict(self) -> dict:
        return asdict(self)


_PLATFORM_FAMILIES: dict[str, MajorRetailerAdapterFamily] = {
    "shopify": MajorRetailerAdapterFamily(
        key="SHOPIFY_MAJOR",
        display_name="Shopify Major Retailer Base",
        reusable=True,
        description="Reuse Shopify catalog/product primitives while keeping major-retailer policy and alert routing separate.",
    ),
    "woocommerce": MajorRetailerAdapterFamily(
        key="WOOCOMMERCE_MAJOR",
        display_name="WooCommerce Major Retailer Base",
        reusable=True,
        description="Reuse WooCommerce Store API/public catalog primitives with dedicated major-retailer safety rules.",
    ),
    "bigcommerce": MajorRetailerAdapterFamily(
        key="BIGCOMMERCE_MAJOR",
        display_name="BigCommerce Major Retailer Base",
        reusable=True,
        description="Reuse BigCommerce storefront discovery with retailer-specific normalization layered on top.",
    ),
    "prestashop": MajorRetailerAdapterFamily(
        key="PRESTASHOP_MAJOR",
        display_name="PrestaShop Major Retailer Base",
        reusable=True,
        description="Reuse PrestaShop storefront discovery when public product data is available.",
    ),
    "square_weebly": MajorRetailerAdapterFamily(
        key="SQUARE_MAJOR",
        display_name="Square / Weebly Major Retailer Base",
        reusable=True,
        description="Reuse Square/Weebly storefront discovery with dedicated major-retailer capability gating.",
    ),
    "shopware": MajorRetailerAdapterFamily(
        key="SHOPWARE_MAJOR",
        display_name="Shopware Major Retailer Base",
        reusable=True,
        description="Reuse Shopware discovery primitives when the storefront exposes reliable public commerce data.",
    ),
    "shopware_6": MajorRetailerAdapterFamily(
        key="SHOPWARE_MAJOR",
        display_name="Shopware Major Retailer Base",
        reusable=True,
        description="Reuse Shopware 6 discovery primitives when the storefront exposes reliable public commerce data.",
    ),
    "magento": MajorRetailerAdapterFamily(
        key="ADOBE_COMMERCE_MAJOR",
        display_name="Adobe Commerce / Magento Major Retailer Base",
        reusable=True,
        description="Shared Adobe Commerce/Magento foundation; retailer-specific endpoints still require validation.",
    ),
    "adobe_commerce": MajorRetailerAdapterFamily(
        key="ADOBE_COMMERCE_MAJOR",
        display_name="Adobe Commerce / Magento Major Retailer Base",
        reusable=True,
        description="Shared Adobe Commerce/Magento foundation; retailer-specific endpoints still require validation.",
    ),
}

_CUSTOM = MajorRetailerAdapterFamily(
    key="CUSTOM_MAJOR",
    display_name="Custom Major Retailer Adapter",
    reusable=False,
    description="No reusable storefront family is confirmed; build or connect a retailer-specific public/official source.",
)


def recommend_adapter_family(platform: str | None) -> MajorRetailerAdapterFamily:
    normalized = str(platform or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _PLATFORM_FAMILIES.get(normalized, _CUSTOM)


def list_adapter_families() -> list[dict]:
    seen: set[str] = set()
    rows = []
    for family in _PLATFORM_FAMILIES.values():
        if family.key in seen:
            continue
        seen.add(family.key)
        rows.append(family.to_dict())
    rows.append(_CUSTOM.to_dict())
    return rows
