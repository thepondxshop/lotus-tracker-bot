from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import select

from app.models import PricingReference

from app.product_family import (
    allows_global_msrp_fallback,
    detect_product_family,
    normalize_product_family,
)


# =========================================================
# LOTUS PRICING REFERENCE
# PonDeX Trackers
# Version 1.0.2
#
# MSRP hierarchy:
#
# Adapter Verified MSRP
#
# then:
#
# Exact Product
# Product Type
# Game Default
#
# Product-family isolation:
#
# GLOBAL_STANDARD
# JP
# KR
# CN
# UNKNOWN
#
# JP / KR / CN never fall back to GLOBAL_STANDARD MSRP.
# =========================================================


@dataclass
class ReferencePrice:

    amount: float

    currency: str

    source: str

    confidence: str = "HIGH"

    kind: str = "MSRP"

    region: str = "GLOBAL"

    scope_type: str = "EXACT_PRODUCT"

    match_value: str | None = None

    product_family: str = "GLOBAL_STANDARD"


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_reference_text(
    value,
):

    if value is None:

        return ""

    text = (
        str(
            value
        )
        .lower()
        .strip()
    )

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_region(
    value,
):

    value = (
        str(
            value
            or "GLOBAL"
        )
        .strip()
        .upper()
    )

    return (
        value
        or "GLOBAL"
    )


def normalize_currency(
    value,
):

    value = (
        str(
            value
            or "USD"
        )
        .strip()
        .upper()
    )

    return (
        value
        or "USD"
    )


def normalize_confidence(
    value,
):

    value = (
        str(
            value
            or "HIGH"
        )
        .strip()
        .upper()
    )

    if value not in {
        "LOW",
        "MEDIUM",
        "HIGH",
    }:

        return "HIGH"

    return value


def normalize_kind(
    value,
):

    value = (
        str(
            value
            or "MSRP"
        )
        .strip()
        .upper()
    )

    return (
        value
        or "MSRP"
    )


def normalize_scope_type(
    value,
):

    value = (
        str(
            value
            or "EXACT_PRODUCT"
        )
        .strip()
        .upper()
    )


    aliases = {

        "EXACT":
            "EXACT_PRODUCT",

        "PRODUCT":
            "EXACT_PRODUCT",

        "TYPE":
            "PRODUCT_TYPE",

        "CATEGORY":
            "PRODUCT_TYPE",

        "GAME":
            "GAME_DEFAULT",

        "DEFAULT":
            "GAME_DEFAULT",
    }


    value = (
        aliases.get(
            value,
            value,
        )
    )


    if value not in {
        "EXACT_PRODUCT",
        "PRODUCT_TYPE",
        "GAME_DEFAULT",
    }:

        raise ValueError(
            (
                "Invalid MSRP scope. "
                "Use EXACT_PRODUCT, PRODUCT_TYPE, "
                "or GAME_DEFAULT."
            )
        )


    return value


def _safe_positive_float(
    value,
):

    if value is None:

        return None


    try:

        result = float(
            value
        )


    except (
        TypeError,
        ValueError,
    ):

        return None


    if result <= 0:

        return None


    return result


# =========================================================
# FAMILY
# =========================================================

def require_product_family(
    value,
):

    family = (
        normalize_product_family(
            value
        )
    )


    if family is None:

        raise ValueError(
            (
                "Invalid product family. "
                "Use GLOBAL_STANDARD, JP, KR, CN, "
                "or UNKNOWN."
            )
        )


    return family


# =========================================================
# INTERNAL STORAGE KEY
#
# Family is included in normalized_name so separate
# references can safely exist for:
#
# GLOBAL_STANDARD Booster Box
# JP Booster Box
# KR Booster Box
# CN Booster Box
# =========================================================

def build_reference_key(
    *,
    scope_type,
    match_value=None,
    product_family="GLOBAL_STANDARD",
):

    scope = (
        normalize_scope_type(
            scope_type
        )
    )


    family = (
        require_product_family(
            product_family
        )
    )


    family_key = (
        family.lower()
    )


    if (
        scope
        == "GAME_DEFAULT"
    ):

        return (
            f"family {family_key} "
            "scope game default"
        )


    normalized_match = (
        normalize_reference_text(
            match_value
        )
    )


    if not normalized_match:

        raise ValueError(
            (
                "A match value is required for "
                "Exact Product and Product Type rules."
            )
        )


    if (
        scope
        == "PRODUCT_TYPE"
    ):

        return (
            f"family {family_key} "
            "scope product type "
            + normalized_match
        )


    return (
        f"family {family_key} "
        "scope exact product "
        + normalized_match
    )


