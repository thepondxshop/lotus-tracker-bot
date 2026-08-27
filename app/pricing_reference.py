from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import select

from app.models import PricingReference


# =========================================================
# LOTUS PRICING REFERENCE
# PonDeX Trackers
# Version 1.0.0
#
# Persistent MSRP / Reference Price Intelligence
# =========================================================


@dataclass
class ReferencePrice:
    amount: float
    currency: str
    source: str
    confidence: str = "HIGH"
    kind: str = "MSRP"
    region: str = "GLOBAL"


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_reference_text(value):

    if value is None:
        return ""

    text = str(value).lower()

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


def normalize_game(value):

    return normalize_reference_text(
        value
    )


def normalize_region(value):

    value = (
        str(
            value
            or "GLOBAL"
        )
        .strip()
        .upper()
    )

    if not value:
        return "GLOBAL"

    return value


def normalize_currency(value):

    value = (
        str(
            value
            or "USD"
        )
        .strip()
        .upper()
    )

    if not value:
        return "USD"

    return value


def normalize_confidence(value):

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


def normalize_kind(value):

    value = (
        str(
            value
            or "MSRP"
        )
        .strip()
        .upper()
    )

    if not value:
        return "MSRP"

    return value


def _safe_positive_float(value):

    if value is None:
        return None

    try:
        result = float(value)

    except (
        TypeError,
        ValueError,
    ):
        return None

    if result <= 0:
        return None

    return result


# =========================================================
# CREATE / UPDATE REFERENCE
# =========================================================

async def set_pricing_reference(
    session,
    *,
    game,
    product_name,
    amount,
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

    normalized_name = (
        normalize_reference_text(
            product_name
        )
    )

    if not normalized_name:

        raise ValueError(
            "Product name is required."
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
                == normalized_name
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

            game=game_value,

            product_name=(
                product_name.strip()
            ),

            normalized_name=(
                normalized_name
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

            active=True,
        )

        session.add(
            row
        )

        created = True

    else:

        row.product_name = (
            product_name.strip()
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
# GET EXACT REFERENCE
# =========================================================

async def get_pricing_reference(
    session,
    *,
    game,
    product_name,
    region="GLOBAL",
    kind="MSRP",
):

    normalized_name = (
        normalize_reference_text(
            product_name
        )
    )

    if not normalized_name:
        return None

    game_value = (
        str(
            game
            or ""
        ).strip()
    )

    if not game_value:
        return None

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

    # =====================================================
    # FIRST TRY EXACT REGION
    # =====================================================

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
                == normalized_name
            )
            .where(
                PricingReference.region
                == region_value
            )
            .where(
                PricingReference.kind
                == kind_value
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

    row = (
        result.scalars().first()
    )

    if row is not None:
        return row

    # =====================================================
    # FALL BACK TO GLOBAL REFERENCE
    # =====================================================

    if region_value != "GLOBAL":

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
                    == normalized_name
                )
                .where(
                    PricingReference.region
                    == "GLOBAL"
                )
                .where(
                    PricingReference.kind
                    == kind_value
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

        row = (
            result.scalars().first()
        )

    return row


# =========================================================
# REMOVE REFERENCE
#
# Soft delete keeps historical/admin information intact.
# =========================================================

async def remove_pricing_reference(
    session,
    *,
    game,
    product_name,
    region="GLOBAL",
    kind="MSRP",
):

    row = (
        await get_pricing_reference(

            session,

            game=game,

            product_name=product_name,

            region=region,

            kind=kind,
        )
    )

    if row is None:
        return None

    row.active = False

    row.updated_at = (
        datetime.utcnow()
    )

    await session.commit()

    await session.refresh(
        row
    )

    return row


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
    Resolve a trustworthy MSRP/reference price.

    Priority:

    1. Explicit verified MSRP supplied by an adapter.
    2. Persistent PostgreSQL pricing reference.
    3. No reference.

    IMPORTANT:
    Shopify compare_at_price is deliberately NOT treated
    as MSRP because retailers control that value.
    """

    if item is None:
        return None

    # =====================================================
    # ADAPTER-PROVIDED VERIFIED MSRP
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
        )

    # =====================================================
    # DATABASE REFERENCE
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

    row = (
        await get_pricing_reference(

            session,

            game=(
                game_value
            ),

            product_name=(
                product_name
            ),

            region=(
                region_value
            ),

            kind="MSRP",
        )
    )

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
    )