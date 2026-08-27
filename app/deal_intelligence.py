from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import select

from app.currency_service import (
    convert_currency,
)

from app.models import (
    PriceHistory,
)


# =========================================================
# LOTUS DEAL INTELLIGENCE
# PonDeX Trackers
# Version 1.0.0
#
# Historical Pricing
# MSRP Intelligence
# Cross-Currency Reference Pricing
# Scalper Protection v1
# Deal Score v2
# =========================================================


@dataclass
class DealIntelligence:

    window_days: int = 30

    # =====================================================
    # HISTORICAL PRICING
    # =====================================================

    low: float | None = None

    average: float | None = None

    high: float | None = None

    sample_count: int = 0

    vs_average_pct: float | None = None

    vs_low_pct: float | None = None

    price_drop_pct: float | None = None

    historical_deal_score: float | None = None


    # =====================================================
    # MSRP / REFERENCE INTELLIGENCE
    #
    # msrp:
    # Reference amount converted into the CURRENT STORE'S
    # currency for correct comparison.
    #
    # msrp_original_*:
    # Preserves the verified source/reference currency.
    # =====================================================

    msrp: float | None = None

    msrp_currency: str | None = None

    msrp_source: str | None = None

    msrp_confidence: str | None = None

    msrp_original: float | None = None

    msrp_original_currency: str | None = None

    msrp_conversion_used: bool = False


    # =====================================================
    # MSRP COMPARISON
    # =====================================================

    vs_msrp_pct: float | None = None

    markup_amount: float | None = None

    msrp_price_state: str | None = None

    scalper_risk: str | None = None


    # =====================================================
    # FINAL DEAL INTELLIGENCE
    # =====================================================

    deal_score: float | None = None

    deal_label: str | None = None

    deal_confidence: str | None = None


    # =====================================================
    # EVENT SERIALIZATION
    # =====================================================

    def to_event_fields(
        self,
    ):

        return {

            "price_window_days":
                self.window_days,

            "price_30d_low":
                self.low,

            "price_30d_average":
                self.average,

            "price_30d_high":
                self.high,

            "price_history_samples":
                self.sample_count,

            "price_vs_average_pct":
                self.vs_average_pct,

            "price_vs_low_pct":
                self.vs_low_pct,

            "price_drop_pct":
                self.price_drop_pct,

            "historical_deal_score":
                self.historical_deal_score,


            # =================================================
            # MSRP
            # =================================================

            "msrp":
                self.msrp,

            "msrp_currency":
                self.msrp_currency,

            "msrp_source":
                self.msrp_source,

            "msrp_confidence":
                self.msrp_confidence,

            "msrp_original":
                self.msrp_original,

            "msrp_original_currency":
                self.msrp_original_currency,

            "msrp_conversion_used":
                self.msrp_conversion_used,


            # =================================================
            # MSRP ANALYSIS
            # =================================================

            "price_vs_msrp_pct":
                self.vs_msrp_pct,

            "markup_amount":
                self.markup_amount,

            "msrp_price_state":
                self.msrp_price_state,

            "scalper_risk":
                self.scalper_risk,


            # =================================================
            # DEAL SCORE
            # =================================================

            "deal_score":
                self.deal_score,

            "deal_label":
                self.deal_label,

            "deal_confidence":
                self.deal_confidence,
        }


# =========================================================
# SAFE FLOAT
# =========================================================

def _safe_float(
    value,
):

    if value is None:

        return None


    try:

        number = float(
            value
        )


    except (
        TypeError,
        ValueError,
    ):

        return None


    if number <= 0:

        return None


    return number


# =========================================================
# CLAMP
# =========================================================

def _clamp(
    value,
    minimum,
    maximum,
):

    return max(

        minimum,

        min(
            maximum,
            value,
        ),
    )


# =========================================================
# CURRENCY
# =========================================================

