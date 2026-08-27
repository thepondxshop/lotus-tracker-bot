from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import select

from app.models import PriceHistory


# =========================================================
# LOTUS DEAL INTELLIGENCE
# PonDeX Trackers
# Version 0.9.0
#
# Historical Pricing + Deal Score v1
# =========================================================


@dataclass
class DealIntelligence:
    window_days: int = 30

    low: float | None = None
    average: float | None = None
    high: float | None = None

    sample_count: int = 0

    vs_average_pct: float | None = None
    vs_low_pct: float | None = None

    price_drop_pct: float | None = None

    deal_score: float | None = None
    deal_label: str | None = None
    deal_confidence: str | None = None

    def to_event_fields(self):
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

            "deal_score":
                self.deal_score,

            "deal_label":
                self.deal_label,

            "deal_confidence":
                self.deal_confidence,
        }


def _safe_float(value):
    if value is None:
        return None

    try:
        number = float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if number <= 0:
        return None

    return number


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


def _confidence_from_samples(
    sample_count,
):
    """
    Confidence is intentionally conservative.

    LOW:
        1-2 useful observations

    MEDIUM:
        3-5 useful observations

    HIGH:
        6+ useful observations
    """

    if sample_count >= 6:
        return "HIGH"

    if sample_count >= 3:
        return "MEDIUM"

    return "LOW"


def _confidence_component(
    confidence,
):
    if confidence == "HIGH":
        return 1.0

    if confidence == "MEDIUM":
        return 0.65

    return 0.30


def _deal_label(
    score,
    current_price,
    average_price,
):
    if (
        average_price is not None
        and current_price > average_price
    ):
        if score < 4.5:
            return "Above Average"

    if score >= 8.0:
        return "Excellent Deal"

    if score >= 6.5:
        return "Good Deal"

    if score >= 4.5:
        return "Fair Price"

    if (
        average_price is not None
        and current_price > average_price
    ):
        return "Above Average"

    return "Normal Price"


def score_deal(
    *,
    current_price,
    average_price,
    low_price,
    old_price=None,
    sample_count=0,
):
    """
    Deal Score v1 â 0.0 to 10.0

    Weighting:
      40% = discount vs 30-day average
      30% = proximity to 30-day low
      20% = size of current price drop
      10% = historical-data confidence

    This is deliberately transparent and deterministic.
    """

    current = _safe_float(
        current_price
    )

    average = _safe_float(
        average_price
    )

    low = _safe_float(
        low_price
    )

    old = _safe_float(
        old_price
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
    # VS AVERAGE
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
    # PROXIMITY TO LOW
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

        # Full points at the low.
        # Linearly falls to zero at 20% above the low.
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
        and current < old
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
        _confidence_from_samples(
            sample_count
        )
    )

    history_component = (
        _confidence_component(
            confidence
        )
        * 1.0
    )

    score = round(
        _clamp(
            (
                average_component
                + low_component
                + drop_component
                + history_component
            ),
            0.0,
            10.0,
        ),
        1,
    )

    label = _deal_label(
        score,
        current,
        average,
    )

    return (
        score,
        label,
        confidence,
        vs_average_pct,
        vs_low_pct,
    )


async def analyze_price_history(
    session,
    *,
    store_product_id,
    current_price,
    old_price=None,
    currency="USD",
    window_days=30,
):
    """
    Calculate historical pricing intelligence for one store
    product.

    The database stores observations in PriceHistory only when
    useful price states are recorded. We also fold the current
    and previous observed prices into the working window so a
    fresh price change can be scored immediately.
    """

    current = _safe_float(
        current_price
    )

    if current is None:
        return DealIntelligence(
            window_days=window_days
        )

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

    if currency:
        query = query.where(
            PriceHistory.currency
            == str(
                currency
            ).upper()
        )

    result = (
        await session.execute(
            query
        )
    )

    prices = []

    for value in result.scalars().all():
        parsed = _safe_float(
            value
        )

        if parsed is not None:
            prices.append(
                parsed
            )

    old = _safe_float(
        old_price
    )

    # Include the last-known price as an observation when it
    # is not already represented by the latest history row.
    if old is not None:
        if (
            not prices
            or abs(
                prices[-1]
                - old
            )
            > 0.000001
        ):
            prices.append(
                old
            )

    # Include current price so a newly reached low can
    # immediately become the 30-day low shown in the alert.
    # Avoid counting an unchanged current price as a second
    # historical observation.
    if (
        not prices
        or abs(
            prices[-1]
            - current
        )
        > 0.000001
    ):
        prices.append(
            current
        )

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

    (
        score,
        label,
        confidence,
        vs_average_pct,
        vs_low_pct,
    ) = score_deal(
        current_price=current,
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

    price_drop_pct = None

    if (
        old is not None
        and current < old
    ):
        price_drop_pct = (
            (
                old
                - current
            )
            / old
        ) * 100

    return DealIntelligence(
        window_days=window_days,

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
            if vs_average_pct
            is not None
            else None
        ),

        vs_low_pct=(
            round(
                vs_low_pct,
                2,
            )
            if vs_low_pct
            is not None
            else None
        ),

        price_drop_pct=(
            round(
                price_drop_pct,
                2,
            )
            if price_drop_pct
            is not None
            else None
        ),

        deal_score=score,

        deal_label=label,

        deal_confidence=(
            confidence
        ),
    )