# =========================================================
# DISPLAY NAME
# =========================================================

def build_display_name(
    *,
    scope_type,
    match_value,
    game,
    product_family,
):

    scope = (
        normalize_scope_type(
            scope_type
        )
    )


    family = (
        require_product_family(
            product_family
        )
    )


    if (
        scope
        == "GAME_DEFAULT"
    ):

        return (
            f"{game} {family} Default MSRP"
        )


    return (
        str(
            match_value
            or ""
        ).strip()
    )


# =========================================================
# SET REFERENCE
# =========================================================

async def set_pricing_reference(
    session,
    *,
    game,
    amount,
    scope_type="EXACT_PRODUCT",
    match_value=None,
    currency="USD",
    source="Verified MSRP",
    confidence="HIGH",
    kind="MSRP",
    region="GLOBAL",
    product_family="GLOBAL_STANDARD",
):

    parsed_amount = (
        _safe_positive_float(
            amount
        )
    )


    if parsed_amount is None:

        raise ValueError(
            "Reference amount must be greater than 0."
        )


    game_value = (
        str(
            game
            or ""
        ).strip()
    )


    if not game_value:

        raise ValueError(
            "Game is required."
        )


    scope_value = (
        normalize_scope_type(
            scope_type
        )
    )


    family_value = (
        require_product_family(
            product_family
        )
    )


    normalized_key = (
        build_reference_key(

            scope_type=(
                scope_value
            ),

            match_value=(
                match_value
            ),

            product_family=(
                family_value
            ),
        )
    )


    display_name = (
        build_display_name(

            scope_type=(
                scope_value
            ),

            match_value=(
                match_value
            ),

            game=(
                game_value
            ),

            product_family=(
                family_value
            ),
        )
    )


    region_value = (
        normalize_region(
            region
        )
    )


    kind_value = (
        normalize_kind(
            kind
        )
    )


    result = (
        await session.execute(

            select(
                PricingReference
            )
            .where(
                PricingReference.game
                == game_value
            )
            .where(
                PricingReference.normalized_name
                == normalized_key
            )
            .where(
                PricingReference.region
                == region_value
            )
            .where(
                PricingReference.kind
                == kind_value
            )
        )
    )


    row = (
        result.scalars().first()
    )


    created = False


    if row is None:

        row = (
            PricingReference(

                game=(
                    game_value
                ),

                product_name=(
                    display_name
                ),

                normalized_name=(
                    normalized_key
                ),

                amount=(
                    parsed_amount
                ),

                currency=(
                    normalize_currency(
                        currency
                    )
                ),

                source=(
                    str(
                        source
                        or "Verified MSRP"
                    ).strip()
                ),

                confidence=(
                    normalize_confidence(
                        confidence
                    )
                ),

                kind=(
                    kind_value
                ),

                region=(
                    region_value
                ),

                scope_type=(
                    scope_value
                ),

                match_value=(

                    None

                    if (
                        scope_value
                        == "GAME_DEFAULT"
                    )

                    else (
                        str(
                            match_value
                            or ""
                        ).strip()
                    )
                ),

                product_family=(
                    family_value
                ),

                active=True,
            )
        )


        session.add(
            row
        )


        created = True


    else:

        row.product_name = (
            display_name
        )


        row.amount = (
            parsed_amount
        )


        row.currency = (
            normalize_currency(
                currency
            )
        )


        row.source = (
            str(
                source
                or "Verified MSRP"
            ).strip()
        )


        row.confidence = (
            normalize_confidence(
                confidence
            )
        )


        row.scope_type = (
            scope_value
        )


        row.match_value = (

            None

            if (
                scope_value
                == "GAME_DEFAULT"
            )

            else (
                str(
                    match_value
                    or ""
                ).strip()
            )
        )


        row.product_family = (
            family_value
        )


        row.active = (
            True
        )


        row.updated_at = (
            datetime.utcnow()
        )


    await session.commit()


    await session.refresh(
        row
    )


    return (
        row,
        created,
    )


# =========================================================
# INTERNAL LOOKUP
# =========================================================