def _normalize_currency(
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


    if not value:

        return "USD"


    return value


# =========================================================
# HISTORY CONFIDENCE
# =========================================================

def _history_confidence(
    sample_count,
):

    if sample_count >= 6:

        return "HIGH"


    if sample_count >= 3:

        return "MEDIUM"


    return "LOW"


def _history_confidence_component(
    confidence,
):

    if confidence == "HIGH":

        return 1.0


    if confidence == "MEDIUM":

        return 0.65


    return 0.30


# =========================================================
# REFERENCE STRENGTH
# =========================================================

def _reference_strength(
    confidence,
):

    value = (

        str(
            confidence
            or ""
        )

        .upper()

        .strip()
    )


    if value == "HIGH":

        return 1.0


    if value == "MEDIUM":

        return 0.65


    if value == "LOW":

        return 0.35


    return 0.0


# =========================================================
# HISTORICAL LABEL
# =========================================================

def _historical_label(
    score,
    current_price,
    average_price,
):

    if (

        average_price is not None

        and

        current_price > average_price

        and

        score < 4.5

    ):

        return "Above Average"


    if score >= 8.0:

        return "Excellent Deal"


    if score >= 6.5:

        return "Good Deal"


    if score >= 4.5:

        return "Fair Price"


    if (

        average_price is not None

        and

        current_price > average_price

    ):

        return "Above Average"


    return "Normal Price"


# =========================================================
# FINAL LABEL
# =========================================================

def _final_label(
    score,
    scalper_risk=None,
):

    risk = (

        str(
            scalper_risk
            or ""
        )

        .upper()
    )


    if risk == "EXTREME":

        return "Extreme Markup"


    if risk == "HIGH":

        return "High Markup"


    if risk == "MODERATE":

        if score < 6.5:

            return "Marked Up"


    if score >= 8.0:

        return "Excellent Deal"


    if score >= 6.5:

        return "Good Deal"


    if score >= 4.5:

        return "Fair Price"


    return "Above Average"


# =========================================================
# HISTORICAL DEAL SCORE
# =========================================================

def calculate_historical_score(
    *,
    current_price,
    average_price,
    low_price,
    old_price=None,
    sample_count=0,
):

    """
    Historical Deal Score — 0.0 to 10.0

    Weighting:

    40% discount vs 30-day average
    30% proximity to 30-day low
    20% current price-drop size
    10% history confidence
    """


    current = (
        _safe_float(
            current_price
        )
    )


    average = (
        _safe_float(
            average_price
        )
    )


    low = (
        _safe_float(
            low_price
        )
    )


    old = (
        _safe_float(
            old_price
        )
    )


    if current is None:

        return (

            None,

            None,

            None,

            None,

            None,
        )


    # =====================================================
    # VS 30-DAY AVERAGE
    # =====================================================

    vs_average_pct = None

    average_component = 0.0


    if average is not None:

        vs_average_pct = (

            (
                current
                - average
            )

            / average

        ) * 100


        discount_vs_average = max(

            0.0,

            -vs_average_pct,
        )


        average_component = (

            _clamp(

                discount_vs_average
                / 25.0,

                0.0,

                1.0,
            )

            * 4.0
        )


    # =====================================================
    # VS 30-DAY LOW
    # =====================================================

    vs_low_pct = None

    low_component = 0.0


    if low is not None:

        vs_low_pct = (

            (
                current
                - low
            )

            / low

        ) * 100


        proximity = (

            1.0

            - (

                max(
                    0.0,
                    vs_low_pct,
                )

                / 20.0
            )
        )


        low_component = (

            _clamp(

                proximity,

                0.0,

                1.0,
            )

            * 3.0
        )


    # =====================================================
    # CURRENT PRICE DROP
    # =====================================================

    price_drop_pct = None

    drop_component = 0.0


    if (

        old is not None

        and

        current < old

    ):

        price_drop_pct = (

            (
                old
                - current
            )

            / old

        ) * 100


        drop_component = (

            _clamp(

                price_drop_pct
                / 25.0,

                0.0,

                1.0,
            )

            * 2.0
        )


    # =====================================================
    # HISTORY CONFIDENCE
    # =====================================================

    confidence = (
        _history_confidence(
            sample_count
        )
    )


    confidence_component = (
        _history_confidence_component(
            confidence
        )
    )


    # =====================================================
    # FINAL HISTORICAL SCORE
    # =====================================================

    score = round(

        _clamp(

            (
                average_component
                + low_component
                + drop_component
                + confidence_component
            ),

            0.0,

            10.0,
        ),

        1,
    )


    label = (
        _historical_label(

            score,

            current,

            average,
        )
    )


    return (

        score,

        label,

        confidence,

        vs_average_pct,

        vs_low_pct,
    )


# =========================================================
# MSRP ASSESSMENT
# =========================================================

def assess_msrp(
    *,
    current_price,
    msrp,
):

    current = (
        _safe_float(
            current_price
        )
    )


    reference = (
        _safe_float(
            msrp
        )
    )


    if (

        current is None

        or

        reference is None

    ):

        return {

            "vs_msrp_pct":
                None,

            "markup_amount":
                None,

            "price_state":
                None,

            "scalper_risk":
                None,
        }


    difference = (
        current
        - reference
    )


    vs_msrp_pct = (

        difference

        / reference

    ) * 100


    # =====================================================
    # MARKUP AMOUNT
    #
    # Negative differences are intentionally returned as
    # zero markup. Discount percentage is represented by
    # vs_msrp_pct.
    # =====================================================

    markup_amount = max(

        0.0,

        difference,
    )


    # =====================================================
    # MSRP PRICE STATE
    # =====================================================

    if vs_msrp_pct <= -1.0:

        price_state = (
            "BELOW_MSRP"
        )


    elif vs_msrp_pct <= 1.0:

        price_state = (
            "AT_MSRP"
        )


    else:

        price_state = (
            "ABOVE_MSRP"
        )


    # =====================================================
    # SCALPER PROTECTION
    #
    # NONE      <= MSRP
    # LOW       0-10%
    # MODERATE  10-25%
    # HIGH      25-50%
    # EXTREME   50%+
    # =====================================================

    if vs_msrp_pct <= 0:

        scalper_risk = (
            "NONE"
        )


    elif vs_msrp_pct <= 10:

        scalper_risk = (
            "LOW"
        )


    elif vs_msrp_pct <= 25:

        scalper_risk = (
            "MODERATE"
        )


    elif vs_msrp_pct <= 50:

        scalper_risk = (
            "HIGH"
        )


    else:

        scalper_risk = (
            "EXTREME"
        )


    return {

        "vs_msrp_pct":
            round(
                vs_msrp_pct,
                2,
            ),

        "markup_amount":
            round(
                markup_amount,
                4,
            ),

        "price_state":
            price_state,

        "scalper_risk":
            scalper_risk,
    }


# =========================================================
# MSRP-AWARE DEAL SCORE
# =========================================================

def adjust_score_for_msrp(
    *,
    historical_score,
    current_price,
    msrp,
    msrp_confidence,
    scalper_risk,
):

    """
    MSRP-aware Deal Score.

    The historical score remains the foundation.

    Verified MSRP contributes additional value context.

    MSRP confidence determines how much influence the
    reference is allowed to have.

    Scalper risk can penalize overpriced listings.
    """


    base = float(
        historical_score
        or 0.0
    )


    current = (
        _safe_float(
            current_price
        )
    )


    reference = (
        _safe_float(
            msrp
        )
    )


    strength = (
        _reference_strength(
            msrp_confidence
        )
    )


    if (

        current is None

        or

        reference is None

        or

        strength <= 0

    ):

        return round(

            _clamp(

                base,

                0.0,

                10.0,
            ),

            1,
        )


    vs_msrp_pct = (

        (
            current
            - reference
        )

        / reference

    ) * 100


    # =====================================================
    # MSRP VALUE COMPONENT
    #
    # MSRP:
    # approx 2 points
    #
    # 20%+ below MSRP:
    # up to 3 points
    #
    # 25%+ above MSRP:
    # zero MSRP value points
    # =====================================================

    if vs_msrp_pct <= 0:

        msrp_component = (

            2.0

            + (

                _clamp(

                    (
                        -vs_msrp_pct
                    )

                    / 20.0,

                    0.0,

                    1.0,
                )

                * 1.0
            )
        )


    else:

        msrp_component = (

            2.0

            * (

                1.0

                - _clamp(

                    vs_msrp_pct
                    / 25.0,

                    0.0,

                    1.0,
                )
            )
        )


    # =====================================================
    # LOW-CONFIDENCE REFERENCES GET LESS POWER
    # =====================================================

    msrp_component *= (
        strength
    )


    # =====================================================
    # PRESERVE HISTORICAL SCORE
    #
    # HIGH reference:
    # 70% history influence
    #
    # Lower-confidence MSRP:
    # historical data receives more weight.
    # =====================================================

    history_weight = (

        0.70

        + (

            0.30

            * (

                1.0

                - strength
            )
        )
    )


    combined = (

        base
        * history_weight

        + msrp_component
    )


    # =====================================================
    # SCALPER PENALTY
    # =====================================================

    risk = (

        str(
            scalper_risk
            or ""
        )

        .upper()
    )


    penalties = {

        "NONE":
            0.0,

        "LOW":
            0.0,

        "MODERATE":
            0.5,

        "HIGH":
            1.5,

        "EXTREME":
            3.0,
    }


    penalty = (

        penalties.get(
            risk,
            0.0,
        )

        * strength
    )


    return round(

        _clamp(

            combined
            - penalty,

            0.0,

            10.0,
        ),

        1,
    )


# =========================================================
# CONVERT MSRP INTO STORE CURRENCY
# =========================================================

async def convert_reference_to_store_currency(
    *,
    reference_price,
    store_currency,
):

    """
    Returns:

    {
        amount,
        currency,
        original_amount,
        original_currency,
        conversion_used
    }

    The verified reference itself is NEVER overwritten.

    The converted amount exists only for fair comparison
    against the retailer's current native price.
    """


    if reference_price is None:

        return None


    original_amount = (
        _safe_float(
            reference_price.amount
        )
    )


    if original_amount is None:

        return None


    original_currency = (
        _normalize_currency(
            reference_price.currency
        )
    )


    target_currency = (
        _normalize_currency(
            store_currency
        )
    )


    # =====================================================
    # SAME CURRENCY
    # =====================================================

    if (
        original_currency
        == target_currency
    ):

        return {

            "amount":
                original_amount,

            "currency":
                target_currency,

            "original_amount":
                original_amount,

            "original_currency":
                original_currency,

            "conversion_used":
                False,
        }


    # =====================================================
    # CROSS-CURRENCY CONVERSION
    # =====================================================

    try:

        converted = (
            await convert_currency(

                original_amount,

                original_currency,

                target_currency,
            )
        )


    except Exception as error:

        print(
            (
                "MSRP CURRENCY CONVERSION ERROR | "
                f"{original_currency}->"
                f"{target_currency} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return None


    converted = (
        _safe_float(
            converted
        )
    )


    if converted is None:

        print(
            (
                "MSRP CURRENCY CONVERSION FAILED | "
                f"{original_currency}->"
                f"{target_currency}"
            )
        )

        return None


    return {

        "amount":
            converted,

        "currency":
            target_currency,

        "original_amount":
            original_amount,

        "original_currency":
            original_currency,

        "conversion_used":
            True,
    }


# =========================================================
# ANALYZE PRICE HISTORY
# =========================================================

async def analyze_price_history(
    session,
    *,
    store_product_id,
    current_price,
    old_price=None,
    currency="USD",
    window_days=30,
    reference_price=None,
):

    current = (
        _safe_float(
            current_price
        )
    )


    current_currency = (
        _normalize_currency(
            currency
        )
    )


    if current is None:

        return DealIntelligence(

            window_days=(
                window_days
            )
        )


    # =====================================================
    # HISTORY WINDOW
    # =====================================================

    cutoff = (

        datetime.utcnow()

        - timedelta(
            days=window_days
        )
    )


    query = (

        select(
            PriceHistory.price
        )

        .where(
            PriceHistory.store_product_id
            == store_product_id
        )

        .where(
            PriceHistory.recorded_at
            >= cutoff
        )
    )


    if current_currency:

        query = query.where(

            PriceHistory.currency
            == current_currency
        )


    result = (
        await session.execute(
            query
        )
    )


    # =====================================================
    # CLEAN HISTORY VALUES
    # =====================================================

    prices = []


    for value in (
        result.scalars().all()
    ):

        parsed = (
            _safe_float(
                value
            )
        )


        if parsed is not None:

            prices.append(
                parsed
            )


    old = (
        _safe_float(
            old_price
        )
    )


    # =====================================================
    # INCLUDE PREVIOUS PRICE
    # =====================================================

    if old is not None:

        if (

            not prices

            or

            abs(
                prices[-1]
                - old
            )
            > 0.000001

        ):

            prices.append(
                old
            )


    # =====================================================
    # INCLUDE CURRENT PRICE
    # =====================================================

    if (

        not prices

        or

        abs(
            prices[-1]
            - current
        )
        > 0.000001

    ):

        prices.append(
            current
        )


    # =====================================================
    # HISTORICAL RANGE
    # =====================================================

    low_price = min(
        prices
    )


    average_price = mean(
        prices
    )


    high_price = max(
        prices
    )


    sample_count = len(
        prices
    )


    # =====================================================
    # HISTORICAL SCORE
    # =====================================================

    (
        historical_score,
        historical_label,
        confidence,
        vs_average_pct,
        vs_low_pct,
    ) = calculate_historical_score(

        current_price=(
            current
        ),

        average_price=(
            average_price
        ),

        low_price=(
            low_price
        ),

        old_price=(
            old
        ),

        sample_count=(
            sample_count
        ),
    )


    # =====================================================
    # PRICE DROP %
    # =====================================================

    price_drop_pct = None


    if (

        old is not None

        and

        current < old

    ):

        price_drop_pct = (

            (
                old
                - current
            )

            / old

        ) * 100


    # =====================================================
    # MSRP DEFAULTS
    # =====================================================

    msrp = None

    msrp_currency = None

    msrp_source = None

    msrp_confidence = None


    msrp_original = None

    msrp_original_currency = None

    msrp_conversion_used = False


    msrp_assessment = {

        "vs_msrp_pct":
            None,

        "markup_amount":
            None,

        "price_state":
            None,

        "scalper_risk":
            None,
    }


    # =====================================================
    # MSRP / REFERENCE PRICE
    # =====================================================

    if reference_price is not None:

        converted_reference = (
            await convert_reference_to_store_currency(

                reference_price=(
                    reference_price
                ),

                store_currency=(
                    current_currency
                ),
            )
        )


        if converted_reference is not None:

            msrp = (
                _safe_float(

                    converted_reference[
                        "amount"
                    ]
                )
            )


            msrp_currency = (
                converted_reference[
                    "currency"
                ]
            )


            msrp_original = (
                converted_reference[
                    "original_amount"
                ]
            )


            msrp_original_currency = (
                converted_reference[
                    "original_currency"
                ]
            )


            msrp_conversion_used = bool(

                converted_reference[
                    "conversion_used"
                ]
            )


            msrp_source = (
                getattr(
                    reference_price,
                    "source",
                    None,
                )
            )


            msrp_confidence = (
                getattr(
                    reference_price,
                    "confidence",
                    None,
                )
            )


            msrp_assessment = (
                assess_msrp(

                    current_price=(
                        current
                    ),

                    msrp=(
                        msrp
                    ),
                )
            )


            print(
                (
                    "MSRP INTELLIGENCE | "
                    f"Current={current:.2f} "
                    f"{current_currency} | "
                    f"Reference={msrp:.2f} "
                    f"{msrp_currency} | "
                    f"Original="
                    f"{msrp_original:.2f} "
                    f"{msrp_original_currency} | "
                    f"Converted="
                    f"{msrp_conversion_used} | "
                    f"VsMSRP="
                    f"{msrp_assessment['vs_msrp_pct']}% | "
                    f"Risk="
                    f"{msrp_assessment['scalper_risk']}"
                )
            )


    # =====================================================
    # FINAL DEAL SCORE
    # =====================================================

    final_score = (
        adjust_score_for_msrp(

            historical_score=(
                historical_score
            ),

            current_price=(
                current
            ),

            msrp=(
                msrp
            ),

            msrp_confidence=(
                msrp_confidence
            ),

            scalper_risk=(

                msrp_assessment[
                    "scalper_risk"
                ]
            ),
        )
    )


    final_label = (
        _final_label(

            final_score,

            scalper_risk=(

                msrp_assessment[
                    "scalper_risk"
                ]
            ),
        )
    )


    # =====================================================
    # RETURN
    # =====================================================

    return DealIntelligence(

        window_days=(
            window_days
        ),

        low=round(
            low_price,
            4,
        ),

        average=round(
            average_price,
            4,
        ),

        high=round(
            high_price,
            4,
        ),

        sample_count=(
            sample_count
        ),

        vs_average_pct=(

            round(
                vs_average_pct,
                2,
            )

            if (
                vs_average_pct
                is not None
            )

            else None
        ),

        vs_low_pct=(

            round(
                vs_low_pct,
                2,
            )

            if (
                vs_low_pct
                is not None
            )

            else None
        ),

        price_drop_pct=(

            round(
                price_drop_pct,
                2,
            )

            if (
                price_drop_pct
                is not None
            )

            else None
        ),

        historical_deal_score=(
            historical_score
        ),


        # =================================================
        # MSRP
        # =================================================

        msrp=(
            round(
                msrp,
                4,
            )

            if msrp
            is not None

            else None
        ),

        msrp_currency=(
            msrp_currency
        ),

        msrp_source=(
            msrp_source
        ),

        msrp_confidence=(
            msrp_confidence
        ),

        msrp_original=(

            round(
                msrp_original,
                4,
            )

            if (
                msrp_original
                is not None
            )

            else None
        ),

        msrp_original_currency=(
            msrp_original_currency
        ),

        msrp_conversion_used=(
            msrp_conversion_used
        ),


        # =================================================
        # MSRP ANALYSIS
        # =================================================

        vs_msrp_pct=(

            msrp_assessment[
                "vs_msrp_pct"
            ]
        ),

        markup_amount=(

            msrp_assessment[
                "markup_amount"
            ]
        ),

        msrp_price_state=(

            msrp_assessment[
                "price_state"
            ]
        ),

        scalper_risk=(

            msrp_assessment[
                "scalper_risk"
            ]
        ),


        # =================================================
        # FINAL DEAL SCORE
        # =================================================

        deal_score=(
            final_score
        ),

        deal_label=(
            final_label
        ),

        deal_confidence=(
            confidence
        ),
    )