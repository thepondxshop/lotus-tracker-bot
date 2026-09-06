"""
Lotus Tracker Bot
PonDeX Trackers

Universal Retailer Onboarding Service
Version: 1.0.0

Step 6J-3E1 — Immediate Silent Validation Foundation

Purpose:
- Validate a newly staged universal retailer immediately.
- Reuse the production universal adapter + normalization pipeline.
- Perform the first scan silently so an existing catalog does not spam Discord.
- Keep the store inactive until a later explicit enable/auto-enable decision.
- Record a simple validation state on the existing Store row.

Safety:
- Shopify is not handled here.
- Public storefront / adapter-supported sources only.
- No cart mutation or checkout automation.
- No CAPTCHA / queue / anti-bot bypass.
- Unknown availability remains unknown.
- Validation never activates a retailer by itself.
"""

from __future__ import annotations

import asyncio
import logging

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Store
from app.retailer_registry import (
    get_registered_retailer_platforms,
    normalize_platform,
)
from app.retailers import load_retailer_adapters
from app.universal_retailer_monitor import (
    SUPPORTED_UNIVERSAL_PLATFORMS,
    scan_store,
)


VERSION = "1.0.0"

logger = logging.getLogger(
    "lotus.retailer_onboarding"
)


ONBOARDING_SCAN_TIMEOUT_SECONDS = 180

VALIDATED_REASON = "UNIVERSAL_VALIDATED"
VALIDATION_FAILED_REASON = "VALIDATION_FAILED"


# =========================================================
# RESULT
# =========================================================

@dataclass
class RetailerOnboardingResult:
    store_id: int
    store_name: str
    domain: str
    platform: str
    region: str

    success: bool
    validated: bool
    activated: bool

    scan_mode: str | None
    products: int
    created: int
    updated: int
    events: int
    suppressed: int

    unknown_availability: int
    missing_prices: int
    backorders: int

    availability_coverage: str
    price_coverage: str

    validation_reason: str
    scan_error: str | None
    timed_out: bool

    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =========================================================
# HELPERS
# =========================================================

def utcnow() -> datetime:
    return datetime.utcnow()


def clean_text(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default

    value = str(value).strip()
    return value or default


def coverage_label(
    total: int,
    missing_or_unknown: int,
) -> str:
    total = max(int(total or 0), 0)
    missing_or_unknown = max(
        int(missing_or_unknown or 0),
        0,
    )

    if total <= 0:
        return "UNKNOWN"

    if missing_or_unknown <= 0:
        return "FULL"

    if missing_or_unknown >= total:
        return "NONE"

    return "PARTIAL"


async def get_store(
    store_id: int,
) -> Store | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Store)
            .where(Store.id == store_id)
            .limit(1)
        )

        return result.scalar_one_or_none()


async def update_store_validation_state(
    *,
    store_id: int,
    validated: bool,
    error: str | None,
) -> None:
    """
    Persist validation state without activating the retailer.

    Existing schema fields are reused deliberately so this step
    does not require an Alembic migration.
    """

    async with SessionLocal() as session:
        result = await session.execute(
            select(Store)
            .where(Store.id == store_id)
            .limit(1)
        )

        store = result.scalar_one_or_none()

        if store is None:
            return

        # Step 6J-3E1 never activates automatically.
        store.active = False

        if validated:
            store.health_status = "HEALTHY"
            store.consecutive_failures = 0
            store.last_success_at = utcnow()
            store.last_error = None
            store.disabled_reason = VALIDATED_REASON

        else:
            # A staged validation failure should not be treated like
            # a production-store failure. Keep it inactive and record
            # the reason for admin review/retry.
            store.disabled_reason = VALIDATION_FAILED_REASON
            store.last_failure_at = utcnow()
            store.last_error = (
                clean_text(
                    error,
                    "VALIDATION_FAILED",
                )
                or "VALIDATION_FAILED"
            )

        await session.commit()


# =========================================================
# VALIDATION
# =========================================================