async def _get_reference_by_key(
    session,
    *,
    game,
    normalized_key,
    region,
    kind,
):

    result = (
        await session.execute(

            select(
                PricingReference
            )
            .where(
                PricingReference.game
                == game
            )
            .where(
                PricingReference.normalized_name
                == normalized_key
            )
            .where(
                PricingReference.region
                == region
            )
            .where(
                PricingReference.kind
                == kind
            )
            .where(
                PricingReference.active
                == True
            )
            .order_by(
                PricingReference.id.desc()
            )
        )
    )


    return (
        result.scalars().first()
    )


# =========================================================
# ADMIN LOOKUP
# =========================================================

async def get_pricing_reference(
    session,
    *,
    game,
    scope_type="EXACT_PRODUCT",
    match_value=None,
    region="GLOBAL",
    kind="MSRP",
    product_family="GLOBAL_STANDARD",
):

    game_value = (
        str(
            game
            or ""
        ).strip()
    )


    if not game_value:

        return None


    family_value = (
        require_product_family(
            product_family
        )
    )


    normalized_key = (
        build_reference_key(

            scope_type=(
                scope_type
            ),

            match_value=(
                match_value
            ),

            product_family=(
                family_value
            ),
        )
    )


    region_value = (
        normalize_region(
            region
        )
    )


    kind_value = (
        normalize_kind(
            kind
        )
    )


    row = (
        await _get_reference_by_key(

            session,

            game=(
                game_value
            ),

            normalized_key=(
                normalized_key
            ),

            region=(
                region_value
            ),

            kind=(
                kind_value
            ),
        )
    )


    # =====================================================
    # SAME PRODUCT FAMILY, GLOBAL REGION FALLBACK
    #
    # This is NOT a product-family fallback.
    #
    # Example:
    #
    # JP + US region lookup
    #
    # may fall back to:
    #
    # JP + GLOBAL region
    #
    # but NEVER to GLOBAL_STANDARD.
    # =====================================================

    if (
        row is None
        and region_value != "GLOBAL"
    ):

        row = (
            await _get_reference_by_key(

                session,

                game=(
                    game_value
                ),

                normalized_key=(
                    normalized_key
                ),

                region="GLOBAL",

                kind=(
                    kind_value
                ),
            )
        )


    return row


# =========================================================
# REMOVE REFERENCE
# =========================================================

async def remove_pricing_reference(
    session,
    *,
    game,
    scope_type="EXACT_PRODUCT",
    match_value=None,
    region="GLOBAL",
    kind="MSRP",
    product_family="GLOBAL_STANDARD",
):

    row = (
        await get_pricing_reference(

            session,

            game=(
                game
            ),

            scope_type=(
                scope_type
            ),

            match_value=(
                match_value
            ),

            region=(
                region
            ),

            kind=(
                kind
            ),

            product_family=(
                product_family
            ),
        )
    )


    if row is None:

        return None


    row.active = (
        False
    )


    row.updated_at = (
        datetime.utcnow()
    )


    await session.commit()


    await session.refresh(
        row
    )


    return row


# =========================================================
# ROW -> REFERENCE
# =========================================================

def _row_to_reference(
    row,
):

    if row is None:

        return None


    return ReferencePrice(

        amount=(
            float(
                row.amount
            )
        ),

        currency=(
            normalize_currency(
                row.currency
            )
        ),

        source=(
            row.source
        ),

        confidence=(
            normalize_confidence(
                row.confidence
            )
        ),

        kind=(
            normalize_kind(
                row.kind
            )
        ),

        region=(
            normalize_region(
                row.region
            )
        ),

        scope_type=(
            normalize_scope_type(

                row.scope_type
                or "EXACT_PRODUCT"
            )
        ),

        match_value=(
            row.match_value
        ),

        product_family=(
            require_product_family(

                row.product_family
                or "GLOBAL_STANDARD"
            )
        ),
    )


# =========================================================
# RESOLVE REFERENCE
# =========================================================

