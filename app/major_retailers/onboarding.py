"""
Lotus Major Retailer Auto-Onboarding Foundation
Step 6K-2A

Purpose:
- Read-only detection for a major-retailer domain.
- Recognize built-in major retailers automatically.
- Reuse Lotus's existing storefront platform fingerprinting.
- Recommend a reusable adapter family when possible.
- Persist an inactive Store row for major-retailer staging without activating monitoring.
- Never auto-enable alerts or background scans.

This is onboarding automation, not autonomous internet crawling. Automatic discovery of
new retailer candidates from release/community intelligence remains a later milestone.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Store
from app.retailer_platform_detector import detect_retailer_platform, platform_display_name

from .families import recommend_adapter_family
from .registry import (
    get_major_retailer_adapter_class,
    list_major_retailer_definitions,
    normalize_retailer_key,
)

VERSION = "1.0.6"
STEP = "6K-2A"
STAGING_REASON = "MAJOR_RETAILER_STAGING"


@dataclass
class MajorRetailerDetection:
    domain: str
    region: str
    known_retailer: bool
    retailer_key: str | None
    display_name: str | None
    catalog_domain: str | None
    adapter_registered: bool
    affiliate_provider: str | None
    underlying_platform: str
    underlying_platform_label: str
    platform_confidence: str
    platform_score: int
    homepage_status: int | None
    homepage_url: str | None
    platform_signals: list[str]
    platform_errors: list[str]
    recommended_strategy: str
    adapter_family_key: str
    adapter_family_name: str
    reusable_family: bool
    auto_stage_safe: bool
    next_step: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MajorRetailerStageResult:
    created: bool
    store_id: int
    store_name: str
    domain: str
    region: str
    active: bool
    existing_platform: str | None
    detection: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_major_domain(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").strip().lower().rstrip(".")
    except Exception:
        host = raw.lower().split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _known_definition_for_domain(domain: str):
    normalized = normalize_major_domain(domain)
    for definition in list_major_retailer_definitions():
        if normalize_major_domain(definition.domain) == normalized:
            return definition
    return None


def _recommended_strategy(*, known: bool, adapter_registered: bool, reusable: bool) -> str:
    if adapter_registered:
        return "EXISTING_DEDICATED_ADAPTER"
    if known:
        return "KNOWN_MAJOR_ADAPTER_PENDING"
    if reusable:
        return "REUSABLE_MAJOR_ADAPTER_FAMILY"
    return "CUSTOM_MAJOR_ADAPTER_REVIEW"


def _next_step(strategy: str, retailer_key: str | None, family_name: str) -> str:
    if strategy == "EXISTING_DEDICATED_ADAPTER":
        key = retailer_key or "retailer_key"
        return f"Run /majorprobe retailer:{key}, then a controlled /majorscan if the probe is appropriate."
    if strategy == "KNOWN_MAJOR_ADAPTER_PENDING":
        return "Keep the retailer inactive and build/attach its dedicated validated adapter or official feed source."
    if strategy == "REUSABLE_MAJOR_ADAPTER_FAMILY":
        return f"Stage it inactive, then derive a retailer adapter from {family_name} and silently validate it."
    return "Stage it inactive for review, then identify a trustworthy public API/feed/storefront source before writing a custom adapter."


async def detect_major_retailer(domain: str, *, region: str = "US") -> dict[str, Any]:
    clean_domain = normalize_major_domain(domain)
    clean_region = str(region or "US").strip().upper() or "US"
    if not clean_domain or "." not in clean_domain:
        raise ValueError("A valid retailer domain is required.")

    definition = _known_definition_for_domain(clean_domain)
    known = definition is not None
    retailer_key = definition.key if definition else None
    adapter_registered = bool(
        retailer_key and get_major_retailer_adapter_class(retailer_key) is not None
    )

    platform = "unknown"
    platform_label = "Unknown"
    confidence = "UNKNOWN"
    score = 0
    homepage_status = None
    homepage_url = None
    signals: list[str] = []
    errors: list[str] = []

    try:
        detection = await detect_retailer_platform(clean_domain)
        platform = str(getattr(detection, "platform", None) or "unknown")
        platform_label = platform_display_name(platform)
        confidence = str(getattr(detection, "confidence", None) or "UNKNOWN")
        score = int(getattr(detection, "score", 0) or 0)
        homepage_status = getattr(detection, "homepage_status", None)
        homepage_url = getattr(detection, "homepage_url", None)
        signals = [str(x) for x in (getattr(detection, "signals", None) or [])[:8]]
        errors = [str(x) for x in (getattr(detection, "errors", None) or [])[:6]]
    except asyncio.CancelledError:
        raise
    except Exception as error:
        errors.append(f"PLATFORM_FINGERPRINT_ERROR:{type(error).__name__}:{error}")

    family = recommend_adapter_family(platform)
    strategy = _recommended_strategy(
        known=known,
        adapter_registered=adapter_registered,
        reusable=family.reusable,
    )

    result = MajorRetailerDetection(
        domain=clean_domain,
        region=clean_region,
        known_retailer=known,
        retailer_key=retailer_key,
        display_name=definition.display_name if definition else None,
        catalog_domain=definition.domain if definition else None,
        adapter_registered=adapter_registered,
        affiliate_provider=definition.affiliate_provider if definition else None,
        underlying_platform=platform,
        underlying_platform_label=platform_label,
        platform_confidence=confidence,
        platform_score=score,
        homepage_status=int(homepage_status) if homepage_status is not None else None,
        homepage_url=str(homepage_url) if homepage_url else None,
        platform_signals=signals,
        platform_errors=errors,
        recommended_strategy=strategy,
        adapter_family_key=family.key,
        adapter_family_name=family.display_name,
        reusable_family=family.reusable,
        # Staging creates only an inactive administrative row. It does not grant
        # monitoring capability, so even ambiguous/custom domains can be staged safely.
        auto_stage_safe=True,
        next_step=_next_step(strategy, retailer_key, family.display_name),
    )
    return result.to_dict()


async def stage_major_retailer(
    *,
    name: str,
    domain: str,
    region: str = "US",
) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Retailer name is required.")

    detection = await detect_major_retailer(domain, region=region)
    clean_domain = detection["domain"]
    clean_region = detection["region"]

    async with SessionLocal() as session:
        candidates = {clean_domain, f"www.{clean_domain}"}
        result = await session.execute(
            select(Store).where(Store.domain.in_(candidates)).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return MajorRetailerStageResult(
                created=False,
                store_id=int(existing.id),
                store_name=str(existing.name),
                domain=str(existing.domain),
                region=str(existing.region or clean_region),
                active=bool(existing.active),
                existing_platform=str(existing.platform or ""),
                detection=detection,
            ).to_dict()

        key = detection.get("retailer_key") or normalize_retailer_key(clean_domain)
        disabled_reason = f"{STAGING_REASON}:{key}"[:240]
        store = Store(
            name=clean_name,
            domain=clean_domain,
            platform="major_retailer",
            region=clean_region,
            active=False,
            health_status="HEALTHY",
            consecutive_failures=0,
            disabled_reason=disabled_reason,
        )
        session.add(store)
        await session.commit()
        await session.refresh(store)

        return MajorRetailerStageResult(
            created=True,
            store_id=int(store.id),
            store_name=str(store.name),
            domain=str(store.domain),
            region=str(store.region or clean_region),
            active=bool(store.active),
            existing_platform=str(store.platform or ""),
            detection=detection,
        ).to_dict()


async def list_staged_major_retailers() -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Store)
            .where(Store.platform == "major_retailer")
            .order_by(Store.id.asc())
        )
        stores = list(result.scalars().all())

    rows: list[dict[str, Any]] = []
    for store in stores:
        rows.append({
            "store_id": int(store.id),
            "name": str(store.name),
            "domain": str(store.domain),
            "region": str(store.region or "US"),
            "active": bool(store.active),
            "health_status": str(store.health_status or "UNKNOWN"),
            "disabled_reason": str(store.disabled_reason or ""),
        })
    return rows


async def get_major_retailer_onboarding_status() -> dict[str, Any]:
    try:
        staged = await list_staged_major_retailers()
        database_available = True
        error = None
    except Exception as exc:
        staged = []
        database_available = False
        error = f"{type(exc).__name__}:{exc}"

    return {
        "version": VERSION,
        "step": STEP,
        "database_available": database_available,
        "staged_major_retailers": len(staged),
        "domain_auto_detection": True,
        "platform_fingerprinting": True,
        "adapter_family_recommendation": True,
        "autonomous_shop_discovery": False,
        "automatic_activation": False,
        "last_error": error,
    }
