"""
Lotus Major Retailer Production Event Pipeline
Step 6K-2C • Bot release 1.0.6

Responsibilities:
- Persistent major-retailer baselines/snapshots.
- Capability-safe change detection.
- Validation vs production modes.
- Formal promotion gate.
- Per-retailer + global emergency kill switches.
- Change-based dedupe/cooldown protection.
- Redis/ProductEvent integration only after explicit promotion.
- Background monitoring of promoted retailers only.

Critical safety rules:
- A missing product in a bounded scan NEVER means sold out.
- UNKNOWN availability NEVER becomes a stock/restock/sold-out event.
- Online and local inventory remain separate; this pipeline only acts on verified
  online availability until local-inventory support is added explicitly.
- Target is production-blocked until an approved official source exists.
- Walmart is production-blocked in 6K-3A until online stock signals are separately validated.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from app.database import SessionLocal
from app.event_service import (
    push_product_event,
    save_product_event,
    serialize_product_event,
)
from app.events import ProductEvent, ProductEventType
from app.models import Store

from .monitor import probe_major_retailer, scan_major_retailer
from .registry import (
    build_major_retailer_adapter,
    get_major_retailer_adapter_class,
    get_major_retailer_definition,
    normalize_retailer_key,
)

VERSION = "1.0.6"
STEP = "6K-2C"

VALIDATION_PASSES_REQUIRED = 2
BACKGROUND_INTERVAL_SECONDS = 180
BACKGROUND_SCAN_LIMIT = 50
MAX_REJECTION_RATIO = 0.50
STOCK_CONFIDENCE_MINIMUM = "MEDIUM"
FLICKER_WINDOW_SECONDS = 300
AUTO_DEMOTE_FAILURES = 3

PRODUCTION_BLOCKS = {
    "premium_bandai": "PREMIUM_BANDAI_SOURCE_ASSESSMENT_ONLY_STEP_6K_3D",
    "gamestop": "GAMESTOP_SOURCE_VALIDATION_REQUIRED_STEP_6K_3C",
    "best_buy": "BESTBUY_API_LIVE_VALIDATION_REQUIRED_STEP_6K_3B",
    "target": "TARGET_OFFICIAL_SOURCE_REQUIRED",
    "walmart": "WALMART_VALIDATION_ONLY_STEP_6K_3A",
}

CONFIDENCE_RANK = {
    "UNKNOWN": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
}

EVENT_COOLDOWNS_SECONDS = {
    "DISCOVERED": 300,
    "PAGE_LIVE": 300,
    "COMING_SOON": 300,
    "PREORDER_LIVE": 180,
    "STOCK_AVAILABLE": 90,
    "RESTOCK": 90,
    "SOLD_OUT": 90,
    "PRICE_DROP": 300,
    "PRICE_INCREASE": 300,
    "INVENTORY_FLICKER": 60,
    "RELEASE_DATE_CHANGED": 300,
}

_SCHEMA_LOCK = asyncio.Lock()
_SCHEMA_READY = False
_SCAN_LOCKS: dict[str, asyncio.Lock] = {}

_STATUS: dict[str, Any] = {
    "version": VERSION,
    "step": STEP,
    "running": False,
    "background_monitor_enabled": True,
    "background_interval_seconds": BACKGROUND_INTERVAL_SECONDS,
    "current_retailer": None,
    "last_cycle_started_at": None,
    "last_cycle_completed_at": None,
    "last_cycle_retailers": 0,
    "last_cycle_failures": 0,
    "last_scan_retailer": None,
    "last_scan_mode": None,
    "last_scan_success": None,
    "last_error": None,
    "events_emitted_total": 0,
    "events_suppressed_validation_total": 0,
    "events_blocked_capability_total": 0,
    "events_blocked_confidence_total": 0,
    "events_blocked_cooldown_total": 0,
    "unknown_stock_ignored_total": 0,
    "missing_product_inference_events": 0,
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _clean(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    return _clean(value, default).upper().replace("-", "_").replace(" ", "_")


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number, 4)


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _platform_data(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("platform_data")
    return dict(raw) if isinstance(raw, dict) else {}


def _availability_state(item: dict[str, Any]) -> str:
    data = _platform_data(item)
    return _upper(data.get("availability_state"), "UNKNOWN")


def _availability_known(item: dict[str, Any]) -> bool:
    data = _platform_data(item)
    return bool(data.get("availability_known") is True)


def _availability_confidence(item: dict[str, Any]) -> str:
    data = _platform_data(item)
    return _upper(data.get("availability_confidence"), "UNKNOWN")


def _lifecycle_state(item: dict[str, Any]) -> str:
    data = _platform_data(item)
    return _upper(data.get("lifecycle_state"), "UNKNOWN")


def _lifecycle_confidence(item: dict[str, Any]) -> str:
    data = _platform_data(item)
    return _upper(data.get("lifecycle_confidence"), "UNKNOWN")


def _source_confidence(item: dict[str, Any]) -> str:
    data = _platform_data(item)
    return _upper(data.get("source_confidence"), "UNKNOWN")


def _release_date(item: dict[str, Any]) -> str | None:
    value = item.get("release_date") or _platform_data(item).get("release_date")
    value = _clean(value)
    return value or None


def _inventory_quantity(item: dict[str, Any]) -> int | None:
    return _int(_platform_data(item).get("exact_inventory_quantity"))


def _confidence_at_least(value: str, minimum: str) -> bool:
    return CONFIDENCE_RANK.get(_upper(value), 0) >= CONFIDENCE_RANK.get(_upper(minimum), 0)


def _scan_lock(retailer_key: str) -> asyncio.Lock:
    key = normalize_retailer_key(retailer_key)
    if key not in _SCAN_LOCKS:
        _SCAN_LOCKS[key] = asyncio.Lock()
    return _SCAN_LOCKS[key]


def _adapter_signature(retailer_key: str, scan: dict[str, Any]) -> str:
    payload = {
        "retailer_key": normalize_retailer_key(retailer_key),
        "adapter_class": scan.get("adapter_class"),
        "adapter_version": scan.get("adapter_version"),
        "capabilities": scan.get("capabilities") or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def ensure_major_pipeline_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        async with SessionLocal() as session:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS major_retailer_runtime (
                    retailer_key VARCHAR(100) PRIMARY KEY,
                    store_id BIGINT NULL,
                    mode VARCHAR(30) NOT NULL DEFAULT 'VALIDATION',
                    kill_switch BOOLEAN NOT NULL DEFAULT FALSE,
                    baseline_ready BOOLEAN NOT NULL DEFAULT FALSE,
                    validation_passes INTEGER NOT NULL DEFAULT 0,
                    validation_failures INTEGER NOT NULL DEFAULT 0,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_probe_success BOOLEAN NULL,
                    last_validation_at TIMESTAMP NULL,
                    last_scan_at TIMESTAMP NULL,
                    last_success_at TIMESTAMP NULL,
                    last_error TEXT NULL,
                    promoted_at TIMESTAMP NULL,
                    validated_signature VARCHAR(128) NULL,
                    last_adapter_signature VARCHAR(128) NULL,
                    last_accepted INTEGER NOT NULL DEFAULT 0,
                    last_rejected INTEGER NOT NULL DEFAULT 0,
                    last_candidate_events INTEGER NOT NULL DEFAULT 0,
                    last_emitted_events INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))

            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS major_retailer_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    retailer_key VARCHAR(100) NOT NULL,
                    external_product_id VARCHAR(255) NOT NULL,
                    title TEXT NOT NULL,
                    game VARCHAR(150) NOT NULL,
                    url TEXT NOT NULL,
                    price DOUBLE PRECISION NULL,
                    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
                    availability_state VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
                    availability_known BOOLEAN NOT NULL DEFAULT FALSE,
                    availability_confidence VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
                    lifecycle_state VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
                    lifecycle_confidence VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
                    product_type VARCHAR(150) NULL,
                    product_category VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
                    product_family VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
                    image_url TEXT NULL,
                    sku VARCHAR(255) NULL,
                    offer_id VARCHAR(255) NULL,
                    purchase_limit INTEGER NULL,
                    release_date TEXT NULL,
                    exact_inventory_quantity INTEGER NULL,
                    source_confidence VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
                    platform_data TEXT NULL,
                    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    availability_changed_at TIMESTAMP NULL,
                    price_changed_at TIMESTAMP NULL,
                    release_date_changed_at TIMESTAMP NULL,
                    CONSTRAINT uq_major_retailer_snapshot
                        UNIQUE (retailer_key, external_product_id)
                )
            """))

            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_major_retailer_snapshots_retailer
                ON major_retailer_snapshots (retailer_key)
            """))

            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS major_retailer_event_guards (
                    event_key VARCHAR(128) PRIMARY KEY,
                    retailer_key VARCHAR(100) NOT NULL,
                    external_product_id VARCHAR(255) NOT NULL,
                    event_type VARCHAR(100) NOT NULL,
                    last_emitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))

            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS major_retailer_event_outbox (
                    outbox_key VARCHAR(128) PRIMARY KEY,
                    guard_key VARCHAR(128) NOT NULL,
                    retailer_key VARCHAR(100) NOT NULL,
                    external_product_id VARCHAR(255) NOT NULL,
                    event_type VARCHAR(100) NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_attempt_at TIMESTAMP NULL
                )
            """))

            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_major_retailer_outbox_retailer
                ON major_retailer_event_outbox (retailer_key, created_at)
            """))

            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS major_retailer_system_control (
                    control_key VARCHAR(50) PRIMARY KEY,
                    global_kill_switch BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))

            await session.execute(text("""
                INSERT INTO major_retailer_system_control
                    (control_key, global_kill_switch, updated_at)
                VALUES
                    ('GLOBAL', FALSE, CURRENT_TIMESTAMP)
                ON CONFLICT (control_key) DO NOTHING
            """))
            await session.commit()

        _SCHEMA_READY = True


async def _ensure_runtime_row(retailer_key: str) -> None:
    await ensure_major_pipeline_schema()
    key = normalize_retailer_key(retailer_key)
    async with SessionLocal() as session:
        await session.execute(text("""
            INSERT INTO major_retailer_runtime
                (retailer_key, mode, kill_switch, baseline_ready,
                 validation_passes, validation_failures, consecutive_failures,
                 created_at, updated_at)
            VALUES
                (:retailer_key, 'VALIDATION', FALSE, FALSE, 0, 0, 0,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (retailer_key) DO NOTHING
        """), {"retailer_key": key})
        await session.commit()


async def _runtime_row(retailer_key: str) -> dict[str, Any]:
    await _ensure_runtime_row(retailer_key)
    key = normalize_retailer_key(retailer_key)
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT *
            FROM major_retailer_runtime
            WHERE retailer_key = :retailer_key
        """), {"retailer_key": key})
        row = result.mappings().first()
    return dict(row or {})