async def resolve_reference_price(
    session,
    item,
    *,
    game=None,
    region=None,
    product_family=None,
):

    """
    Product-family-safe MSRP resolution.

    Product family is determined from the actual item.

    JP / KR / CN / UNKNOWN never inherit
    GLOBAL_STANDARD rules.
    """


    if item is None:

        return None


    # =====================================================
    # PRODUCT FAMILY
    # =====================================================

    family_value = (

        normalize_product_family(
            product_family
        )

        or

        detect_product_family(
            item
        )

        or

        "UNKNOWN"
    )


    # =====================================================
    # VERIFIED ADAPTER MSRP
    # =====================================================

    explicit_msrp = (
        _safe_positive_float(
            item.get(
                "msrp"
            )
        )
    )


    if explicit_msrp is not None:

        explicit_family = (

            normalize_product_family(

                item.get(
                    "msrp_product_family"
                )
            )

            or family_value
        )


        return ReferencePrice(

            amount=(
                explicit_msrp
            ),

            currency=(
                normalize_currency(

                    item.get(
                        "msrp_currency"
                    )

                    or item.get(
                        "currency"
                    )

                    or "USD"
                )
            ),

            source=(
                str(

                    item.get(
                        "msrp_source"
                    )

                    or "Verified Adapter MSRP"
                ).strip()
            ),

            confidence=(
                normalize_confidence(

                    item.get(
                        "msrp_confidence"
                    )

                    or "MEDIUM"
                )
            ),

            kind="MSRP",

            region=(
                normalize_region(

                    region

                    or item.get(
                        "region"
                    )

                    or "GLOBAL"
                )
            ),

            scope_type="EXACT_PRODUCT",

            match_value=(
                item.get(
                    "title"
                )
            ),

            product_family=(
                explicit_family
            ),
        )


    # =====================================================
    # PRODUCT DATA
    # =====================================================

    product_name = (

        item.get(
            "title"
        )

        or item.get(
            "product_name"
        )

        or ""
    )


    product_type = (

        item.get(
            "product_type"
        )

        or ""
    )


    game_value = (

        game

        or item.get(
            "game"
        )

        or ""
    )


    region_value = (

        region

        or item.get(
            "region"
        )

        or "GLOBAL"
    )


    if not game_value:

        return None


    # =====================================================
    # SAFE FAMILY RESOLUTION
    # =====================================================

    lookup_families = [
        family_value
    ]


    # GLOBAL_STANDARD is already its own family.
    #
    # JP/KR/CN/UNKNOWN intentionally receive no additional
    # family fallback.

    if (
        family_value
        == "GLOBAL_STANDARD"

        and

        allows_global_msrp_fallback(
            family_value
        )
    ):

        lookup_families = [
            "GLOBAL_STANDARD"
        ]


    # =====================================================
    # EACH PERMITTED FAMILY
    # =====================================================

    for lookup_family in lookup_families:


        # =================================================
        # 1. EXACT PRODUCT
        # =================================================

        if product_name:

            row = (
                await get_pricing_reference(

                    session,

                    game=(
                        game_value
                    ),

                    scope_type="EXACT_PRODUCT",

                    match_value=(
                        product_name
                    ),

                    region=(
                        region_value
                    ),

                    kind="MSRP",

                    product_family=(
                        lookup_family
                    ),
                )
            )


            if row is not None:

                print(
                    (
                        "MSRP MATCH | "
                        "Scope=EXACT_PRODUCT | "
                        f"Family={lookup_family} | "
                        f"Game={game_value} | "
                        f"Product={product_name}"
                    )
                )


                return (
                    _row_to_reference(
                        row
                    )
                )


        # =================================================
        # 2. PRODUCT TYPE
        # =================================================

        if product_type:

            row = (
                await get_pricing_reference(

                    session,

                    game=(
                        game_value
                    ),

                    scope_type="PRODUCT_TYPE",

                    match_value=(
                        product_type
                    ),

                    region=(
                        region_value
                    ),

                    kind="MSRP",

                    product_family=(
                        lookup_family
                    ),
                )
            )


            if row is not None:

                print(
                    (
                        "MSRP MATCH | "
                        "Scope=PRODUCT_TYPE | "
                        f"Family={lookup_family} | "
                        f"Game={game_value} | "
                        f"Type={product_type}"
                    )
                )


                return (
                    _row_to_reference(
                        row
                    )
                )


        # =================================================
        # 3. GAME DEFAULT
        # =================================================

        row = (
            await get_pricing_reference(

                session,

                game=(
                    game_value
                ),

                scope_type="GAME_DEFAULT",

                match_value=None,

                region=(
                    region_value
                ),

                kind="MSRP",

                product_family=(
                    lookup_family
                ),
            )
        )


        if row is not None:

            print(
                (
                    "MSRP MATCH | "
                    "Scope=GAME_DEFAULT | "
                    f"Family={lookup_family} | "
                    f"Game={game_value}"
                )
            )


            return (
                _row_to_reference(
                    row
                )
            )


    # =====================================================
    # NO SAFE REFERENCE
    # =====================================================

    print(
        (
            "MSRP NO SAFE MATCH | "
            f"Family={family_value} | "
            f"Game={game_value} | "
            f"Product={product_name} | "
            f"Type={product_type}"
        )
    )


    return None