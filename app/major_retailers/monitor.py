"""
Lotus Major Retailer Monitor Foundation
Step 6K-1C

This milestone intentionally does not start background polling. It provides
registry, normalization, safety validation, health/probe orchestration and a
controlled scan contract. Retailer adapters become active only after their
own silent validation milestone.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import MajorRetailerProduct
from .registry import (
    build_major_retailer_adapter,
    get_major_retailer_adapter_class,
    get_major_retailer_definition,
    list_major_retailer_definitions,
    list_registered_major_retailer_adapters,
    normalize_retailer_key,
)

VERSION = "1.2.0"
FRAMEWORK_STEP = "6K-1C"
DEFAULT_SCAN_TIMEOUT_SECONDS = 75
MAX_SCAN_PRODUCTS = 200

_STATUS: dict[str, Any] = {
    "version": VERSION,
    "step": FRAMEWORK_STEP,
    "running": False,
    "background_monitor_enabled": False,
    "definitions_loaded": 0,
    "adapters_registered": 0,
    "last_probe_retailer": None,
    "last_probe_success": None,
    "last_scan_retailer": None,
    "last_scan_success": None,
    "last_error": None,
    "last_scan_products": 0,
    "last_scan_rejected": 0,
    "stock_safety": "UNKNOWN_NEVER_BECOMES_STOCK_EVENT",
    "local_inventory_separated": True,
}


def _refresh_counts() -> None:
    _STATUS["definitions_loaded"] = len(list_major_retailer_definitions())
    _STATUS["adapters_registered"] = len(list_registered_major_retailer_adapters())


def get_major_retailer_framework_status() -> dict[str, Any]:
    _refresh_counts()
    return dict(_STATUS)


def get_major_retailer_catalog_status() -> list[dict[str, Any]]:
    adapter_keys = set(list_registered_major_retailer_adapters())
    rows = []
    for definition in list_major_retailer_definitions():
        rows.append({
            **definition.to_dict(),
            "adapter_registered": definition.key in adapter_keys,
            "production_ready": bool(definition.enabled and definition.key in adapter_keys),
        })
    return rows


async def probe_major_retailer(key: str) -> dict[str, Any]:
    normalized = normalize_retailer_key(key)
    _STATUS["last_probe_retailer"] = normalized
    _STATUS["last_error"] = None

    definition = get_major_retailer_definition(normalized)
    if definition is None:
        _STATUS["last_probe_success"] = False
        _STATUS["last_error"] = "UNKNOWN_RETAILER"
        return {
            "success": False,
            "retailer_key": normalized,
            "error": "UNKNOWN_RETAILER",
        }

    if get_major_retailer_adapter_class(normalized) is None:
        _STATUS["last_probe_success"] = False
        return {
            "success": False,
            "retailer_key": normalized,
            "display_name": definition.display_name,
            "domain": definition.domain,
            "error": "ADAPTER_NOT_REGISTERED",
            "planned": True,
        }

    try:
        adapter = build_major_retailer_adapter(normalized)
        probe = await asyncio.wait_for(
            adapter.healthcheck(),
            timeout=DEFAULT_SCAN_TIMEOUT_SECONDS,
        )
        _STATUS["last_probe_success"] = bool(probe.success)
        if not probe.success:
            _STATUS["last_error"] = probe.message or "HEALTHCHECK_FAILED"
        return {
            "success": bool(probe.success),
            "retailer_key": normalized,
            "display_name": definition.display_name,
            "domain": definition.domain,
            "probe": probe.to_dict(),
            "capabilities": adapter.capabilities.to_dict(),
            "diagnostics": adapter.get_diagnostics(),
        }
    except asyncio.TimeoutError:
        _STATUS["last_probe_success"] = False
        _STATUS["last_error"] = "PROBE_TIMEOUT"
        return {"success": False, "retailer_key": normalized, "error": "PROBE_TIMEOUT"}
    except Exception as error:
        _STATUS["last_probe_success"] = False
        _STATUS["last_error"] = f"PROBE_ERROR:{type(error).__name__}"
        return {
            "success": False,
            "retailer_key": normalized,
            "error": f"PROBE_ERROR:{type(error).__name__}:{error}",
        }


async def scan_major_retailer(
    key: str,
    *,
    limit: int = 50,
    suppress_events: bool = True,
) -> dict[str, Any]:
    """
    Controlled adapter scan contract.

    Step 6K-1C validates and normalizes retailer output only. It does not
    persist products or publish Discord events. Persistence/event wiring is
    enabled retailer-by-retailer after silent validation.
    """

    started = time.monotonic()
    normalized = normalize_retailer_key(key)
    _STATUS["last_scan_retailer"] = normalized
    _STATUS["last_scan_success"] = False
    _STATUS["last_scan_products"] = 0
    _STATUS["last_scan_rejected"] = 0
    _STATUS["last_error"] = None

    definition = get_major_retailer_definition(normalized)
    if definition is None:
        _STATUS["last_error"] = "UNKNOWN_RETAILER"
        return {"success": False, "retailer_key": normalized, "error": "UNKNOWN_RETAILER"}

    adapter_class = get_major_retailer_adapter_class(normalized)
    if adapter_class is None:
        _STATUS["last_error"] = "ADAPTER_NOT_REGISTERED"
        return {
            "success": False,
            "retailer_key": normalized,
            "display_name": definition.display_name,
            "domain": definition.domain,
            "error": "ADAPTER_NOT_REGISTERED",
            "suppress_events": True,
            "products": 0,
            "accepted": 0,
            "rejected": 0,
        }

    limit = max(1, min(int(limit or 50), MAX_SCAN_PRODUCTS))

    try:
        adapter = build_major_retailer_adapter(normalized)
        raw_products = await asyncio.wait_for(
            adapter.discover_products(limit=limit),
            timeout=DEFAULT_SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        _STATUS["last_error"] = "SCAN_TIMEOUT"
        return {"success": False, "retailer_key": normalized, "error": "SCAN_TIMEOUT"}
    except Exception as error:
        _STATUS["last_error"] = f"SCAN_ERROR:{type(error).__name__}"
        return {
            "success": False,
            "retailer_key": normalized,
            "error": f"SCAN_ERROR:{type(error).__name__}:{error}",
        }

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for item in raw_products or []:
        if not isinstance(item, MajorRetailerProduct):
            rejected.append({"reason": "INVALID_PRODUCT_TYPE"})
            continue

        errors = item.validate(adapter.capabilities)
        if errors:
            rejected.append({
                "external_product_id": item.external_product_id,
                "title": item.title,
                "reason": ",".join(errors),
            })
            continue

        try:
            accepted.append(
                item.to_normalized_dict(
                    adapter.capabilities,
                    region=definition.region,
                )
            )
        except Exception as error:
            rejected.append({
                "external_product_id": item.external_product_id,
                "title": item.title,
                "reason": f"NORMALIZE_ERROR:{type(error).__name__}:{error}",
            })

    _STATUS["last_scan_success"] = True
    _STATUS["last_scan_products"] = len(accepted)
    _STATUS["last_scan_rejected"] = len(rejected)

    return {
        "success": True,
        "retailer_key": normalized,
        "display_name": definition.display_name,
        "domain": definition.domain,
        "region": definition.region,
        "production_enabled": bool(definition.enabled),
        "suppress_events": True,  # forced in foundation milestone
        "requested_limit": limit,
        "products": len(raw_products or []),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "normalized_products": accepted,
        "rejections": rejected[:20],
        "capabilities": adapter.capabilities.to_dict(),
        "diagnostics": adapter.get_diagnostics(),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "note": "6K-1B Target silent validation only; persistence and Discord events remain disabled.",
    }