async def _global_kill_switch() -> bool:
    await ensure_major_pipeline_schema()
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT global_kill_switch
            FROM major_retailer_system_control
            WHERE control_key = 'GLOBAL'
        """))
        value = result.scalar_one_or_none()
    return bool(value)


async def _find_staged_store(retailer_key: str) -> Store | None:
    definition = get_major_retailer_definition(retailer_key)
    if definition is None:
        return None
    domain = str(definition.domain or "").strip().lower()
    candidates = {domain, f"www.{domain}"}
    async with SessionLocal() as session:
        result = await session.execute(
            select(Store)
            .where(Store.platform == "major_retailer")
            .where(Store.domain.in_(candidates))
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _bind_store_if_available(retailer_key: str) -> int | None:
    store = await _find_staged_store(retailer_key)
    store_id = int(store.id) if store is not None else None
    if store_id is not None:
        async with SessionLocal() as session:
            await session.execute(text("""
                UPDATE major_retailer_runtime
                SET store_id = :store_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE retailer_key = :retailer_key
            """), {"store_id": store_id, "retailer_key": normalize_retailer_key(retailer_key)})
            await session.commit()
    return store_id


def _scan_quality(scan: dict[str, Any]) -> tuple[bool, list[str], dict[str, int]]:
    products = list(scan.get("normalized_products") or [])
    accepted = int(scan.get("accepted", 0) or 0)
    rejected = int(scan.get("rejected", 0) or 0)
    capabilities = dict(scan.get("capabilities") or {})

    price_hits = sum(1 for item in products if _float(item.get("price")) is not None)
    known_stock = sum(1 for item in products if _availability_known(item))
    high_or_medium_stock = sum(
        1 for item in products
        if _availability_known(item)
        and _confidence_at_least(_availability_confidence(item), STOCK_CONFIDENCE_MINIMUM)
    )

    reasons: list[str] = []
    if not bool(scan.get("success")):
        reasons.append(str(scan.get("error") or "SCAN_FAILED"))
    if not bool(capabilities.get("discovery")):
        reasons.append("DISCOVERY_CAPABILITY_NOT_VERIFIED")
    if accepted <= 0:
        reasons.append("NO_ACCEPTED_PRODUCTS")

    total = accepted + rejected
    if total > 0 and rejected / total > MAX_REJECTION_RATIO:
        reasons.append("REJECTION_RATIO_TOO_HIGH")

    if capabilities.get("price") and price_hits <= 0:
        reasons.append("PRICE_CAPABILITY_CLAIM_UNPROVEN")

    if capabilities.get("online_availability") and known_stock <= 0:
        reasons.append("ONLINE_AVAILABILITY_CLAIM_UNPROVEN")

    if capabilities.get("online_availability") and known_stock > 0 and high_or_medium_stock <= 0:
        reasons.append("STOCK_CONFIDENCE_TOO_LOW")

    metrics = {
        "price_hits": price_hits,
        "known_stock": known_stock,
        "trusted_stock": high_or_medium_stock,
    }
    return not reasons, reasons, metrics


def _event_allowed_by_capability(
    event_type: str,
    capabilities: dict[str, Any],
    item: dict[str, Any],
) -> tuple[bool, str | None]:
    event_type = _upper(event_type)

    if event_type == "DISCOVERED":
        return bool(capabilities.get("discovery")), "DISCOVERY_CAPABILITY_REQUIRED"
    if event_type in {"PAGE_LIVE", "COMING_SOON"}:
        return bool(capabilities.get("page_live")), "PAGE_LIVE_CAPABILITY_REQUIRED"
    if event_type == "PREORDER_LIVE":
        return bool(capabilities.get("preorder")), "PREORDER_CAPABILITY_REQUIRED"
    if event_type in {"PRICE_DROP", "PRICE_INCREASE"}:
        return bool(capabilities.get("price")), "PRICE_CAPABILITY_REQUIRED"
    if event_type == "RELEASE_DATE_CHANGED":
        return bool(capabilities.get("release_date")), "RELEASE_DATE_CAPABILITY_REQUIRED"
    if event_type in {"STOCK_AVAILABLE", "RESTOCK", "SOLD_OUT", "INVENTORY_FLICKER"}:
        if not capabilities.get("online_availability"):
            return False, "ONLINE_AVAILABILITY_CAPABILITY_REQUIRED"
        if not _availability_known(item):
            return False, "UNKNOWN_AVAILABILITY_BLOCKED"
        if not _confidence_at_least(_availability_confidence(item), STOCK_CONFIDENCE_MINIMUM):
            return False, "STOCK_CONFIDENCE_TOO_LOW"
        return True, None

    return False, "UNSUPPORTED_EVENT_TYPE"


def _event_identity(retailer_key: str, external_id: str, event_type: str, item: dict[str, Any]) -> str:
    event_type = _upper(event_type)
    state_value = ""
    if event_type in {"STOCK_AVAILABLE", "RESTOCK", "SOLD_OUT", "INVENTORY_FLICKER"}:
        state_value = _availability_state(item)
    elif event_type in {"PRICE_DROP", "PRICE_INCREASE"}:
        state_value = str(_float(item.get("price")) or "")
    elif event_type == "RELEASE_DATE_CHANGED":
        state_value = str(_release_date(item) or "")
    elif event_type in {"PAGE_LIVE", "COMING_SOON", "PREORDER_LIVE"}:
        state_value = _lifecycle_state(item)

    raw = "|".join([
        normalize_retailer_key(retailer_key),
        str(external_id),
        event_type,
        state_value,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _guard_recent(event_key: str, cooldown_seconds: int) -> bool:
    await ensure_major_pipeline_schema()
    threshold = _utcnow() - timedelta(seconds=max(int(cooldown_seconds), 0))
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT last_emitted_at
            FROM major_retailer_event_guards
            WHERE event_key = :event_key
        """), {"event_key": event_key})
        last = result.scalar_one_or_none()
    return isinstance(last, datetime) and last >= threshold