async def validate_staged_retailer(
    store_id: int,
    *,
    timeout_seconds: int = ONBOARDING_SCAN_TIMEOUT_SECONDS,
) -> RetailerOnboardingResult:
    """
    Immediately run a controlled silent first scan for a staged store.

    IMPORTANT:
    - suppress_events=True prevents historical catalog spam.
    - automatic_mode=False forces the adapter's full initial discovery path.
    - the store remains inactive even when validation passes.
    """

    store = await get_store(
        store_id
    )

    if store is None:
        raise ValueError(
            f"Store ID {store_id} was not found."
        )

    platform = normalize_platform(
        getattr(
            store,
            "platform",
            None,
        )
    )

    store_name = clean_text(
        getattr(
            store,
            "name",
            None,
        ),
        "Unknown Store",
    )

    domain = clean_text(
        getattr(
            store,
            "domain",
            None,
        )
    )

    region = clean_text(
        getattr(
            store,
            "region",
            None,
        ),
        "US",
    ).upper()

    if platform == "shopify":
        raise ValueError(
            "Shopify stores use the dedicated Shopify monitor."
        )

    if platform not in SUPPORTED_UNIVERSAL_PLATFORMS:
        raise ValueError(
            f"Unsupported universal platform: {platform}"
        )

    if not domain:
        raise ValueError(
            "Store has no domain."
        )

    load_retailer_adapters()

    registered = set(
        get_registered_retailer_platforms()
    )

    if platform not in registered:
        raise ValueError(
            f"No registered adapter for platform: {platform}"
        )

    timeout_seconds = max(
        30,
        min(
            int(timeout_seconds),
            300,
        ),
    )

    logger.info(
        (
            "UNIVERSAL ONBOARDING VALIDATION START | "
            "Store=%s | StoreID=%s | Platform=%s | "
            "Domain=%s | TimeoutSeconds=%s | "
            "Silent=True | AutoActivate=False"
        ),
        store_name,
        store.id,
        platform,
        domain,
        timeout_seconds,
    )

    timed_out = False
    scan_error = None
    scan_result: dict[str, Any] = {}

    try:
        scan_result = await asyncio.wait_for(
            scan_store(
                store,
                suppress_events=True,
                automatic_mode=False,
            ),
            timeout=timeout_seconds,
        )

    except asyncio.TimeoutError:
        timed_out = True
        scan_error = (
            "ONBOARDING_SCAN_TIMEOUT:"
            f"{timeout_seconds}s"
        )

    except asyncio.CancelledError:
        raise

    except Exception as error:
        scan_error = (
            f"{type(error).__name__}:"
            f"{error}"
        )

        logger.exception(
            (
                "UNIVERSAL ONBOARDING VALIDATION ERROR | "
                "Store=%s | StoreID=%s | Platform=%s"
            ),
            store_name,
            store.id,
            platform,
        )

    if not scan_error:
        scan_error = clean_text(
            scan_result.get("error"),
            "",
        ) or None

    products = int(
        scan_result.get(
            "products",
            0,
        )
        or 0
    )

    unknown_availability = int(
        scan_result.get(
            "unknown_availability",
            0,
        )
        or 0
    )

    missing_prices = int(
        scan_result.get(
            "missing_prices",
            0,
        )
        or 0
    )

    scan_success = bool(
        scan_result.get(
            "success",
            False,
        )
    )

    validated = bool(
        scan_success
        and products > 0
        and not timed_out
        and scan_error is None
    )

    if validated:
        validation_reason = "VALIDATION_PASSED"

    elif timed_out:
        validation_reason = "VALIDATION_TIMEOUT"

    elif scan_error:
        validation_reason = scan_error

    elif products <= 0:
        validation_reason = "NO_SUPPORTED_PRODUCTS_FOUND"

    else:
        validation_reason = "VALIDATION_FAILED"

    await update_store_validation_state(
        store_id=store.id,
        validated=validated,
        error=(
            None
            if validated
            else validation_reason
        ),
    )

    diagnostics = scan_result.get(
        "diagnostics",
        {},
    )

    if not isinstance(
        diagnostics,
        dict,
    ):
        diagnostics = {}

    result = RetailerOnboardingResult(
        store_id=store.id,
        store_name=store_name,
        domain=domain,
        platform=platform,
        region=region,

        success=validated,
        validated=validated,
        activated=False,

        scan_mode=(
            clean_text(
                scan_result.get("scan_mode"),
                "",
            )
            or None
        ),

        products=products,

        created=int(
            scan_result.get(
                "created",
                0,
            )
            or 0
        ),

        updated=int(
            scan_result.get(
                "updated",
                0,
            )
            or 0
        ),

        events=int(
            scan_result.get(
                "events",
                0,
            )
            or 0
        ),

        suppressed=int(
            scan_result.get(
                "suppressed",
                0,
            )
            or 0
        ),

        unknown_availability=(
            unknown_availability
        ),

        missing_prices=missing_prices,

        backorders=int(
            scan_result.get(
                "backorders",
                0,
            )
            or 0
        ),

        availability_coverage=(
            coverage_label(
                products,
                unknown_availability,
            )
        ),

        price_coverage=(
            coverage_label(
                products,
                missing_prices,
            )
        ),

        validation_reason=(
            validation_reason
        ),

        scan_error=scan_error,
        timed_out=timed_out,
        diagnostics=dict(diagnostics),
    )

    logger.info(
        (
            "UNIVERSAL ONBOARDING VALIDATION COMPLETE | "
            "Store=%s | StoreID=%s | Platform=%s | "
            "Validated=%s | Products=%s | "
            "AvailabilityCoverage=%s | PriceCoverage=%s | "
            "Suppressed=%s | Reason=%s | "
            "StoreRemainsInactive=True"
        ),
        result.store_name,
        result.store_id,
        result.platform,
        result.validated,
        result.products,
        result.availability_coverage,
        result.price_coverage,
        result.suppressed,
        result.validation_reason,
    )

    return result


# =========================================================
# OPTIONAL ADMIN RETRY ENTRY POINT
# =========================================================

async def retry_retailer_validation(
    store_id: int,
) -> dict[str, Any]:
    result = await validate_staged_retailer(
        store_id
    )

    return result.to_dict()
