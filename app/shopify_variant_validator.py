import asyncio
import aiohttp

from dataclasses import dataclass
from urllib.parse import (
    urlparse,
)


# =========================================================
# LOTUS SHOPIFY VARIANT VALIDATOR
# PonDeX Trackers
# Version 1.0.3
#
# Smart Cart Variant Validation
#
# Verifies:
#
# - Shopify product URL is valid
# - Product JSON is reachable
# - Variant still exists
# - Variant availability
# - Current variant price
# - Variant title
#
# Does NOT:
#
# - Add anything to a user's cart
# - Checkout
# - Reserve inventory
# =========================================================


VALIDATION_TIMEOUT_SECONDS = (
    10
)


# =========================================================
# VALIDATION RESULT
# =========================================================

@dataclass
class ShopifyVariantValidation:

    checked: bool

    valid: bool

    available: bool

    variant_id: str | None

    variant_title: str | None

    price: float | None

    product_title: str | None

    http_status: int | None

    reason: str | None

    product_json_url: str | None


# =========================================================
# SAFE FLOAT
# =========================================================

def safe_float(
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


# =========================================================
# NORMALIZE VARIANT
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

    if not value.isdigit():

        return None

    return value


# =========================================================
# PRODUCT JSON URL
#
# Shopify supports:
#
# /products/product-handle.js
#
# Example:
#
# https://store.com/products/op20-booster-box
#
# becomes:
#
# https://store.com/products/op20-booster-box.js
# =========================================================

def build_product_json_url(
    product_url,
):

    if not product_url:

        return None

    try:

        parsed = (
            urlparse(
                str(
                    product_url
                ).strip()
            )
        )

    except Exception:

        return None


    if (
        parsed.scheme
        not in {
            "http",
            "https",
        }
    ):

        return None


    if not parsed.netloc:

        return None


    path = (
        parsed.path
        or ""
    )


    # =====================================================
    # MUST BE A SHOPIFY PRODUCT PATH
    # =====================================================

    if (
        "/products/"
        not in path
    ):

        return None


    # =====================================================
    # REMOVE TRAILING SLASH
    # =====================================================

    path = (
        path.rstrip(
            "/"
        )
    )


    # =====================================================
    # AVOID DOUBLE .JS
    # =====================================================

    if path.endswith(
        ".js"
    ):

        json_path = (
            path
        )

    else:

        json_path = (
            path
            + ".js"
        )


    return (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{json_path}"
    )


# =========================================================
# FIND VARIANT
# =========================================================

def find_variant(
    product_data,
    variant_id,
):

    if not isinstance(
        product_data,
        dict,
    ):

        return None


    variants = (
        product_data.get(
            "variants"
        )
        or []
    )


    target = (
        normalize_variant_id(
            variant_id
        )
    )


    if target is None:

        return None


    for variant in variants:

        if not isinstance(
            variant,
            dict,
        ):

            continue


        current_id = (
            normalize_variant_id(
                variant.get(
                    "id"
                )
            )
        )


        if (
            current_id
            == target
        ):

            return variant


    return None


# =========================================================
# PRICE NORMALIZATION
#
# Shopify product .js endpoints commonly return prices
# in cents.
#
# Example:
#
# 11999 -> $119.99
#
# Some stores/apps can return decimal-style values, so
# this function handles both forms defensively.
# =========================================================

def normalize_shopify_price(
    value,
):

    parsed = (
        safe_float(
            value
        )
    )


    if parsed is None:

        return None


    # Integer-style Shopify cents.

    if (
        isinstance(
            value,
            int,
        )

        or

        (
            isinstance(
                value,
                str,
            )

            and

            value.isdigit()
        )
    ):

        return (
            parsed
            / 100.0
        )


    return parsed


# =========================================================
# VALIDATE SHOPIFY VARIANT
# =========================================================

async def validate_shopify_variant(
    *,
    product_url,
    variant_id,
):

    variant_id = (
        normalize_variant_id(
            variant_id
        )
    )


    # =====================================================
    # NO VARIANT
    # =====================================================

    if variant_id is None:

        return ShopifyVariantValidation(

            checked=False,

            valid=False,

            available=False,

            variant_id=None,

            variant_title=None,

            price=None,

            product_title=None,

            http_status=None,

            reason=(
                "VARIANT_ID_MISSING"
            ),

            product_json_url=None,
        )


    # =====================================================
    # PRODUCT JSON URL
    # =====================================================

    product_json_url = (
        build_product_json_url(
            product_url
        )
    )


    if product_json_url is None:

        return ShopifyVariantValidation(

            checked=False,

            valid=False,

            available=False,

            variant_id=(
                variant_id
            ),

            variant_title=None,

            price=None,

            product_title=None,

            http_status=None,

            reason=(
                "INVALID_PRODUCT_URL"
            ),

            product_json_url=None,
        )


    timeout = (
        aiohttp.ClientTimeout(
            total=(
                VALIDATION_TIMEOUT_SECONDS
            )
        )
    )


    headers = {

        "Accept":
            "application/json",

        "User-Agent":
            "PonDeX-Trackers/1.0.3",
    }


    # =====================================================
    # FETCH PRODUCT JSON
    # =====================================================

    try:

        async with aiohttp.ClientSession(

            timeout=(
                timeout
            ),

            headers=(
                headers
            ),

        ) as session:

            async with session.get(

                product_json_url,

                allow_redirects=True,

            ) as response:

                status = (
                    response.status
                )


                # =========================================
                # PRODUCT NO LONGER AVAILABLE
                # =========================================

                if status == 404:

                    return ShopifyVariantValidation(

                        checked=True,

                        valid=False,

                        available=False,

                        variant_id=(
                            variant_id
                        ),

                        variant_title=None,

                        price=None,

                        product_title=None,

                        http_status=(
                            status
                        ),

                        reason=(
                            "PRODUCT_NOT_FOUND"
                        ),

                        product_json_url=(
                            product_json_url
                        ),
                    )


                # =========================================
                # NON-200 RESPONSE
                # =========================================

                if status != 200:

                    return ShopifyVariantValidation(

                        checked=True,

                        valid=False,

                        available=False,

                        variant_id=(
                            variant_id
                        ),

                        variant_title=None,

                        price=None,

                        product_title=None,

                        http_status=(
                            status
                        ),

                        reason=(
                            f"HTTP_{status}"
                        ),

                        product_json_url=(
                            product_json_url
                        ),
                    )


                # =========================================
                # JSON
                # =========================================

                try:

                    data = (
                        await response.json(
                            content_type=None
                        )
                    )


                except Exception:

                    return ShopifyVariantValidation(

                        checked=True,

                        valid=False,

                        available=False,

                        variant_id=(
                            variant_id
                        ),

                        variant_title=None,

                        price=None,

                        product_title=None,

                        http_status=(
                            status
                        ),

                        reason=(
                            "INVALID_JSON"
                        ),

                        product_json_url=(
                            product_json_url
                        ),
                    )


    except asyncio.TimeoutError:

        return ShopifyVariantValidation(

            checked=False,

            valid=False,

            available=False,

            variant_id=(
                variant_id
            ),

            variant_title=None,

            price=None,

            product_title=None,

            http_status=None,

            reason=(
                "TIMEOUT"
            ),

            product_json_url=(
                product_json_url
            ),
        )


    except Exception as error:

        return ShopifyVariantValidation(

            checked=False,

            valid=False,

            available=False,

            variant_id=(
                variant_id
            ),

            variant_title=None,

            price=None,

            product_title=None,

            http_status=None,

            reason=(
                (
                    f"{type(error).__name__}: "
                    f"{error}"
                )[:500]
            ),

            product_json_url=(
                product_json_url
            ),
        )


    # =====================================================
    # FIND VARIANT
    # =====================================================

    variant = (
        find_variant(

            data,

            variant_id,
        )
    )


    if variant is None:

        return ShopifyVariantValidation(

            checked=True,

            valid=False,

            available=False,

            variant_id=(
                variant_id
            ),

            variant_title=None,

            price=None,

            product_title=(
                data.get(
                    "title"
                )
            ),

            http_status=200,

            reason=(
                "VARIANT_NOT_FOUND"
            ),

            product_json_url=(
                product_json_url
            ),
        )


    # =====================================================
    # AVAILABILITY
    # =====================================================

    available = bool(
        variant.get(
            "available"
        )
    )


    price = (
        normalize_shopify_price(
            variant.get(
                "price"
            )
        )
    )


    return ShopifyVariantValidation(

        checked=True,

        valid=True,

        available=(
            available
        ),

        variant_id=(
            variant_id
        ),

        variant_title=(
            variant.get(
                "title"
            )
        ),

        price=(
            price
        ),

        product_title=(
            data.get(
                "title"
            )
        ),

        http_status=200,

        reason=(

            "AVAILABLE"

            if available

            else "SOLD_OUT"
        ),

        product_json_url=(
            product_json_url
        ),
    )


# =========================================================
# VALIDATE EVENT
# =========================================================

async def validate_event_variant(
    event,
):

    if not event:

        return ShopifyVariantValidation(

            checked=False,

            valid=False,

            available=False,

            variant_id=None,

            variant_title=None,

            price=None,

            product_title=None,

            http_status=None,

            reason="EVENT_MISSING",

            product_json_url=None,
        )


    source_type = (
        str(
            event.get(
                "source_type"
            )
            or ""
        )
        .strip()
        .lower()
    )


    # =====================================================
    # SHOPIFY ONLY
    #
    # Target/Walmart/etc will get their own validation
    # strategies later.
    # =====================================================

    if source_type != "shopify":

        return ShopifyVariantValidation(

            checked=False,

            valid=False,

            available=False,

            variant_id=(
                normalize_variant_id(
                    event.get(
                        "variant_id"
                    )
                )
            ),

            variant_title=None,

            price=None,

            product_title=None,

            http_status=None,

            reason=(
                "SOURCE_NOT_SHOPIFY"
            ),

            product_json_url=None,
        )


    return (
        await validate_shopify_variant(

            product_url=(
                event.get(
                    "product_url"
                )
            ),

            variant_id=(
                event.get(
                    "variant_id"
                )
            ),
        )
    )


# =========================================================
# DEBUG SUMMARY
# =========================================================

def variant_validation_summary(
    result,
):

    if result is None:

        return (
            "VariantValidation(None)"
        )


    return (
        "VariantValidation("
        f"checked={result.checked}, "
        f"valid={result.valid}, "
        f"available={result.available}, "
        f"variant={result.variant_id}, "
        f"http={result.http_status}, "
        f"reason={result.reason}"
        ")"
    )