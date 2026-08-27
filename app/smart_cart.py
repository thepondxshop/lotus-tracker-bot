from dataclasses import dataclass
from urllib.parse import urlparse


# =========================================================
# LOTUS SMART CART
# PonDeX Trackers
# Version 1.0.3
#
# Shopify Smart Cart v1
#
# Features:
#
# - Shopify variant cart URLs
# - Product-page fallback
# - Purchase-limit protection
# - Quantity options
# - Safe URL validation
# - Ready for Discord buttons
# =========================================================


DEFAULT_QUANTITIES = (
    1,
    2,
    3,
    4,
    5,
    10,
)


MAX_SAFE_QUANTITY = 25


# =========================================================
# SMART CART RESULT
# =========================================================

@dataclass
class SmartCartResult:

    supported: bool

    product_url: str | None

    cart_base_url: str | None

    variant_id: str | None

    purchase_limit: int | None

    quantities: list[int]

    cart_links: dict[int, str]

    primary_quantity: int | None

    primary_cart_url: str | None

    reason: str | None = None


# =========================================================
# SAFE INTEGER
# =========================================================

def safe_positive_int(
    value,
):

    if value is None:

        return None

    try:

        parsed = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return None

    if parsed <= 0:

        return None

    return parsed


# =========================================================
# NORMALIZE VARIANT ID
# =========================================================

def normalize_variant_id(
    value,
):

    if value is None:

        return None

    value = str(
        value
    ).strip()

    if not value:

        return None

    # Shopify variant IDs are numeric.
    #
    # Keeping this strict prevents malformed cart paths.

    if not value.isdigit():

        return None

    return value


# =========================================================
# NORMALIZE URL
# =========================================================

def normalize_base_url(
    value,
):

    if not value:

        return None

    value = str(
        value
    ).strip()

    if not value:

        return None

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

    try:

        parsed = urlparse(
            value
        )

    except Exception:

        return None

    if not parsed.hostname:

        return None

    scheme = (
        parsed.scheme
        or "https"
    )

    hostname = (
        parsed.hostname
        .lower()
    )

    # Preserve non-standard port if one exists.

    netloc = hostname

    if parsed.port:

        netloc = (
            f"{hostname}:{parsed.port}"
        )

    return (
        f"{scheme}://{netloc}"
    )


# =========================================================
# NORMALIZE PRODUCT URL
# =========================================================

def normalize_product_url(
    value,
):

    if not value:

        return None

    value = str(
        value
    ).strip()

    if not value:

        return None

    if not value.startswith(
        (
            "http://",
            "https://",
        )
    ):

        return None

    try:

        parsed = urlparse(
            value
        )

    except Exception:

        return None

    if not parsed.hostname:

        return None

    return value


# =========================================================
# PURCHASE LIMIT
# =========================================================

def normalize_purchase_limit(
    value,
):

    parsed = (
        safe_positive_int(
            value
        )
    )

    if parsed is None:

        return None

    # Protect against bad scraper/parser values.
    #
    # Example:
    # "limit 9999" should not create an absurd cart URL.

    return min(
        parsed,
        MAX_SAFE_QUANTITY,
    )


# =========================================================
# QUANTITY OPTIONS
# =========================================================

def build_quantity_options(
    purchase_limit=None,
    requested_quantities=None,
):

    limit = (
        normalize_purchase_limit(
            purchase_limit
        )
    )

    quantities = (
        requested_quantities
        or DEFAULT_QUANTITIES
    )

    output = []

    for quantity in quantities:

        parsed = (
            safe_positive_int(
                quantity
            )
        )

        if parsed is None:

            continue

        if parsed > MAX_SAFE_QUANTITY:

            continue

        if (
            limit is not None
            and parsed > limit
        ):

            continue

        output.append(
            parsed
        )

    # =====================================================
    # ALWAYS INCLUDE LIMIT ITSELF
    #
    # Example:
    #
    # Normal buttons:
    # 1,2,3,4,5,10
    #
    # Retailer limit:
    # 6
    #
    # Result:
    # 1,2,3,4,5,6
    # =====================================================

    if (
        limit is not None
        and limit not in output
    ):

        output.append(
            limit
        )

    # =====================================================
    # ENSURE x1 EXISTS
    # =====================================================

    if (
        limit is None
        or limit >= 1
    ):

        if 1 not in output:

            output.append(
                1
            )

    return sorted(
        set(
            output
        )
    )


# =========================================================
# BUILD SHOPIFY CART URL
# =========================================================

def build_shopify_cart_url(
    *,
    cart_base_url,
    variant_id,
    quantity=1,
    purchase_limit=None,
):

    base = (
        normalize_base_url(
            cart_base_url
        )
    )

    variant = (
        normalize_variant_id(
            variant_id
        )
    )

    qty = (
        safe_positive_int(
            quantity
        )
    )

    limit = (
        normalize_purchase_limit(
            purchase_limit
        )
    )

    if base is None:

        return None

    if variant is None:

        return None

    if qty is None:

        return None

    if qty > MAX_SAFE_QUANTITY:

        return None

    if (
        limit is not None
        and qty > limit
    ):

        return None

    # Shopify cart permalink format:
    #
    # https://store.com/cart/VARIANT_ID:QTY

    return (
        f"{base}/cart/"
        f"{variant}:{qty}"
    )


# =========================================================
# BUILD ALL CART LINKS
# =========================================================

