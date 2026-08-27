from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import select

from app.models import PricingReference


# =========================================================
# LOTUS PRICING REFERENCE
# PonDeX Trackers
# Version 1.0.1
#
# MSRP Hierarchy
#
# 1. Adapter-provided verified MSRP
# 2. Exact product MSRP
# 3. Product-type MSRP
# 4. Game-default MSRP
# 5. No MSRP
#
# Shopify compare_at_price is NOT trusted as MSRP.
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
# INTERNAL STORAGE KEY
#
# normalized_name remains the unique lookup key so we do
# not need to replace the existing pricing-reference table.
# =========================================================

def build_reference_key(
    *,
    scope_type,
    match_value=None,
):

    scope = (
        normalize_scope_type(
            scope_type
        )
    )

    if (
        scope
        == "GAME_DEFAULT"
    ):

        return (
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
            "scope product type "
            + normalized_match
        )

    return (
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
):

    scope = (
        normalize_scope_type(
            scope_type
        )
    )

    if (
        scope
        == "GAME_DEFAULT"
    ):

        return (
            f"{game} Default MSRP"
        )

    return (
        str(
            match_value
            or ""
        ).strip()
    )


# =========================================================
# SET / UPDATE REFERENCE
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

    normalized_key = (
        build_reference_key(

            scope_type=(
                scope_value
            ),

            match_value=(
                match_value
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

        row = PricingReference(

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

            active=True,
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

        row.active = True

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
):

    game_value = (
        str(
            game
            or ""
        ).strip()
    )

    if not game_value:

        return None

    normalized_key = (
        build_reference_key(

            scope_type=(
                scope_type
            ),

            match_value=(
                match_value
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

    # -----------------------------------------------------
    # Region-specific rule missing:
    # fall back to GLOBAL.
    # -----------------------------------------------------

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
#
# Soft delete preserves history.
# =========================================================

async def remove_pricing_reference(
    session,
    *,
    game,
    scope_type="EXACT_PRODUCT",
    match_value=None,
    region="GLOBAL",
    kind="MSRP",
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
# DATABASE ROW -> REFERENCE PRICE
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
    )


# =========================================================
# RESOLVE REFERENCE PRICE
# =========================================================

async def resolve_reference_price(
    session,
    item,
    *,
    game=None,
    region=None,
):

    """
    Resolution order:

    1. Verified adapter MSRP
    2. Exact product MSRP
    3. Product-type MSRP
    4. Game-default MSRP
    5. None
    """

    if item is None:

        return None


    # =====================================================
    # 1. ADAPTER-PROVIDED VERIFIED MSRP
    # =====================================================

    explicit_msrp = (
        _safe_positive_float(
            item.get(
                "msrp"
            )
        )
    )

    if explicit_msrp is not None:

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

            scope_type=(
                "EXACT_PRODUCT"
            ),

            match_value=(
                item.get(
                    "title"
                )
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


    # =====================================================
    # 2. EXACT PRODUCT
    # =====================================================

    if product_name:

        row = (
            await get_pricing_reference(

                session,

                game=(
                    game_value
                ),

                scope_type=(
                    "EXACT_PRODUCT"
                ),

                match_value=(
                    product_name
                ),

                region=(
                    region_value
                ),

                kind="MSRP",
            )
        )

        if row is not None:

            print(
                (
                    "MSRP MATCH | "
                    "Scope=EXACT_PRODUCT | "
                    f"Game={game_value} | "
                    f"Product={product_name}"
                )
            )

            return (
                _row_to_reference(
                    row
                )
            )


    # =====================================================
    # 3. PRODUCT TYPE
    # =====================================================

    if product_type:

        row = (
            await get_pricing_reference(

                session,

                game=(
                    game_value
                ),

                scope_type=(
                    "PRODUCT_TYPE"
                ),

                match_value=(
                    product_type
                ),

                region=(
                    region_value
                ),

                kind="MSRP",
            )
        )

        if row is not None:

            print(
                (
                    "MSRP MATCH | "
                    "Scope=PRODUCT_TYPE | "
                    f"Game={game_value} | "
                    f"Type={product_type}"
                )
            )

            return (
                _row_to_reference(
                    row
                )
            )


    # =====================================================
    # 4. GAME DEFAULT
    # =====================================================

    row = (
        await get_pricing_reference(

            session,

            game=(
                game_value
            ),

            scope_type=(
                "GAME_DEFAULT"
            ),

            match_value=None,

            region=(
                region_value
            ),

            kind="MSRP",
        )
    )

    if row is not None:

        print(
            (
                "MSRP MATCH | "
                "Scope=GAME_DEFAULT | "
                f"Game={game_value}"
            )
        )

        return (
            _row_to_reference(
                row
            )
        )


    # =====================================================
    # NO TRUSTED REFERENCE
    # =====================================================

    return None