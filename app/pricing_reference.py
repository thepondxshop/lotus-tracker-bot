from dataclasses import dataclass
import re


# =========================================================
# LOTUS PRICING REFERENCE
# PonDeX Trackers
# Version 1.0.0
#
# MSRP Intelligence + Scalper Protection v1
# =========================================================


@dataclass
class ReferencePrice:
    amount: float
    currency: str
    source: str
    confidence: str = "HIGH"
    kind: str = "MSRP"


# =========================================================
# MANUAL / VERIFIED MSRP CATALOG
#
# Keep this conservative.
# Only add prices that are known and verified.
#
# Key format:
#   normalized_game|normalized_product_title
#
# Value format:
#   {
#       "amount": 109.99,
#       "currency": "USD",
#       "source": "Official MSRP",
#       "confidence": "HIGH",
#       "kind": "MSRP",
#   }
#
# This catalog is intentionally empty by default so Lotus
# never invents an MSRP.
# =========================================================

REFERENCE_PRICE_CATALOG = {
    # Example:
    #
    # "one piece|example booster box": {
    #     "amount": 107.76,
    #     "currency": "USD",
    #     "source": "Official MSRP",
    #     "confidence": "HIGH",
    #     "kind": "MSRP",
    # },
}


def normalize_reference_text(
    value,
):
    if value is None:
        return ""

    text = str(
        value
    ).lower()

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


def _build_catalog_key(
    game,
    product_name,
):
    return (
        f"{normalize_reference_text(game)}|"
        f"{normalize_reference_text(product_name)}"
    )


def _reference_from_mapping(
    mapping,
):
    if not mapping:
        return None

    amount = (
        _safe_positive_float(
            mapping.get(
                "amount"
            )
        )
    )

    if amount is None:
        return None

    currency = (
        str(
            mapping.get(
                "currency",
                "USD",
            )
        )
        .upper()
        .strip()
    )

    source = (
        str(
            mapping.get(
                "source",
                "Verified Reference",
            )
        )
        .strip()
    )

    confidence = (
        str(
            mapping.get(
                "confidence",
                "HIGH",
            )
        )
        .upper()
        .strip()
    )

    kind = (
        str(
            mapping.get(
                "kind",
                "MSRP",
            )
        )
        .upper()
        .strip()
    )

    return ReferencePrice(
        amount=amount,
        currency=currency,
        source=source,
        confidence=confidence,
        kind=kind,
    )


def resolve_reference_price(
    item,
    *,
    game=None,
):
    """
    Resolve a trustworthy MSRP/reference price.

    Priority:

    1. Explicit normalized MSRP data supplied by an adapter.
    2. Verified manual catalog entry.
    3. None.

    Lotus deliberately does NOT treat Shopify compare-at price
    as MSRP because compare-at prices can be arbitrary retailer
    marketing values.
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

        explicit_currency = (
            str(
                item.get(
                    "msrp_currency"
                )
                or item.get(
                    "currency"
                )
                or "USD"
            )
            .upper()
            .strip()
        )

        explicit_source = (
            str(
                item.get(
                    "msrp_source"
                )
                or "Retailer/Adapter MSRP"
            )
            .strip()
        )

        explicit_confidence = (
            str(
                item.get(
                    "msrp_confidence"
                )
                or "MEDIUM"
            )
            .upper()
            .strip()
        )

        return ReferencePrice(
            amount=explicit_msrp,
            currency=explicit_currency,
            source=explicit_source,
            confidence=explicit_confidence,
            kind="MSRP",
        )

    # =====================================================
    # VERIFIED CATALOG
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

    key = (
        _build_catalog_key(
            game_value,
            product_name,
        )
    )

    mapping = (
        REFERENCE_PRICE_CATALOG.get(
            key
        )
    )

    return (
        _reference_from_mapping(
            mapping
        )
    )