async def _mark_guard(
    *, event_key: str, retailer_key: str, external_product_id: str, event_type: str,
) -> None:
    async with SessionLocal() as session:
        await session.execute(text("""
            INSERT INTO major_retailer_event_guards
                (event_key, retailer_key, external_product_id, event_type, last_emitted_at)
            VALUES
                (:event_key, :retailer_key, :external_product_id, :event_type, CURRENT_TIMESTAMP)
            ON CONFLICT (event_key)
            DO UPDATE SET last_emitted_at = CURRENT_TIMESTAMP
        """), {
            "event_key": event_key,
            "retailer_key": normalize_retailer_key(retailer_key),
            "external_product_id": str(external_product_id),
            "event_type": _upper(event_type),
        })
        await session.commit()



async def _enqueue_outbox(
    *, retailer_key: str, external_product_id: str, event_type: str,
    guard_key: str, event: ProductEvent, transition_at: datetime,
) -> bool:
    payload = serialize_product_event(event)
    raw_key = "|".join([
        guard_key,
        transition_at.isoformat(timespec="microseconds"),
    ])
    outbox_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    async with SessionLocal() as session:
        result = await session.execute(text("""
            INSERT INTO major_retailer_event_outbox (
                outbox_key, guard_key, retailer_key, external_product_id,
                event_type, payload, attempts, created_at
            ) VALUES (
                :outbox_key, :guard_key, :retailer_key, :external_product_id,
                :event_type, :payload, 0, CURRENT_TIMESTAMP
            )
            ON CONFLICT (outbox_key) DO NOTHING
            RETURNING outbox_key
        """), {
            "outbox_key": outbox_key,
            "guard_key": guard_key,
            "retailer_key": normalize_retailer_key(retailer_key),
            "external_product_id": str(external_product_id),
            "event_type": _upper(event_type),
            "payload": json.dumps(payload, sort_keys=True, default=str),
        })
        inserted = result.scalar_one_or_none() is not None
        await session.commit()
    return inserted


def _event_from_payload(payload: dict[str, Any]) -> ProductEvent:
    timestamp = payload.get("timestamp")
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            timestamp = None

    allowed = {
        "event_type", "game", "product_name", "store_name", "product_url",
        "price", "old_price", "currency", "price_window_days", "price_30d_low",
        "price_30d_average", "price_30d_high", "price_history_samples",
        "price_vs_average_pct", "price_vs_low_pct", "price_drop_pct", "deal_score",
        "deal_label", "deal_confidence", "in_stock", "availability_state",
        "availability_known", "availability_confidence", "exact_inventory_quantity",
        "region", "language", "product_type", "product_category", "product_family",
        "lifecycle_state", "release_date", "old_release_date", "source_type",
        "retailer_key", "external_product_id", "source_confidence", "image_url",
        "variant_id", "purchase_limit", "cart_base_url", "timestamp",
    }
    kwargs = {key: payload.get(key) for key in allowed if key in payload}
    kwargs["event_type"] = ProductEventType(str(payload.get("event_type")))
    kwargs["timestamp"] = timestamp
    return ProductEvent(**kwargs)


async def _delete_outbox(outbox_key: str) -> None:
    async with SessionLocal() as session:
        await session.execute(text("""
            DELETE FROM major_retailer_event_outbox
            WHERE outbox_key = :outbox_key
        """), {"outbox_key": outbox_key})
        await session.commit()


async def _dispatch_outbox(retailer_key: str, *, max_events: int = 100) -> dict[str, Any]:
    key = normalize_retailer_key(retailer_key)
    if await _global_kill_switch():
        return {"emitted": 0, "failed": 0, "cooldown_suppressed": 0, "pending": 0, "errors": []}

    runtime = await _runtime_row(key)
    if bool(runtime.get("kill_switch")) or str(runtime.get("mode") or "").upper() != "PRODUCTION":
        return {"emitted": 0, "failed": 0, "cooldown_suppressed": 0, "pending": 0, "errors": []}

    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT *
            FROM major_retailer_event_outbox
            WHERE retailer_key = :retailer_key
            ORDER BY created_at ASC
            LIMIT :limit
        """), {"retailer_key": key, "limit": max(1, min(int(max_events), 200))})
        rows = [dict(row) for row in result.mappings().all()]

    emitted = 0
    failed = 0
    cooldown_suppressed = 0
    errors: list[str] = []

    for row in rows:
        event_type = _upper(row.get("event_type"))
        guard_key = str(row.get("guard_key") or "")
        cooldown = EVENT_COOLDOWNS_SECONDS.get(event_type, 120)

        if guard_key and await _guard_recent(guard_key, cooldown):
            cooldown_suppressed += 1
            _STATUS["events_blocked_cooldown_total"] += 1
            await _delete_outbox(str(row.get("outbox_key")))
            continue

        try:
            payload = json.loads(str(row.get("payload") or "{}"))
            event = _event_from_payload(payload)
            redis_saved = await push_product_event(event)
            if not redis_saved:
                raise RuntimeError("REDIS_QUEUE_FAILED")

            # Queue delivery is authoritative. Database event history is saved
            # after the Redis queue accepts the event; the durable outbox itself
            # remains the fallback audit record until this point.
            database_saved = await save_product_event(event)
            if not database_saved:
                errors.append(f"{event_type}:EVENT_HISTORY_SAVE_FAILED")

            await _delete_outbox(str(row.get("outbox_key")))
            if guard_key:
                await _mark_guard(
                    event_key=guard_key,
                    retailer_key=key,
                    external_product_id=str(row.get("external_product_id") or ""),
                    event_type=event_type,
                )
            emitted += 1
            _STATUS["events_emitted_total"] += 1

        except Exception as error:
            failed += 1
            message = f"{event_type}:{type(error).__name__}:{error}"
            errors.append(message)
            async with SessionLocal() as session:
                await session.execute(text("""
                    UPDATE major_retailer_event_outbox
                    SET attempts = attempts + 1,
                        last_error = :last_error,
                        last_attempt_at = CURRENT_TIMESTAMP
                    WHERE outbox_key = :outbox_key
                """), {
                    "last_error": message[:1000],
                    "outbox_key": str(row.get("outbox_key")),
                })
                await session.commit()

    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT COUNT(*)
            FROM major_retailer_event_outbox
            WHERE retailer_key = :retailer_key
        """), {"retailer_key": key})
        pending = int(result.scalar_one() or 0)

    return {
        "emitted": emitted,
        "failed": failed,
        "cooldown_suppressed": cooldown_suppressed,
        "pending": pending,
        "errors": errors[:8],
    }