def build_shopify_cart_links(
    *,
    cart_base_url,
    variant_id,
    purchase_limit=None,
    requested_quantities=None,
):

    quantities = (
        build_quantity_options(

            purchase_limit=(
                purchase_limit
            ),

            requested_quantities=(
                requested_quantities
            ),
        )
    )

    links = {}

    for quantity in quantities:

        url = (
            build_shopify_cart_url(

                cart_base_url=(
                    cart_base_url
                ),

                variant_id=(
                    variant_id
                ),

                quantity=(
                    quantity
                ),

                purchase_limit=(
                    purchase_limit
                ),
            )
        )

        if url:

            links[
                quantity
            ] = (
                url
            )

    return links


# =========================================================
# PRIMARY QUANTITY
# =========================================================

def choose_primary_quantity(
    quantities,
    purchase_limit=None,
):

    if not quantities:

        return None

    limit = (
        normalize_purchase_limit(
            purchase_limit
        )
    )

    # =====================================================
    # DEFAULT PRIMARY BUTTON
    #
    # Use x1 by default.
    #
    # We do NOT automatically use the purchase maximum
    # because that could cause someone to accidentally add
    # several expensive products to cart.
    # =====================================================

    if 1 in quantities:

        return 1

    # Defensive fallback.

    if limit is not None:

        allowed = [

            quantity

            for quantity in quantities

            if quantity <= limit
        ]

        if allowed:

            return min(
                allowed
            )

    return min(
        quantities
    )


# =========================================================
# BUILD SMART CART
# =========================================================

def build_smart_cart(
    *,
    product_url=None,
    cart_base_url=None,
    variant_id=None,
    purchase_limit=None,
    requested_quantities=None,
):

    product_url = (
        normalize_product_url(
            product_url
        )
    )

    base_url = (
        normalize_base_url(
            cart_base_url
        )
    )

    variant = (
        normalize_variant_id(
            variant_id
        )
    )

    limit = (
        normalize_purchase_limit(
            purchase_limit
        )
    )

    # =====================================================
    # PRODUCT PAGE ONLY
    # =====================================================

    if base_url is None:

        return SmartCartResult(

            supported=False,

            product_url=(
                product_url
            ),

            cart_base_url=None,

            variant_id=(
                variant
            ),

            purchase_limit=(
                limit
            ),

            quantities=[],

            cart_links={},

            primary_quantity=None,

            primary_cart_url=None,

            reason=(
                "CART_BASE_URL_MISSING"
            ),
        )

    if variant is None:

        return SmartCartResult(

            supported=False,

            product_url=(
                product_url
            ),

            cart_base_url=(
                base_url
            ),

            variant_id=None,

            purchase_limit=(
                limit
            ),

            quantities=[],

            cart_links={},

            primary_quantity=None,

            primary_cart_url=None,

            reason=(
                "VARIANT_ID_MISSING"
            ),
        )

    # =====================================================
    # CART LINKS
    # =====================================================

    cart_links = (
        build_shopify_cart_links(

            cart_base_url=(
                base_url
            ),

            variant_id=(
                variant
            ),

            purchase_limit=(
                limit
            ),

            requested_quantities=(
                requested_quantities
            ),
        )
    )

    quantities = sorted(
        cart_links.keys()
    )

    if not quantities:

        return SmartCartResult(

            supported=False,

            product_url=(
                product_url
            ),

            cart_base_url=(
                base_url
            ),

            variant_id=(
                variant
            ),

            purchase_limit=(
                limit
            ),

            quantities=[],

            cart_links={},

            primary_quantity=None,

            primary_cart_url=None,

            reason=(
                "NO_SAFE_QUANTITIES"
            ),
        )

    primary_quantity = (
        choose_primary_quantity(

            quantities,

            purchase_limit=(
                limit
            ),
        )
    )

    primary_cart_url = (
        cart_links.get(
            primary_quantity
        )
    )

    return SmartCartResult(

        supported=True,

        product_url=(
            product_url
        ),

        cart_base_url=(
            base_url
        ),

        variant_id=(
            variant
        ),

        purchase_limit=(
            limit
        ),

        quantities=(
            quantities
        ),

        cart_links=(
            cart_links
        ),

        primary_quantity=(
            primary_quantity
        ),

        primary_cart_url=(
            primary_cart_url
        ),

        reason=None,
    )


# =========================================================
# EVENT -> SMART CART
# =========================================================

def build_smart_cart_from_event(
    event,
):

    if not event:

        return SmartCartResult(

            supported=False,

            product_url=None,

            cart_base_url=None,

            variant_id=None,

            purchase_limit=None,

            quantities=[],

            cart_links={},

            primary_quantity=None,

            primary_cart_url=None,

            reason="EVENT_MISSING",
        )

    return (
        build_smart_cart(

            product_url=(
                event.get(
                    "product_url"
                )
            ),

            cart_base_url=(
                event.get(
                    "cart_base_url"
                )
            ),

            variant_id=(
                event.get(
                    "variant_id"
                )
            ),

            purchase_limit=(
                event.get(
                    "purchase_limit"
                )
            ),
        )
    )


# =========================================================
# DEBUG SUMMARY
# =========================================================

def smart_cart_debug_summary(
    result,
):

    if result is None:

        return (
            "SmartCart(None)"
        )

    return (
        "SmartCart("
        f"supported={result.supported}, "
        f"variant={result.variant_id}, "
        f"limit={result.purchase_limit}, "
        f"quantities={result.quantities}, "
        f"reason={result.reason}"
        ")"
    )