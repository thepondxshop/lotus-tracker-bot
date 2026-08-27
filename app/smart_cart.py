from dataclasses import dataclass
from urllib.parse import urlparse


# =========================================================
# LOTUS SMART CART
# PonDeX Trackers
# Smart Cart v1
#
# Current scope:
# - Shopify cart permalinks
# - Quantity-aware cart links
# - Retailer-limit-aware buttons
# - Safe product-page fallback
#
# Shopify cart permalink format:
# https://store.example/cart/{variant_id}:{quantity}
# =========================================================


@dataclass
class SmartCartAction:
    label: str
    url: str
    quantity: int | None = None
    kind: str = "cart"


@dataclass
class SmartCartResult:
    supported: bool
    provider: str
    status_text: str
    actions: list[SmartCartAction]


def _clean_numeric_variant_id(
    variant_id,
):
    """
    Shopify cart permalinks require the numeric variant ID.

    Supports:
    - 123456789
    - "123456789"
    - "gid://shopify/ProductVariant/123456789"
    """

    if variant_id is None:
        return None

    value = str(
        variant_id
    ).strip()

    if not value:
        return None

    # GraphQL/GID format.
    if "/" in value:
        value = (
            value
            .rstrip("/")
            .split("/")[-1]
        )

    # Defensive cleanup for accidental query/fragment suffixes.
    value = (
        value
        .split("?")[0]
        .split("#")[0]
        .strip()
    )

    if not value.isdigit():
        return None

    return value


def _normalize_store_base_url(
    *,
    cart_base_url=None,
    product_url=None,
):
    """
    Returns scheme + host only.

    Examples:
    https://example.com/products/card
        -> https://example.com

    example.com/cart
        -> https://example.com
    """

    candidate = (
        cart_base_url
        or product_url
        or ""
    )

    candidate = str(
        candidate
    ).strip()

    if not candidate:
        return None

    if not candidate.startswith(
        (
            "http://",
            "https://",
        )
    ):
        candidate = (
            "https://"
            + candidate
        )

    try:
        parsed = urlparse(
            candidate
        )

        if not parsed.netloc:
            return None

        scheme = (
            parsed.scheme
            or "https"
        )

        return (
            f"{scheme}://"
            f"{parsed.netloc}"
        )

    except Exception:
        return None


def _safe_purchase_limit(
    purchase_limit,
):
    """
    Convert purchase limit to a positive int.
    Returns None when no reliable limit is available.
    """

    if purchase_limit is None:
        return None

    try:
        value = int(
            purchase_limit
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if value <= 0:
        return None

    return value


def build_shopify_cart_url(
    *,
    variant_id,
    quantity=1,
    cart_base_url=None,
    product_url=None,
):
    """
    Build a Shopify cart permalink.

    Example:
    https://example.com/cart/123456789:2
    """

    numeric_variant_id = (
        _clean_numeric_variant_id(
            variant_id
        )
    )

    if numeric_variant_id is None:
        return None

    base_url = (
        _normalize_store_base_url(
            cart_base_url=(
                cart_base_url
            ),
            product_url=(
                product_url
            ),
        )
    )

    if base_url is None:
        return None

    try:
        quantity = int(
            quantity
        )

    except (
        TypeError,
        ValueError,
    ):
        quantity = 1

    quantity = max(
        1,
        quantity,
    )

    return (
        f"{base_url}/cart/"
        f"{numeric_variant_id}:"
        f"{quantity}"
    )


def build_smart_cart(
    event,
    *,
    product_url=None,
):
    """
    Build Smart Cart actions for an event.

    Smart Cart v1 intentionally avoids pretending a purchase
    limit exists when the monitor did not detect one.

    Behavior:
    - Limit 1 -> Add 1
    - Limit 2+ -> Add 1 + Add up to detected limit
    - Unknown limit -> Add 1 only
    - Missing Shopify variant/base -> product-page fallback
    - Sold-out alerts do not show an add-to-cart action
    """

    source_type = (
        event.get(
            "source_type"
        )
        or ""
    ).lower()

    event_type = (
        event.get(
            "event_type"
        )
        or ""
    ).upper()

    variant_id = (
        event.get(
            "variant_id"
        )
    )

    purchase_limit = (
        _safe_purchase_limit(
            event.get(
                "purchase_limit"
            )
        )
    )

    cart_base_url = (
        event.get(
            "cart_base_url"
        )
    )

    effective_product_url = (
        product_url
        or event.get(
            "product_url"
        )
        or ""
    )

    # =====================================================
    # SOLD OUT
    # =====================================================

    if event_type == "SOLD_OUT":
        actions = []

        if effective_product_url:
            actions.append(
                SmartCartAction(
                    label="Open Product",
                    url=(
                        effective_product_url
                    ),
                    kind="product",
                )
            )

        return SmartCartResult(
            supported=False,
            provider=(
                source_type
                or "unknown"
            ),
            status_text=(
                "Currently sold out â¢ "
                "product page available"
            ),
            actions=actions,
        )

    # =====================================================
    # SHOPIFY
    # =====================================================

    if source_type == "shopify":
        add_one_url = (
            build_shopify_cart_url(
                variant_id=(
                    variant_id
                ),
                quantity=1,
                cart_base_url=(
                    cart_base_url
                ),
                product_url=(
                    effective_product_url
                ),
            )
        )

        if add_one_url:
            actions = [
                SmartCartAction(
                    label="Add 1 to Cart",
                    url=add_one_url,
                    quantity=1,
                    kind="cart",
                )
            ]

            # If a retailer limit is detected, provide a
            # second button for that quantity.
            #
            # We cap this display button at 5 in v1 to avoid
            # extreme quantities and clutter. Add 1 is always
            # available as the conservative choice.
            if (
                purchase_limit is not None
                and purchase_limit >= 2
            ):
                secondary_quantity = min(
                    purchase_limit,
                    5,
                )

                secondary_url = (
                    build_shopify_cart_url(
                        variant_id=(
                            variant_id
                        ),
                        quantity=(
                            secondary_quantity
                        ),
                        cart_base_url=(
                            cart_base_url
                        ),
                        product_url=(
                            effective_product_url
                        ),
                    )
                )

                if secondary_url:
                    actions.append(
                        SmartCartAction(
                            label=(
                                "Add "
                                f"{secondary_quantity} "
                                "to Cart"
                            ),
                            url=(
                                secondary_url
                            ),
                            quantity=(
                                secondary_quantity
                            ),
                            kind="cart",
                        )
                    )

            if effective_product_url:
                actions.append(
                    SmartCartAction(
                        label="Open Product",
                        url=(
                            effective_product_url
                        ),
                        kind="product",
                    )
                )

            if purchase_limit is not None:
                status_text = (
                    "â Retailer limit detected: "
                    f"**{purchase_limit}**"
                )
            else:
                status_text = (
                    "â ï¸ Limit not detected â¢ "
                    "Add 1 is the safe default"
                )

            return SmartCartResult(
                supported=True,
                provider="shopify",
                status_text=(
                    status_text
                ),
                actions=actions,
            )

    # =====================================================
    # FALLBACK
    # =====================================================

    actions = []

    if effective_product_url:
        actions.append(
            SmartCartAction(
                label="Open Product",
                url=(
                    effective_product_url
                ),
                kind="product",
            )
        )

    return SmartCartResult(
        supported=False,
        provider=(
            source_type
            or "unknown"
        ),
        status_text=(
            "Direct cart unavailable â¢ "
            "use product page"
        ),
        actions=actions,
    )