async def _snapshot_count(retailer_key: str) -> int:
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT COUNT(*)
            FROM major_retailer_snapshots
            WHERE retailer_key = :retailer_key
        """), {"retailer_key": normalize_retailer_key(retailer_key)})
        return int(result.scalar_one() or 0)


async def _load_snapshot(
    session,
    *, retailer_key: str, external_product_id: str,
) -> dict[str, Any] | None:
    result = await session.execute(text("""
        SELECT *
        FROM major_retailer_snapshots
        WHERE retailer_key = :retailer_key
          AND external_product_id = :external_product_id
        LIMIT 1
    """), {
        "retailer_key": normalize_retailer_key(retailer_key),
        "external_product_id": str(external_product_id),
    })
    row = result.mappings().first()
    return dict(row) if row else None


def _candidate_events(
    *, old: dict[str, Any] | None, item: dict[str, Any], baseline_seed: bool, now: datetime,
) -> list[dict[str, Any]]:
    if baseline_seed:
        return []

    new_state = _availability_state(item)
    new_known = _availability_known(item)
    new_lifecycle = _lifecycle_state(item)
    new_price = _float(item.get("price"))
    new_release = _release_date(item)

    events: list[dict[str, Any]] = []

    if old is None:
        # One useful primary event for a newly discovered product; avoid
        # duplicate DISCOVERED + STOCK_AVAILABLE/PREORDER noise.
        if new_lifecycle == "PREORDER" or (new_known and new_state == "PREORDER"):
            events.append({"event_type": "PREORDER_LIVE"})
        elif new_lifecycle == "COMING_SOON":
            events.append({"event_type": "COMING_SOON"})
        elif new_lifecycle == "PAGE_LIVE":
            events.append({"event_type": "PAGE_LIVE"})
        elif new_known and new_state == "IN_STOCK":
            events.append({"event_type": "STOCK_AVAILABLE"})
        else:
            events.append({"event_type": "DISCOVERED"})
        return events

    old_state = _upper(old.get("availability_state"), "UNKNOWN")
    old_known = bool(old.get("availability_known"))
    old_lifecycle = _upper(old.get("lifecycle_state"), "UNKNOWN")
    old_price = _float(old.get("price"))
    old_release = _clean(old.get("release_date")) or None

    # Lifecycle transitions.
    if new_lifecycle != old_lifecycle:
        if new_lifecycle == "PREORDER":
            events.append({"event_type": "PREORDER_LIVE"})
        elif new_lifecycle == "COMING_SOON":
            events.append({"event_type": "COMING_SOON"})
        elif new_lifecycle == "PAGE_LIVE":
            events.append({"event_type": "PAGE_LIVE"})

    # Online availability transitions. Unknown never creates SOLD_OUT.
    availability_changed = False
    if new_known:
        if old_known:
            if new_state != old_state:
                availability_changed = True
                if new_state == "IN_STOCK":
                    if old_state == "OUT_OF_STOCK":
                        events.append({"event_type": "RESTOCK"})
                    else:
                        events.append({"event_type": "STOCK_AVAILABLE"})
                elif new_state == "OUT_OF_STOCK" and old_state in {"IN_STOCK", "PREORDER"}:
                    events.append({"event_type": "SOLD_OUT"})
                elif new_state == "PREORDER" and old_state != "PREORDER":
                    events.append({"event_type": "PREORDER_LIVE"})
        else:
            if new_state == "IN_STOCK":
                events.append({"event_type": "STOCK_AVAILABLE"})
            elif new_state == "PREORDER":
                events.append({"event_type": "PREORDER_LIVE"})
            # UNKNOWN -> OUT_OF_STOCK intentionally emits nothing.

    # Rapid verified stock movement gets a separate Premium+ flicker event.
    if availability_changed and {old_state, new_state}.issubset({"IN_STOCK", "OUT_OF_STOCK"}):
        changed_at = old.get("availability_changed_at")
        if isinstance(changed_at, datetime):
            age = (now - changed_at).total_seconds()
            if 0 <= age <= FLICKER_WINDOW_SECONDS:
                events.append({"event_type": "INVENTORY_FLICKER"})

    # Price changes only when both values are known.
    if old_price is not None and new_price is not None and abs(new_price - old_price) >= 0.01:
        if new_price < old_price:
            events.append({"event_type": "PRICE_DROP", "old_price": old_price})
        else:
            events.append({"event_type": "PRICE_INCREASE", "old_price": old_price})

    if old_release and new_release and old_release != new_release:
        events.append({
            "event_type": "RELEASE_DATE_CHANGED",
            "old_release_date": old_release,
        })

    # Remove duplicates while preserving order.
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        key = str(event.get("event_type"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


async def _upsert_snapshot(
    session,
    *, retailer_key: str, item: dict[str, Any], old: dict[str, Any] | None, now: datetime,
) -> None:
    external_id = str(item.get("external_product_id") or item.get("external_id") or "").strip()
    availability_state = _availability_state(item)
    availability_known = _availability_known(item)
    price = _float(item.get("price"))
    release_date = _release_date(item)

    if old is None:
        availability_changed_at = now if availability_known else None
        price_changed_at = now if price is not None else None
        release_changed_at = now if release_date else None
    else:
        old_state = _upper(old.get("availability_state"), "UNKNOWN")
        old_known = bool(old.get("availability_known"))
        availability_changed_at = old.get("availability_changed_at")
        if availability_known and (not old_known or availability_state != old_state):
            availability_changed_at = now

        old_price = _float(old.get("price"))
        price_changed_at = old.get("price_changed_at")
        if price is not None and old_price is not None and abs(price - old_price) >= 0.01:
            price_changed_at = now
        elif price is not None and old_price is None:
            price_changed_at = now

        old_release = _clean(old.get("release_date")) or None
        release_changed_at = old.get("release_date_changed_at")
        if release_date and release_date != old_release:
            release_changed_at = now

    await session.execute(text("""
        INSERT INTO major_retailer_snapshots (
            retailer_key, external_product_id, title, game, url,
            price, currency,
            availability_state, availability_known, availability_confidence,
            lifecycle_state, lifecycle_confidence,
            product_type, product_category, product_family,
            image_url, sku, offer_id, purchase_limit,
            release_date, exact_inventory_quantity, source_confidence,
            platform_data, first_seen_at, last_seen_at,
            availability_changed_at, price_changed_at, release_date_changed_at
        ) VALUES (
            :retailer_key, :external_product_id, :title, :game, :url,
            :price, :currency,
            :availability_state, :availability_known, :availability_confidence,
            :lifecycle_state, :lifecycle_confidence,
            :product_type, :product_category, :product_family,
            :image_url, :sku, :offer_id, :purchase_limit,
            :release_date, :exact_inventory_quantity, :source_confidence,
            :platform_data, :now, :now,
            :availability_changed_at, :price_changed_at, :release_date_changed_at
        )
        ON CONFLICT (retailer_key, external_product_id)
        DO UPDATE SET
            title = EXCLUDED.title,
            game = EXCLUDED.game,
            url = EXCLUDED.url,
            price = EXCLUDED.price,
            currency = EXCLUDED.currency,
            availability_state = EXCLUDED.availability_state,
            availability_known = EXCLUDED.availability_known,
            availability_confidence = EXCLUDED.availability_confidence,
            lifecycle_state = EXCLUDED.lifecycle_state,
            lifecycle_confidence = EXCLUDED.lifecycle_confidence,
            product_type = EXCLUDED.product_type,
            product_category = EXCLUDED.product_category,
            product_family = EXCLUDED.product_family,
            image_url = EXCLUDED.image_url,
            sku = EXCLUDED.sku,
            offer_id = EXCLUDED.offer_id,
            purchase_limit = EXCLUDED.purchase_limit,
            release_date = EXCLUDED.release_date,
            exact_inventory_quantity = EXCLUDED.exact_inventory_quantity,
            source_confidence = EXCLUDED.source_confidence,
            platform_data = EXCLUDED.platform_data,
            last_seen_at = EXCLUDED.last_seen_at,
            availability_changed_at = EXCLUDED.availability_changed_at,
            price_changed_at = EXCLUDED.price_changed_at,
            release_date_changed_at = EXCLUDED.release_date_changed_at
    """), {
        "retailer_key": normalize_retailer_key(retailer_key),
        "external_product_id": external_id,
        "title": _clean(item.get("title"), "Unknown Product"),
        "game": _clean(item.get("game"), "Unknown"),
        "url": _clean(item.get("url")),
        "price": price,
        "currency": _upper(item.get("currency"), "USD"),
        "availability_state": availability_state,
        "availability_known": availability_known,
        "availability_confidence": _availability_confidence(item),
        "lifecycle_state": _lifecycle_state(item),
        "lifecycle_confidence": _lifecycle_confidence(item),
        "product_type": _clean(item.get("product_type"), "TCG Product"),
        "product_category": _upper(item.get("product_category"), "UNKNOWN"),
        "product_family": _upper(item.get("product_family"), "UNKNOWN"),
        "image_url": _clean(item.get("image_url")) or None,
        "sku": _clean(item.get("sku")) or None,
        "offer_id": _clean(item.get("offer_id")) or None,
        "purchase_limit": _int(item.get("purchase_limit")),
        "release_date": release_date,
        "exact_inventory_quantity": _inventory_quantity(item),
        "source_confidence": _source_confidence(item),
        "platform_data": json.dumps(_platform_data(item), sort_keys=True, default=str),
        "now": now,
        "availability_changed_at": availability_changed_at,
        "price_changed_at": price_changed_at,
        "release_date_changed_at": release_changed_at,
    })


def _build_event(
    *, retailer_key: str, definition, item: dict[str, Any], event_spec: dict[str, Any],
) -> ProductEvent:
    event_type = ProductEventType(str(event_spec["event_type"]))
    availability_state = _availability_state(item)
    in_stock = availability_state in {"IN_STOCK", "PREORDER"}
    family = _upper(item.get("product_family"), "UNKNOWN")
    language = {
        "GLOBAL_STANDARD": "English",
        "JP": "Japanese",
        "KR": "Korean",
        "CN": "Simplified Chinese",
        "UNKNOWN": "Unknown",
    }.get(family, "Unknown")

    kwargs = {
        "event_type": event_type,
        "game": _clean(item.get("game"), "Unknown"),
        "product_name": _clean(item.get("title"), "Unknown Product"),
        "store_name": str(definition.display_name),
        "product_url": _clean(item.get("url")),
        "price": _float(item.get("price")),
        "old_price": _float(event_spec.get("old_price")),
        "currency": _upper(item.get("currency"), "USD"),
        "in_stock": in_stock,
        "region": _upper(item.get("region") or definition.region, "US"),
        "language": language,
        "product_type": _clean(item.get("product_type"), "TCG Product"),
        "product_category": _upper(item.get("product_category"), "UNKNOWN"),
        "source_type": "major_retailer",
        "retailer_key": normalize_retailer_key(retailer_key),
        "image_url": _clean(item.get("image_url")) or None,
        "variant_id": _clean(item.get("variant_id")) or None,
        "purchase_limit": _int(item.get("purchase_limit")),
        "cart_base_url": _clean(item.get("cart_base_url")) or None,
        "product_family": family,
        "external_product_id": _clean(item.get("external_product_id") or item.get("external_id")),
        "availability_state": availability_state,
        "availability_known": _availability_known(item),
        "availability_confidence": _availability_confidence(item),
        "lifecycle_state": _lifecycle_state(item),
        "source_confidence": _source_confidence(item),
        "release_date": _release_date(item),
        "old_release_date": _clean(event_spec.get("old_release_date")) or None,
        "exact_inventory_quantity": _inventory_quantity(item),
    }

    # Events.py in 1.0.6 accepts the extended fields. The fallback keeps this
    # module tolerant if deploy order briefly leaves an older events.py loaded.
    try:
        return ProductEvent(**kwargs)
    except TypeError:
        core_keys = {
            "event_type", "game", "product_name", "store_name", "product_url",
            "price", "old_price", "currency", "in_stock", "region", "language",
            "product_type", "product_category", "source_type", "retailer_key",
            "image_url", "variant_id", "purchase_limit", "cart_base_url",
        }
        event = ProductEvent(**{key: value for key, value in kwargs.items() if key in core_keys})
        for key, value in kwargs.items():
            if key not in core_keys:
                setattr(event, key, value)
        return event


async def _update_runtime_scan(
    *, retailer_key: str, store_id: int | None, mode: str, signature: str | None,
    success: bool, error: str | None, accepted: int, rejected: int,
    candidate_events: int, emitted_events: int, validation_pass: bool | None = None,
    probe_success: bool | None = None, baseline_ready: bool | None = None,
) -> dict[str, Any]:
    key = normalize_retailer_key(retailer_key)
    await _ensure_runtime_row(key)

    async with SessionLocal() as session:
        current_result = await session.execute(text("""
            SELECT * FROM major_retailer_runtime WHERE retailer_key = :retailer_key
        """), {"retailer_key": key})
        current = dict(current_result.mappings().first() or {})

        validation_passes = int(current.get("validation_passes", 0) or 0)
        validation_failures = int(current.get("validation_failures", 0) or 0)
        consecutive_failures = int(current.get("consecutive_failures", 0) or 0)
        validated_signature = current.get("validated_signature")

        if mode == "VALIDATION" and validation_pass is not None:
            if validation_pass:
                validation_passes += 1
                consecutive_failures = 0
                if signature:
                    validated_signature = signature
            else:
                validation_failures += 1
                consecutive_failures += 1
                # Promotion requires consecutive clean validations. Any failed
                # validation resets the pass streak and validated signature.
                validation_passes = 0
                validated_signature = None
        elif success:
            consecutive_failures = 0
        else:
            consecutive_failures += 1

        actual_mode = str(current.get("mode") or "VALIDATION").upper()
        auto_demoted = False
        if actual_mode == "PRODUCTION" and consecutive_failures >= AUTO_DEMOTE_FAILURES:
            actual_mode = "VALIDATION"
            validated_signature = None
            validation_passes = 0
            auto_demoted = True
            error = error or "AUTO_DEMOTED_AFTER_CONSECUTIVE_FAILURES"

        await session.execute(text("""
            UPDATE major_retailer_runtime
            SET store_id = COALESCE(:store_id, store_id),
                mode = :actual_mode,
                baseline_ready = COALESCE(:baseline_ready, baseline_ready),
                validation_passes = :validation_passes,
                validation_failures = :validation_failures,
                consecutive_failures = :consecutive_failures,
                last_probe_success = COALESCE(:probe_success, last_probe_success),
                last_validation_at = CASE WHEN :mode = 'VALIDATION' THEN CURRENT_TIMESTAMP ELSE last_validation_at END,
                last_scan_at = CURRENT_TIMESTAMP,
                last_success_at = CASE WHEN :success THEN CURRENT_TIMESTAMP ELSE last_success_at END,
                last_error = :last_error,
                validated_signature = :validated_signature,
                last_adapter_signature = COALESCE(:signature, last_adapter_signature),
                last_accepted = :accepted,
                last_rejected = :rejected,
                last_candidate_events = :candidate_events,
                last_emitted_events = :emitted_events,
                updated_at = CURRENT_TIMESTAMP
            WHERE retailer_key = :retailer_key
        """), {
            "retailer_key": key,
            "store_id": store_id,
            "actual_mode": actual_mode,
            "baseline_ready": baseline_ready,
            "validation_passes": validation_passes,
            "validation_failures": validation_failures,
            "consecutive_failures": consecutive_failures,
            "probe_success": probe_success,
            "mode": mode,
            "success": bool(success),
            "last_error": error,
            "validated_signature": validated_signature,
            "signature": signature,
            "accepted": int(accepted),
            "rejected": int(rejected),
            "candidate_events": int(candidate_events),
            "emitted_events": int(emitted_events),
        })
        await session.commit()

    if auto_demoted:
        store = await _find_staged_store(key)
        if store is not None:
            async with SessionLocal() as session:
                result = await session.execute(select(Store).where(Store.id == int(store.id)).limit(1))
                db_store = result.scalar_one_or_none()
                if db_store is not None:
                    db_store.active = False
                    db_store.disabled_reason = f"MAJOR_RETAILER_AUTO_DEMOTED:{key}"[:240]
                    await session.commit()

    return await _runtime_row(key)


async def validate_major_retailer(retailer_key: str, *, limit: int = 20) -> dict[str, Any]:
    """Run health probe + persistent silent validation. Never emits product events."""
    key = normalize_retailer_key(retailer_key)
    definition = get_major_retailer_definition(key)
    if definition is None:
        return {"success": False, "retailer_key": key, "error": "UNKNOWN_RETAILER"}
    if get_major_retailer_adapter_class(key) is None:
        return {"success": False, "retailer_key": key, "error": "ADAPTER_NOT_REGISTERED"}

    await _ensure_runtime_row(key)
    store_id = await _bind_store_if_available(key)
    probe = await probe_major_retailer(key)

    if not probe.get("success"):
        runtime = await _update_runtime_scan(
            retailer_key=key,
            store_id=store_id,
            mode="VALIDATION",
            signature=None,
            success=False,
            error=str(probe.get("error") or (probe.get("probe") or {}).get("message") or "PROBE_FAILED"),
            accepted=0,
            rejected=0,
            candidate_events=0,
            emitted_events=0,
            validation_pass=False,
            probe_success=False,
            baseline_ready=None,
        )
        return {
            "success": False,
            "retailer_key": key,
            "display_name": definition.display_name,
            "error": runtime.get("last_error") or "PROBE_FAILED",
            "probe": probe,
            "runtime": runtime,
            "production_events": 0,
        }

    result = await run_major_retailer_pipeline_scan(
        key,
        limit=limit,
        force_validation=True,
        probe_success=True,
    )
    result["probe"] = probe
    return result


async def run_major_retailer_pipeline_scan(
    retailer_key: str,
    *,
    limit: int = 50,
    force_validation: bool = False,
    probe_success: bool | None = None,
) -> dict[str, Any]:
    """Run a persistent major-retailer scan through the production gate."""

    key = normalize_retailer_key(retailer_key)
    definition = get_major_retailer_definition(key)
    if definition is None:
        return {"success": False, "retailer_key": key, "error": "UNKNOWN_RETAILER"}
    if get_major_retailer_adapter_class(key) is None:
        return {"success": False, "retailer_key": key, "error": "ADAPTER_NOT_REGISTERED"}

    await ensure_major_pipeline_schema()

    async with _scan_lock(key):
        started = time.monotonic()
        runtime = await _runtime_row(key)
        store_id = await _bind_store_if_available(key)
        global_kill = await _global_kill_switch()

        requested_mode = "VALIDATION" if force_validation else str(runtime.get("mode") or "VALIDATION").upper()
        production_requested = requested_mode == "PRODUCTION"
        retailer_kill = bool(runtime.get("kill_switch"))

        scan = await scan_major_retailer(key, limit=limit, suppress_events=True)
        if not scan.get("success"):
            runtime = await _update_runtime_scan(
                retailer_key=key,
                store_id=store_id,
                mode=requested_mode,
                signature=None,
                success=False,
                error=str(scan.get("error") or "SCAN_FAILED"),
                accepted=int(scan.get("accepted", 0) or 0),
                rejected=int(scan.get("rejected", 0) or 0),
                candidate_events=0,
                emitted_events=0,
                validation_pass=False if requested_mode == "VALIDATION" else None,
                probe_success=probe_success,
                baseline_ready=None,
            )
            _STATUS["last_scan_retailer"] = key
            _STATUS["last_scan_mode"] = requested_mode
            _STATUS["last_scan_success"] = False
            _STATUS["last_error"] = runtime.get("last_error")
            return {
                **scan,
                "pipeline_mode": requested_mode,
                "runtime": runtime,
                "events_emitted": 0,
            }

        signature = _adapter_signature(key, scan)

        # A production adapter/capability change forces revalidation before any
        # events can be emitted.
        signature_changed = bool(
            production_requested
            and runtime.get("validated_signature")
            and runtime.get("validated_signature") != signature
        )
        if signature_changed:
            async with SessionLocal() as session:
                await session.execute(text("""
                    UPDATE major_retailer_runtime
                    SET mode = 'VALIDATION',
                        validation_passes = 0,
                        validated_signature = NULL,
                        last_error = 'ADAPTER_SIGNATURE_CHANGED_REVALIDATION_REQUIRED',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE retailer_key = :retailer_key
                """), {"retailer_key": key})
                await session.commit()
            production_requested = False
            requested_mode = "VALIDATION"
            runtime = await _runtime_row(key)

            store = await _find_staged_store(key)
            if store is not None:
                async with SessionLocal() as session:
                    row = await session.execute(select(Store).where(Store.id == int(store.id)).limit(1))
                    db_store = row.scalar_one_or_none()
                    if db_store is not None:
                        db_store.active = False
                        db_store.disabled_reason = f"MAJOR_RETAILER_REVALIDATION:{key}"[:240]
                        await session.commit()

        quality_pass, quality_reasons, metrics = _scan_quality(scan)
        if not quality_pass:
            error = "VALIDATION_FAILED:" + ",".join(quality_reasons)
            runtime = await _update_runtime_scan(
                retailer_key=key,
                store_id=store_id,
                mode=requested_mode,
                signature=signature,
                success=False,
                error=error,
                accepted=int(scan.get("accepted", 0) or 0),
                rejected=int(scan.get("rejected", 0) or 0),
                candidate_events=0,
                emitted_events=0,
                validation_pass=False if requested_mode == "VALIDATION" else None,
                probe_success=probe_success,
                baseline_ready=None,
            )
            _STATUS["last_scan_retailer"] = key
            _STATUS["last_scan_mode"] = requested_mode
            _STATUS["last_scan_success"] = False
            _STATUS["last_error"] = error
            return {
                **scan,
                "success": False,
                "pipeline_mode": requested_mode,
                "error": error,
                "quality_reasons": quality_reasons,
                "quality_metrics": metrics,
                "runtime": runtime,
                "events_emitted": 0,
            }

        products = list(scan.get("normalized_products") or [])
        baseline_seed = (await _snapshot_count(key)) == 0
        now = _utcnow()
        candidate_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        snapshots_upserted = 0
        unknown_stock_ignored = 0

        async with SessionLocal() as session:
            for item in products:
                external_id = str(item.get("external_product_id") or item.get("external_id") or "").strip()
                if not external_id:
                    continue

                old = await _load_snapshot(
                    session,
                    retailer_key=key,
                    external_product_id=external_id,
                )

                if old is not None and bool(old.get("availability_known")) and not _availability_known(item):
                    # This is deliberately informational only. We update the
                    # snapshot to UNKNOWN, but never infer SOLD_OUT.
                    unknown_stock_ignored += 1

                for event_spec in _candidate_events(
                    old=old,
                    item=item,
                    baseline_seed=baseline_seed,
                    now=now,
                ):
                    candidate_records.append((item, event_spec))

                await _upsert_snapshot(
                    session,
                    retailer_key=key,
                    item=item,
                    old=old,
                    now=now,
                )
                snapshots_upserted += 1

            await session.commit()

        _STATUS["unknown_stock_ignored_total"] += unknown_stock_ignored

        production_active = bool(
            production_requested
            and not force_validation
            and not global_kill
            and not retailer_kill
            and key not in PRODUCTION_BLOCKS
            and runtime.get("validated_signature") == signature
            and int(runtime.get("validation_passes", 0) or 0) >= VALIDATION_PASSES_REQUIRED
            and bool(runtime.get("baseline_ready"))
        )

        emitted = 0
        outbox_enqueued = 0
        outbox_failed = 0
        outbox_pending = 0
        blocked_capability = 0
        blocked_confidence = 0
        blocked_cooldown = 0
        suppressed_validation = 0
        event_errors: list[str] = []

        for item, event_spec in candidate_records:
            event_type = str(event_spec.get("event_type") or "")
            allowed, block_reason = _event_allowed_by_capability(
                event_type,
                dict(scan.get("capabilities") or {}),
                item,
            )
            if not allowed:
                if block_reason == "STOCK_CONFIDENCE_TOO_LOW":
                    blocked_confidence += 1
                    _STATUS["events_blocked_confidence_total"] += 1
                else:
                    blocked_capability += 1
                    _STATUS["events_blocked_capability_total"] += 1
                continue

            if not production_active:
                suppressed_validation += 1
                _STATUS["events_suppressed_validation_total"] += 1
                continue

            external_id = str(item.get("external_product_id") or item.get("external_id") or "")
            event_key = _event_identity(key, external_id, event_type, item)
            cooldown = EVENT_COOLDOWNS_SECONDS.get(_upper(event_type), 120)
            if await _guard_recent(event_key, cooldown):
                blocked_cooldown += 1
                _STATUS["events_blocked_cooldown_total"] += 1
                continue

            try:
                product_event = _build_event(
                    retailer_key=key,
                    definition=definition,
                    item=item,
                    event_spec=event_spec,
                )
                if await _enqueue_outbox(
                    retailer_key=key,
                    external_product_id=external_id,
                    event_type=event_type,
                    guard_key=event_key,
                    event=product_event,
                    transition_at=now,
                ):
                    outbox_enqueued += 1
            except Exception as error:
                event_errors.append(f"{event_type}:OUTBOX:{type(error).__name__}:{error}")

        # Dispatch only after the current scan itself passed quality, signature,
        # capability and production gates. Redis outages leave durable pending
        # rows instead of losing the state transition after snapshot persistence.
        if production_active:
            dispatch = await _dispatch_outbox(key)
            emitted = int(dispatch.get("emitted", 0) or 0)
            outbox_failed = int(dispatch.get("failed", 0) or 0)
            outbox_pending = int(dispatch.get("pending", 0) or 0)
            blocked_cooldown += int(dispatch.get("cooldown_suppressed", 0) or 0)
            event_errors.extend(list(dispatch.get("errors") or []))

        validation_pass = True if requested_mode == "VALIDATION" else None
        baseline_ready = True if products else None

        runtime = await _update_runtime_scan(
            retailer_key=key,
            store_id=store_id,
            mode=requested_mode,
            signature=signature,
            success=True,
            error=(";".join(event_errors[:4]) if event_errors else None),
            accepted=int(scan.get("accepted", 0) or 0),
            rejected=int(scan.get("rejected", 0) or 0),
            candidate_events=len(candidate_records),
            emitted_events=emitted,
            validation_pass=validation_pass,
            probe_success=probe_success,
            baseline_ready=baseline_ready,
        )

        _STATUS["last_scan_retailer"] = key
        _STATUS["last_scan_mode"] = "PRODUCTION" if production_active else "VALIDATION"
        _STATUS["last_scan_success"] = True
        _STATUS["last_error"] = event_errors[0] if event_errors else None

        gate = await get_major_promotion_gate(key)

        return {
            **scan,
            "success": True,
            "pipeline_mode": "PRODUCTION" if production_active else "VALIDATION",
            "production_active": production_active,
            "global_kill_switch": global_kill,
            "retailer_kill_switch": retailer_kill,
            "hard_production_block": PRODUCTION_BLOCKS.get(key),
            "adapter_signature": signature,
            "signature_changed": signature_changed,
            "initial_baseline": baseline_seed,
            "snapshots_upserted": snapshots_upserted,
            "candidate_events": len(candidate_records),
            "events_emitted": emitted,
            "outbox_enqueued": outbox_enqueued,
            "outbox_failed": outbox_failed,
            "outbox_pending": outbox_pending,
            "events_suppressed_validation": suppressed_validation,
            "events_blocked_capability": blocked_capability,
            "events_blocked_confidence": blocked_confidence,
            "events_blocked_cooldown": blocked_cooldown,
            "unknown_stock_ignored": unknown_stock_ignored,
            "missing_product_inference_events": 0,
            "quality_reasons": quality_reasons,
            "quality_metrics": metrics,
            "runtime": runtime,
            "promotion_gate": gate,
            "elapsed_pipeline_ms": int((time.monotonic() - started) * 1000),
        }


async def get_major_promotion_gate(retailer_key: str) -> dict[str, Any]:
    key = normalize_retailer_key(retailer_key)
    definition = get_major_retailer_definition(key)
    runtime = await _runtime_row(key)
    store = await _find_staged_store(key)
    global_kill = await _global_kill_switch()

    reasons: list[str] = []
    if definition is None:
        reasons.append("UNKNOWN_RETAILER")
    if get_major_retailer_adapter_class(key) is None:
        reasons.append("ADAPTER_NOT_REGISTERED")
    if key in PRODUCTION_BLOCKS:
        reasons.append(PRODUCTION_BLOCKS[key])
    if store is None:
        reasons.append("STAGE_RETAILER_FIRST")
    if global_kill:
        reasons.append("GLOBAL_KILL_SWITCH_ACTIVE")
    if bool(runtime.get("kill_switch")):
        reasons.append("RETAILER_KILL_SWITCH_ACTIVE")
    if not bool(runtime.get("baseline_ready")):
        reasons.append("BASELINE_NOT_READY")
    if int(runtime.get("validation_passes", 0) or 0) < VALIDATION_PASSES_REQUIRED:
        reasons.append("VALIDATION_PASSES_REQUIRED")
    if runtime.get("last_probe_success") is not True:
        reasons.append("HEALTH_PROBE_NOT_VERIFIED")
    if not runtime.get("validated_signature"):
        reasons.append("VALIDATED_ADAPTER_SIGNATURE_MISSING")
    if runtime.get("validated_signature") != runtime.get("last_adapter_signature"):
        reasons.append("ADAPTER_SIGNATURE_REVALIDATION_REQUIRED")
    if int(runtime.get("last_accepted", 0) or 0) <= 0:
        reasons.append("NO_ACCEPTED_PRODUCTS")
    if int(runtime.get("consecutive_failures", 0) or 0) > 0:
        reasons.append("LATEST_VALIDATION_NOT_CLEAN")
    if runtime.get("last_error"):
        reasons.append("RUNTIME_ERROR_PRESENT")

    return {
        "retailer_key": key,
        "display_name": definition.display_name if definition else key,
        "ready": not reasons,
        "reasons": reasons,
        "required_validation_passes": VALIDATION_PASSES_REQUIRED,
        "validation_passes": int(runtime.get("validation_passes", 0) or 0),
        "baseline_ready": bool(runtime.get("baseline_ready")),
        "staged_store_id": int(store.id) if store is not None else None,
        "global_kill_switch": global_kill,
        "retailer_kill_switch": bool(runtime.get("kill_switch")),
        "runtime_mode": str(runtime.get("mode") or "VALIDATION"),
    }


async def promote_major_retailer(retailer_key: str) -> dict[str, Any]:
    key = normalize_retailer_key(retailer_key)
    gate = await get_major_promotion_gate(key)
    if not gate.get("ready"):
        return {
            "success": False,
            "retailer_key": key,
            "error": "PROMOTION_GATE_BLOCKED",
            "gate": gate,
        }

    store = await _find_staged_store(key)
    async with SessionLocal() as session:
        await session.execute(text("""
            UPDATE major_retailer_runtime
            SET mode = 'PRODUCTION',
                kill_switch = FALSE,
                promoted_at = CURRENT_TIMESTAMP,
                last_error = NULL,
                consecutive_failures = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE retailer_key = :retailer_key
        """), {"retailer_key": key})

        if store is not None:
            result = await session.execute(select(Store).where(Store.id == int(store.id)).limit(1))
            db_store = result.scalar_one_or_none()
            if db_store is not None:
                db_store.active = True
                db_store.disabled_reason = None
        await session.commit()

    return {
        "success": True,
        "retailer_key": key,
        "mode": "PRODUCTION",
        "runtime": await _runtime_row(key),
    }


async def demote_major_retailer(retailer_key: str, *, reason: str = "MANUAL_DEMOTION") -> dict[str, Any]:
    key = normalize_retailer_key(retailer_key)
    await _ensure_runtime_row(key)
    reason = _clean(reason, "MANUAL_DEMOTION")[:180]

    store = await _find_staged_store(key)
    async with SessionLocal() as session:
        await session.execute(text("""
            UPDATE major_retailer_runtime
            SET mode = 'VALIDATION',
                last_error = :reason,
                updated_at = CURRENT_TIMESTAMP
            WHERE retailer_key = :retailer_key
        """), {"retailer_key": key, "reason": reason})

        if store is not None:
            result = await session.execute(select(Store).where(Store.id == int(store.id)).limit(1))
            db_store = result.scalar_one_or_none()
            if db_store is not None:
                db_store.active = False
                db_store.disabled_reason = f"MAJOR_RETAILER_VALIDATION:{key}"[:240]
        await session.commit()

    return {
        "success": True,
        "retailer_key": key,
        "mode": "VALIDATION",
        "runtime": await _runtime_row(key),
    }


async def set_major_kill_switch(retailer_key: str, enabled: bool) -> dict[str, Any]:
    raw = str(retailer_key or "").strip().lower()
    await ensure_major_pipeline_schema()

    if raw in {"all", "global", "*"}:
        async with SessionLocal() as session:
            await session.execute(text("""
                UPDATE major_retailer_system_control
                SET global_kill_switch = :enabled,
                    updated_at = CURRENT_TIMESTAMP
                WHERE control_key = 'GLOBAL'
            """), {"enabled": bool(enabled)})
            await session.commit()
        return {
            "success": True,
            "scope": "GLOBAL",
            "enabled": bool(enabled),
        }

    key = normalize_retailer_key(retailer_key)
    if get_major_retailer_definition(key) is None:
        return {"success": False, "retailer_key": key, "error": "UNKNOWN_RETAILER"}

    await _ensure_runtime_row(key)
    store = await _find_staged_store(key)
    runtime_before = await _runtime_row(key)

    async with SessionLocal() as session:
        await session.execute(text("""
            UPDATE major_retailer_runtime
            SET kill_switch = :enabled,
                last_error = CASE
                    WHEN :enabled THEN 'MANUAL_KILL_SWITCH'
                    ELSE NULL
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE retailer_key = :retailer_key
        """), {"enabled": bool(enabled), "retailer_key": key})

        if store is not None:
            result = await session.execute(select(Store).where(Store.id == int(store.id)).limit(1))
            db_store = result.scalar_one_or_none()
            if db_store is not None:
                if enabled:
                    db_store.active = False
                    db_store.disabled_reason = f"MAJOR_RETAILER_KILL_SWITCH:{key}"[:240]
                elif str(runtime_before.get("mode") or "VALIDATION").upper() == "PRODUCTION":
                    db_store.active = True
                    db_store.disabled_reason = None
        await session.commit()

    return {
        "success": True,
        "scope": "RETAILER",
        "retailer_key": key,
        "enabled": bool(enabled),
        "runtime": await _runtime_row(key),
    }


async def list_major_pipeline_states() -> list[dict[str, Any]]:
    await ensure_major_pipeline_schema()
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT *
            FROM major_retailer_runtime
            ORDER BY retailer_key ASC
        """))
        rows = [dict(row) for row in result.mappings().all()]

    for row in rows:
        for key in (
            "last_validation_at", "last_scan_at", "last_success_at",
            "promoted_at", "created_at", "updated_at",
        ):
            row[key] = _iso(row.get(key))
    return rows


async def get_major_pipeline_status() -> dict[str, Any]:
    await ensure_major_pipeline_schema()
    rows = await list_major_pipeline_states()
    global_kill = await _global_kill_switch()
    production = [
        row for row in rows
        if str(row.get("mode") or "").upper() == "PRODUCTION"
        and not bool(row.get("kill_switch"))
    ]
    async with SessionLocal() as session:
        pending_result = await session.execute(text("SELECT COUNT(*) FROM major_retailer_event_outbox"))
        pending_outbox = int(pending_result.scalar_one() or 0)
    return {
        **dict(_STATUS),
        "global_kill_switch": global_kill,
        "runtime_rows": len(rows),
        "production_retailers": len(production),
        "validation_retailers": len(rows) - len(production),
        "validation_passes_required": VALIDATION_PASSES_REQUIRED,
        "auto_demote_failures": AUTO_DEMOTE_FAILURES,
        "pending_outbox_events": pending_outbox,
    }


async def _production_keys() -> list[str]:
    await ensure_major_pipeline_schema()
    if await _global_kill_switch():
        return []
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT retailer_key
            FROM major_retailer_runtime
            WHERE mode = 'PRODUCTION'
              AND kill_switch = FALSE
            ORDER BY retailer_key ASC
        """))
        return [str(value) for value in result.scalars().all()]


async def run_major_retailer_monitor() -> None:
    """Background worker. Idle until a retailer passes /majorpromote."""
    await ensure_major_pipeline_schema()
    _STATUS["running"] = True

    while True:
        try:
            keys = await _production_keys()
            _STATUS["last_cycle_started_at"] = _utcnow().isoformat()
            _STATUS["last_cycle_retailers"] = len(keys)
            failures = 0

            for key in keys:
                _STATUS["current_retailer"] = key
                try:
                    result = await run_major_retailer_pipeline_scan(
                        key,
                        limit=BACKGROUND_SCAN_LIMIT,
                        force_validation=False,
                    )
                    if not result.get("success"):
                        failures += 1
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failures += 1
                    _STATUS["last_error"] = f"{key}:{type(error).__name__}:{error}"

            _STATUS["current_retailer"] = None
            _STATUS["last_cycle_failures"] = failures
            _STATUS["last_cycle_completed_at"] = _utcnow().isoformat()

            await asyncio.sleep(BACKGROUND_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            _STATUS["running"] = False
            raise
        except Exception as error:
            _STATUS["last_error"] = f"MONITOR:{type(error).__name__}:{error}"
            await asyncio.sleep(15)
