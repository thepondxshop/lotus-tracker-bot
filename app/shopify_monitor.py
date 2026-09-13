import asyncio
import json
import time

from datetime import datetime, timezone

from sqlalchemy import (
    func,
    select,
)

from sqlalchemy.exc import (
    IntegrityError,
)

from app.database import (
    SessionLocal,
)

from app.deal_intelligence import (
    analyze_price_history,
)

from app.pricing_reference import (
    resolve_reference_price,
)

from app.event_service import (
    process_product_event,
)

from app.events import (
    ProductEvent,
    ProductEventType,
)

from app.flicker import (
    record_stock_transition,
)

from app.models import (
    PriceHistory,
    Product,
    Store,
    StoreProduct,
)

from app.product_family import (
    normalize_product_family,
)

from app.shopify_adapter import (
    ShopifyAdapter,
    ShopifyRateLimitError,
    normalize_shopify_domain,
)

from app.store_health import (
    get_health_recovery_candidates,
    manual_disable_store,
    manual_enable_store,
    mark_store_removed,
    record_store_failure,
    record_store_success,
    restore_removed_store,
)


# =========================================================
# LOTUS SHOPIFY MONITOR
# PonDeX Trackers
# Component Version 1.0.6-C4
# Step 6K-2C4 — Independent Shopify Store Scheduling
#
# Strict structured TCG classification
# Product-category diagnostics
# Historical Pricing
# Deal Score
# Hierarchical MSRP
# Product Family MSRP Isolation
# Scalper Protection
# Native Currency
# Smart Cart
# Dynamic Variant Switching
# Inventory Quantity Snapshots
# Smart Cart Quantity Guard Metadata
# Variant-Switch Price Protection
# Preorder Lifecycle Persistence
# PREORDER_PAGE -> PREORDER_LIVE Detection
# Shopify Discovery Source Persistence
# Collection Backfill Guard + Priority Membership Release Signals
# Per-domain request pacing + 429 Retry-After backoff
# Global/per-store scan overlap protection
# =========================================================


POLL_SECONDS = 5
MAX_CONCURRENT_STORE_SCANS = 4
_STORE_SCAN_CAPACITY = asyncio.Semaphore(MAX_CONCURRENT_STORE_SCANS)
_STORE_TIMINGS = {}
_STORE_RESULTS = {}
_BACKGROUND_SCANS = 0

HEALTH_PROBE_SECONDS = 300


MONITOR_STATUS = {

    "running":
        False,

    "last_scan":
        None,

    "last_health_probe":
        None,

    "stores_scanned":
        0,

    "products_seen":
        0,

    "events_created":
        0,

    "flickers_detected":
        0,

    "stores_recovered":
        0,

    "duplicate_rows_detected":
        0,

    "variant_switches":
        0,

    "inventory_quantity_changes":
        0,

    "inventory_quantity_known":
        0,

    "inventory_quantity_unknown":
        0,

    "new_product_alerts_allowed":
        0,

    "new_product_backfills_suppressed":
        0,

    "preorder_activations":
        0,

    "preorder_pages":
        0,

    "preorder_live_products":
        0,

    "sealed_products":
        0,

    "single_products":
        0,

    "accessory_products":
        0,

    "unknown_category_products":
        0,

    "global_family_products":
        0,

    "jp_family_products":
        0,

    "kr_family_products":
        0,

    "cn_family_products":
        0,

    "unknown_family_products":
        0,

    # Step 6K-2C1 diagnostics
    "scan_in_progress":
        False,

    "scan_started_at":
        None,

    "scan_finished_at":
        None,

    "scan_duration_seconds":
        None,

    "scan_skipped_overlap":
        0,

    "last_scan_outcome":
        "NOT_YET",

    "active_shopify_stores":
        0,

    "stores_failed":
        0,

    "rate_limit_responses":
        0,

    "rate_limit_retries":
        0,

    "rate_limit_backoff_seconds":
        0.0,

    "rate_limit_exhausted":
        0,

    "partial_rate_limited_scans":
        0,

    "priority_collections":
        0,

    "collection_products_seen":
        0,

    "general_products_seen":
        0,

    "general_feed_skipped":
        0,

    "new_priority_collection_memberships":
        0,

    "priority_membership_alerts":
        0,

    "last_adapter_diagnostics":
        {},

    "last_error":
        None,
}


_SHOPIFY_SCAN_LOCK = asyncio.Lock()
_STORE_SCAN_LOCKS = {}


def _get_store_scan_lock(store_id):
    key = int(store_id)
    lock = _STORE_SCAN_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _STORE_SCAN_LOCKS[key] = lock
    return lock


def get_previous_discovery_sources(store_product):
    data = load_platform_data(store_product)
    raw = data.get("shopify_discovery_sources") or []
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw]
    return {
        str(value or "").strip()
        for value in raw
        if str(value or "").strip()
    }


def _record_adapter_diagnostics(store, diagnostics):
    diagnostics = dict(diagnostics or {})
    MONITOR_STATUS["rate_limit_responses"] += int(diagnostics.get("http_429", 0) or 0)
    MONITOR_STATUS["rate_limit_retries"] += int(diagnostics.get("retries", 0) or 0)
    MONITOR_STATUS["rate_limit_backoff_seconds"] += float(diagnostics.get("backoff_seconds", 0.0) or 0.0)
    MONITOR_STATUS["rate_limit_exhausted"] += int(diagnostics.get("rate_limit_exhausted", 0) or 0)
    MONITOR_STATUS["partial_rate_limited_scans"] += int(bool(diagnostics.get("partial_due_to_rate_limit")))
    MONITOR_STATUS["priority_collections"] += int(diagnostics.get("priority_collections", 0) or 0)
    MONITOR_STATUS["collection_products_seen"] += int(diagnostics.get("collection_products_seen", 0) or 0)
    MONITOR_STATUS["general_products_seen"] += int(diagnostics.get("general_products_seen", 0) or 0)
    MONITOR_STATUS["general_feed_skipped"] += int(bool(diagnostics.get("general_feed_skipped")))
    MONITOR_STATUS["new_priority_collection_memberships"] += int(diagnostics.get("new_collection_memberships", 0) or 0)
    MONITOR_STATUS["last_adapter_diagnostics"] = {
        "store": getattr(store, "name", None),
        "domain": getattr(store, "domain", None),
        **diagnostics,
    }


def family_language(
    product_family,
):

    product_family = (
        normalize_product_family(
            product_family
        )
        or "UNKNOWN"
    )

    mapping = {

        "GLOBAL_STANDARD":
            "English",

        "JP":
            "Japanese",

        "KR":
            "Korean",

        "CN":
            "Simplified Chinese",

        "UNKNOWN":
            "Unknown",
    }

    return (
        mapping.get(
            product_family,
            "Unknown",
        )
    )


def normalize_variant_id(
    value,
):

    if value is None:

        return None

    value = (
        str(
            value
        ).strip()
    )

    if not value:

        return None

    return value


def normalize_category(
    value,
):

    value = (
        str(
            value
            or "UNKNOWN"
        )
        .strip()
        .upper()
    )

    if value not in {
        "SEALED",
        "SINGLE",
        "ACCESSORY",
        "UNKNOWN",
    }:

        return (
            "UNKNOWN"
        )

    return (
        value
    )



# =========================================================
# INVENTORY PLATFORM DATA
# =========================================================

def safe_inventory_quantity(
    value,
):

    if value is None or isinstance(
        value,
        bool,
    ):

        return None

    try:

        value = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return None

    return (
        value
        if value >= 0
        else None
    )


def load_platform_data(
    store_product,
):

    raw_value = getattr(
        store_product,
        "platform_data",
        None,
    )

    if not raw_value:

        return {}

    if isinstance(
        raw_value,
        dict,
    ):

        return dict(
            raw_value
        )

    try:

        parsed = json.loads(
            raw_value
        )

        if isinstance(
            parsed,
            dict,
        ):

            return parsed

    except Exception:

        pass

    return {}


def save_inventory_platform_data(
    store_product,
    *,
    quantity,
    quantity_known,
    variant_id,
    product_state=None,
    discovery_sources=None,
):

    if not hasattr(
        store_product,
        "platform_data",
    ):

        return

    data = (
        load_platform_data(
            store_product
        )
    )

    data[
        "shopify_inventory_quantity"
    ] = (
        quantity
        if quantity_known
        else None
    )

    data[
        "shopify_inventory_quantity_known"
    ] = bool(
        quantity_known
    )

    data[
        "shopify_inventory_variant_id"
    ] = (
        normalize_variant_id(
            variant_id
        )
    )

    data[
        "shopify_inventory_observed_at"
    ] = (
        datetime.utcnow().isoformat()
    )

    if product_state:

        data[
            "shopify_product_state"
        ] = (
            str(
                product_state
            ).strip().upper()
        )

        data[
            "shopify_product_state_observed_at"
        ] = (
            datetime.utcnow().isoformat()
        )

    if discovery_sources is not None:

        normalized_sources = []

        for source in (
            discovery_sources
            if isinstance(
                discovery_sources,
                (
                    list,
                    tuple,
                    set,
                ),
            )
            else [discovery_sources]
        ):

            source = str(
                source
                or ""
            ).strip()

            if (
                source
                and source not in normalized_sources
            ):

                normalized_sources.append(
                    source
                )

        data[
            "shopify_discovery_sources"
        ] = normalized_sources

    store_product.platform_data = (
        json.dumps(
            data,
            separators=(
                ",",
                ":",
            ),
            sort_keys=True,
        )
    )


def get_previous_inventory_snapshot(
    store_product,
):

    data = (
        load_platform_data(
            store_product
        )
    )

    known = bool(
        data.get(
            "shopify_inventory_quantity_known"
        )
    )

    quantity = (
        safe_inventory_quantity(
            data.get(
                "shopify_inventory_quantity"
            )
        )
        if known
        else None
    )

    return (
        quantity,
        known,
    )


def get_previous_product_state(
    store_product,
):

    data = (
        load_platform_data(
            store_product
        )
    )

    value = str(
        data.get(
            "shopify_product_state"
        )
        or ""
    ).strip().upper()

    return (
        value
        or None
    )


def normalize_shopify_product_state(
    value,
):

    value = str(
        value
        or "PAGE_LIVE"
    ).strip().upper()

    if value not in {
        "PAGE_LIVE",
        "COMING_SOON",
        "PREORDER_PAGE",
        "PREORDER_LIVE",
        "STOCK_AVAILABLE",
    }:

        return (
            "PAGE_LIVE"
        )

    return value


def is_preorder_title(
    value,
):

    text = str(
        value
        or ""
    ).strip().lower()

    return (
        "preorder" in text
        or "pre-order" in text
        or "pre order" in text
    )


async def add_shopify_store(
    name,
    domain,
    region="US",
):

    domain = (
        normalize_shopify_domain(
            domain
        )
    )

    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    Store
                ).where(
                    Store.domain
                    == domain
                )
            )
        )

        existing = (
            result.scalars().first()
        )

        if existing:

            existing.name = (
                name
            )

            existing.platform = (
                "shopify"
            )

            existing.region = (
                region.upper()
            )

            existing.active = (
                True
            )

            existing.health_status = (
                "HEALTHY"
            )

            existing.disabled_reason = (
                None
            )

            existing.consecutive_failures = (
                0
            )

            existing.last_error = (
                None
            )

            await session.commit()

            await session.refresh(
                existing
            )

            return (
                existing,
                False,
            )

        store = Store(

            name=(
                name
            ),

            domain=(
                domain
            ),

            platform=(
                "shopify"
            ),

            region=(
                region.upper()
            ),

            active=(
                True
            ),

            health_status=(
                "HEALTHY"
            ),

            consecutive_failures=(
                0
            ),
        )

        session.add(
            store
        )

        await session.commit()

        await session.refresh(
            store
        )

        return (
            store,
            True,
        )


async def list_shopify_stores(
    include_removed=False,
):

    async with SessionLocal() as session:

        query = (
            select(
                Store
            )
            .where(
                Store.platform
                == "shopify"
            )
            .order_by(
                Store.id.asc()
            )
        )

        if not include_removed:

            query = query.where(
                (
                    Store.disabled_reason
                    != "REMOVED"
                )
                |
                (
                    Store.disabled_reason
                    == None
                )
            )

        result = (
            await session.execute(
                query
            )
        )

        return list(
            result.scalars().all()
        )


async def get_shopify_store(
    store_id,
):

    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    Store
                ).where(
                    Store.id
                    == store_id
                )
            )
        )

        return (
            result.scalars().first()
        )


async def set_shopify_store_active(
    store_id,
    active,
):

    if active:

        return await manual_enable_store(
            store_id
        )

    return await manual_disable_store(
        store_id
    )


async def remove_shopify_store(
    store_id,
):

    return await mark_store_removed(
        store_id
    )


async def restore_shopify_store(
    store_id,
):

    return await restore_removed_store(
        store_id
    )


async def get_shopify_stores():

    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    Store
                )
                .where(
                    Store.active
                    == True
                )
                .where(
                    Store.platform
                    == "shopify"
                )
                .order_by(
                    Store.id.asc()
                )
            )
        )

        return list(
            result.scalars().all()
        )


def get_item_family(
    item,
):

    return (
        normalize_product_family(
            item.get(
                "product_family"
            )
        )
        or "UNKNOWN"
    )


def make_product_event(
    *,
    event_type,
    item,
    store,
    in_stock,
    old_price=None,
    deal_data=None,
):

    deal_fields = {}

    if deal_data is not None:

        try:

            deal_fields = (
                deal_data.to_event_fields()
            )

        except Exception as error:

            print(
                (
                    "DEAL EVENT FIELD ERROR | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

            deal_fields = {}

    product_family = (
        get_item_family(
            item
        )
    )

    return ProductEvent(

        event_type=(
            event_type
        ),

        game=(
            item[
                "game"
            ]
        ),

        product_name=(
            item[
                "title"
            ]
        ),

        store_name=(
            store.name
        ),

        product_url=(
            item[
                "url"
            ]
        ),

        price=(
            item.get(
                "price"
            )
        ),

        old_price=(
            old_price
        ),

        currency=(
            item.get(
                "currency",
                "USD",
            )
        ),

        price_window_days=(
            deal_fields.get(
                "price_window_days"
            )
        ),

        price_30d_low=(
            deal_fields.get(
                "price_30d_low"
            )
        ),

        price_30d_average=(
            deal_fields.get(
                "price_30d_average"
            )
        ),

        price_30d_high=(
            deal_fields.get(
                "price_30d_high"
            )
        ),

        price_history_samples=(
            deal_fields.get(
                "price_history_samples"
            )
        ),

        price_vs_average_pct=(
            deal_fields.get(
                "price_vs_average_pct"
            )
        ),

        price_vs_low_pct=(
            deal_fields.get(
                "price_vs_low_pct"
            )
        ),

        price_drop_pct=(
            deal_fields.get(
                "price_drop_pct"
            )
        ),

        historical_deal_score=(
            deal_fields.get(
                "historical_deal_score"
            )
        ),

        msrp=(
            deal_fields.get(
                "msrp"
            )
        ),

        msrp_currency=(
            deal_fields.get(
                "msrp_currency"
            )
        ),

        msrp_source=(
            deal_fields.get(
                "msrp_source"
            )
        ),

        msrp_confidence=(
            deal_fields.get(
                "msrp_confidence"
            )
        ),

        msrp_original=(
            deal_fields.get(
                "msrp_original"
            )
        ),

        msrp_original_currency=(
            deal_fields.get(
                "msrp_original_currency"
            )
        ),

        msrp_conversion_used=(
            deal_fields.get(
                "msrp_conversion_used",
                False,
            )
        ),

        price_vs_msrp_pct=(
            deal_fields.get(
                "price_vs_msrp_pct"
            )
        ),

        markup_amount=(
            deal_fields.get(
                "markup_amount"
            )
        ),

        msrp_price_state=(
            deal_fields.get(
                "msrp_price_state"
            )
        ),

        scalper_risk=(
            deal_fields.get(
                "scalper_risk"
            )
        ),

        deal_score=(
            deal_fields.get(
                "deal_score"
            )
        ),

        deal_label=(
            deal_fields.get(
                "deal_label"
            )
        ),

        deal_confidence=(
            deal_fields.get(
                "deal_confidence"
            )
        ),

        in_stock=(
            in_stock
        ),

        region=(
            store.region
            or "US"
        ),

        language=(
            family_language(
                product_family
            )
        ),

        product_type=(
            item.get(
                "product_type",
                "TCG Product",
            )
        ),

        product_category=(
            normalize_category(
                item.get(
                    "product_category"
                )
            )
        ),

        product_family=(
            product_family
        ),

        source_type=(
            "shopify"
        ),

        retailer_key=(
            store.domain
        ),

        image_url=(
            item.get(
                "image_url"
            )
        ),

        variant_id=(
            item.get(
                "variant_id"
            )
        ),

        purchase_limit=(
            item.get(
                "purchase_limit"
            )
        ),

        cart_base_url=(
            item.get(
                "cart_base_url"
            )
        ),
    )


SHOPIFY_COLLECTION_FRESHNESS_SECONDS = 24 * 60 * 60


def parse_shopify_timestamp(value):

    if not value:
        return None

    text = str(value).strip()

    if not text:
        return None

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        parsed = datetime.fromisoformat(text)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return None


def is_recent_public_shopify_product(
    item,
    max_age_seconds=SHOPIFY_COLLECTION_FRESHNESS_SECONDS,
):

    observed = (
        parse_shopify_timestamp(item.get("published_at"))
        or parse_shopify_timestamp(item.get("created_at"))
    )

    if observed is None:
        return False

    age_seconds = (
        datetime.now(timezone.utc)
        - observed
    ).total_seconds()

    return (
        -300
        <= age_seconds
        <= max_age_seconds
    )


def should_alert_new_shopify_product(item):

    new_memberships = item.get("new_collection_memberships") or []
    if not isinstance(new_memberships, (list, tuple, set)):
        new_memberships = [new_memberships]
    if any(str(value or "").strip() for value in new_memberships):
        return True, "NEW_PRIORITY_COLLECTION_MEMBERSHIP"

    sources = item.get("discovery_sources") or []

    if not isinstance(sources, (list, tuple, set)):
        sources = [sources]

    normalized_sources = {
        str(source or "").strip().upper()
        for source in sources
        if str(source or "").strip()
    }

    if "PRODUCTS_JSON_BACKFILL" in normalized_sources and "PRODUCTS_JSON" not in normalized_sources:
        return (is_recent_public_shopify_product(item), "EXTENDED_CATALOG_BASELINE_OR_RECENT")

    if "PRODUCTS_JSON" in normalized_sources:
        return True, "PRODUCTS_JSON"

    collection_only = any(
        source.startswith("COLLECTION:")
        for source in normalized_sources
    )

    if collection_only:
        if is_recent_public_shopify_product(item):
            return True, "RECENT_COLLECTION_PUBLICATION"

        return False, "COLLECTION_BACKFILL"

    return False, "UNKNOWN_DISCOVERY_SOURCE"


def add_new_product_events(
    events_to_send,
    item,
    store,
    deal_data=None,
):

    events_to_send.append(

        make_product_event(

            event_type=(
                ProductEventType.DISCOVERED
            ),

            item=item,

            store=store,

            in_stock=(
                item[
                    "available"
                ]
            ),

            deal_data=(
                deal_data
            ),
        )
    )

    state_mapping = {

        "PAGE_LIVE":
            (
                ProductEventType.PAGE_LIVE,
                False,
            ),

        "COMING_SOON":
            (
                ProductEventType.COMING_SOON,
                False,
            ),

        "PREORDER_LIVE":
            (
                ProductEventType.PREORDER_LIVE,
                True,
            ),

        "PREORDER_PAGE":
            (
                ProductEventType.PAGE_LIVE,
                False,
            ),

        "STOCK_AVAILABLE":
            (
                ProductEventType.STOCK_AVAILABLE,
                True,
            ),
    }

    mapping = (
        state_mapping.get(
            item.get(
                "product_state"
            )
        )
    )

    if mapping:

        event_type, in_stock = (
            mapping
        )

        events_to_send.append(

            make_product_event(

                event_type=(
                    event_type
                ),

                item=item,

                store=store,

                in_stock=(
                    in_stock
                ),

                deal_data=(
                    deal_data
                ),
            )
        )


async def find_store_product(
    session,
    store_id,
    url,
):

    result = (
        await session.execute(

            select(
                StoreProduct
            )
            .where(
                StoreProduct.store_id
                == store_id
            )
            .where(
                StoreProduct.url
                == url
            )
            .order_by(
                StoreProduct.id.asc()
            )
        )
    )

    matches = list(
        result.scalars().all()
    )

    if len(
        matches
    ) > 1:

        MONITOR_STATUS[
            "duplicate_rows_detected"
        ] += (
            len(
                matches
            )
            - 1
        )

    return (
        matches[
            0
        ]
        if matches
        else None
    )


async def get_deal_data(
    session,
    *,
    store_product,
    item,
    current_price,
    old_price=None,
    currency="USD",
):

    if (
        store_product is None

        or
        store_product.id is None

        or
        current_price is None
    ):

        return None

    try:

        product_family = (
            get_item_family(
                item
            )
        )

        reference_price = (
            await resolve_reference_price(

                session,

                item,

                game=(
                    item.get(
                        "game"
                    )
                ),

                region=(
                    item.get(
                        "region"
                    )
                    or "GLOBAL"
                ),

                product_family=(
                    product_family
                ),
            )
        )

        return (
            await analyze_price_history(

                session,

                store_product_id=(
                    store_product.id
                ),

                current_price=(
                    current_price
                ),

                old_price=(
                    old_price
                ),

                currency=(
                    currency
                ),

                window_days=30,

                reference_price=(
                    reference_price
                ),
            )
        )

    except Exception as error:

        print(
            (
                "DEAL INTELLIGENCE ERROR | "
                f"StoreProduct="
                f"{getattr(store_product, 'id', None)} | "
                f"Family="
                f"{item.get('product_family')} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return None


async def _scan_shopify_store_unlocked(store):
    adapter = ShopifyAdapter(store.domain, region=store.region or "US")
    native_currency = await adapter.fetch_store_currency()
    # New stores retain the existing single-scan seed suppression. Start
    # progressive delivery only when a persisted product baseline exists.
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.count(StoreProduct.id)).where(StoreProduct.store_id == store.id)
        )
        seeded = bool(result.scalar())
    totals = {}
    batch_count = 0
    processing_seconds = 0.0
    started = time.monotonic()

    async def process_batch(products, source):
        nonlocal batch_count, processing_seconds
        batch_started = time.monotonic()
        result = await _process_shopify_product_batch(store, adapter, native_currency, products)
        processing_seconds += time.monotonic() - batch_started
        batch_count += 1
        for key, value in result.items():
            if isinstance(value, dict):
                target = totals.setdefault(key, {})
                for name, count in value.items():
                    target[name] = target.get(name, 0) + count
            elif isinstance(value, bool):
                totals[key] = totals.get(key, False) or value
            elif isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
            else:
                totals[key] = value
        print(f"SHOPIFY BATCH TIMING | Store={store.name} | Source={source} | "
              f"Products={len(products)} | BatchSeconds={time.monotonic()-batch_started:.3f} | "
              f"PassElapsedSeconds={time.monotonic()-started:.3f} | Events={result.get('events', 0)}")

    try:
        if seeded:
            await adapter.fetch_products(on_batch=process_batch)
        else:
            raw = await adapter.fetch_products()
            await process_batch(raw, "INITIAL_BASELINE")
    finally:
        _record_adapter_diagnostics(store, adapter.get_diagnostics())
    # Adapter counters describe the pass and must not be added per batch.
    diagnostics = adapter.get_diagnostics()
    for key, diagnostic in (
        ("rate_limit_responses", "http_429"), ("rate_limit_retries", "retries"),
        ("rate_limit_backoff_seconds", "backoff_seconds"),
        ("priority_collections", "priority_collections"),
        ("collection_products_seen", "collection_products_seen"),
        ("general_products_seen", "general_products_seen"),
    ):
        totals[key] = diagnostics.get(diagnostic, 0)
    totals["partial_rate_limited"] = bool(diagnostics.get("partial_due_to_rate_limit"))
    totals["general_feed_skipped"] = bool(diagnostics.get("general_feed_skipped"))
    totals["batches"] = batch_count
    print(f"SHOPIFY PASS PHASES | Store={store.name} | Batches={batch_count} | "
          f"FetchAndDiscoverySeconds={time.monotonic()-started-processing_seconds:.3f} | "
          f"ProcessingAndPublishSeconds={processing_seconds:.3f}")
    return totals


async def _process_shopify_product_batch(store, adapter, native_currency, raw_products):
    processing_started = time.monotonic()
    adapter_diagnostics = adapter.get_diagnostics()

    normalized_products = []

    seen_urls = set()

    family_counts = {

        "GLOBAL_STANDARD": 0,
        "JP": 0,
        "KR": 0,
        "CN": 0,
        "UNKNOWN": 0,
    }

    category_counts = {

        "SEALED": 0,
        "SINGLE": 0,
        "ACCESSORY": 0,
        "UNKNOWN": 0,
    }

    unsupported_count = 0

    for raw_product in raw_products:

        item = (
            adapter.normalize_product(
                raw_product
            )
        )

        item[
            "region"
        ] = (
            store.region
            or "US"
        )

        if not item.get(
            "game"
        ):

            unsupported_count += 1

            continue

        if not item.get(
            "url"
        ):

            continue

        if item[
            "url"
        ] in seen_urls:

            continue

        seen_urls.add(
            item[
                "url"
            ]
        )

        family = (
            get_item_family(
                item
            )
        )

        item[
            "product_family"
        ] = (
            family
        )

        family_counts[
            family
        ] = (
            family_counts.get(
                family,
                0,
            )
            + 1
        )

        category = (
            normalize_category(
                item.get(
                    "product_category"
                )
            )
        )

        item[
            "product_category"
        ] = (
            category
        )

        category_counts[
            category
        ] = (
            category_counts.get(
                category,
                0,
            )
            + 1
        )

        product_state = (
            normalize_shopify_product_state(
                item.get(
                    "product_state"
                )
            )
        )

        item[
            "product_state"
        ] = product_state

        normalized_products.append(
            item
        )

    print(
        (
            "SHOPIFY CATEGORY SUMMARY | "
            f"Store={store.name} | "
            f"RAW={len(raw_products)} | "
            f"SUPPORTED={len(normalized_products)} | "
            f"SEALED={category_counts['SEALED']} | "
            f"SINGLE={category_counts['SINGLE']} | "
            f"ACCESSORY={category_counts['ACCESSORY']} | "
            f"UNKNOWN={category_counts['UNKNOWN']} | "
            f"REJECTED={unsupported_count}"
        )
    )

    print(
        (
            "SHOPIFY FAMILY SUMMARY | "
            f"Store={store.name} | "
            f"GLOBAL={family_counts['GLOBAL_STANDARD']} | "
            f"JP={family_counts['JP']} | "
            f"KR={family_counts['KR']} | "
            f"CN={family_counts['CN']} | "
            f"UNKNOWN={family_counts['UNKNOWN']}"
        )
    )

    events_to_send = []

    stats = {

        "store":
            store.name,

        "currency":
            native_currency,

        "raw":
            len(
                raw_products
            ),

        "rejected":
            unsupported_count,

        "seen":
            len(
                normalized_products
            ),

        "new":
            0,

        "updated":
            0,

        "events":
            0,

        "flickers":
            0,

        "variant_switches":
            0,

        "inventory_quantity_changes":
            0,

        "inventory_quantity_known":
            0,

        "inventory_quantity_unknown":
            0,

        "new_product_alerts_allowed":
            0,

        "new_product_backfills_suppressed":
            0,

        "priority_membership_alerts":
            0,

        "rate_limit_responses":
            int(adapter_diagnostics.get("http_429", 0) or 0),

        "rate_limit_retries":
            int(adapter_diagnostics.get("retries", 0) or 0),

        "rate_limit_backoff_seconds":
            float(adapter_diagnostics.get("backoff_seconds", 0.0) or 0.0),

        "priority_collections":
            int(adapter_diagnostics.get("priority_collections", 0) or 0),

        "collection_products_seen":
            int(adapter_diagnostics.get("collection_products_seen", 0) or 0),

        "general_products_seen":
            int(adapter_diagnostics.get("general_products_seen", 0) or 0),

        "general_feed_skipped":
            bool(adapter_diagnostics.get("general_feed_skipped")),

        "partial_rate_limited":
            bool(adapter_diagnostics.get("partial_due_to_rate_limit")),

        "preorder_activations":
            0,

        "preorder_pages":
            sum(
                1
                for item in normalized_products
                if item.get("product_state") == "PREORDER_PAGE"
            ),

        "preorder_live_products":
            sum(
                1
                for item in normalized_products
                if item.get("product_state") == "PREORDER_LIVE"
            ),

        "initial_seed":
            False,

        "categories":
            dict(
                category_counts
            ),

        "families":
            dict(
                family_counts
            ),
    }

    async with SessionLocal() as session:

        count_result = (
            await session.execute(

                select(
                    func.count(
                        StoreProduct.id
                    )
                ).where(
                    StoreProduct.store_id
                    == store.id
                )
            )
        )

        initial_seed = (
            (
                count_result.scalar()
                or 0
            )
            == 0
        )

        stats[
            "initial_seed"
        ] = (
            initial_seed
        )

        for item in normalized_products:

            product_family = (
                get_item_family(
                    item
                )
            )

            store_product = (
                await find_store_product(

                    session,

                    store.id,

                    item[
                        "url"
                    ],
                )
            )

            if store_product is None:

                product = Product(

                    game=(
                        item[
                            "game"
                        ]
                    ),

                    name=(
                        item[
                            "title"
                        ]
                    ),

                    canonical_name=(
                        item[
                            "title"
                        ]
                    ),

                    product_type=(
                        item[
                            "product_type"
                        ]
                    ),

                    product_category=(
                        normalize_category(
                            item.get(
                                "product_category"
                            )
                        )
                    ),

                    product_family=(
                        product_family
                    ),

                    region=(
                        store.region
                        or "US"
                    ),

                    language=(
                        family_language(
                            product_family
                        )
                    ),
                )

                session.add(
                    product
                )

                await session.flush()

                store_product = StoreProduct(

                    store_id=(
                        store.id
                    ),

                    product_id=(
                        product.id
                    ),

                    url=(
                        item[
                            "url"
                        ]
                    ),

                    sku=(
                        item.get(
                            "sku"
                        )
                    ),

                    variant_id=(
                        item.get(
                            "variant_id"
                        )
                    ),

                    purchase_limit=(
                        item.get(
                            "purchase_limit"
                        )
                    ),

                    status=(
                        normalize_shopify_product_state(
                            item.get(
                                "product_state"
                            )
                        )
                    ),

                    price=(
                        item[
                            "price"
                        ]
                    ),

                    currency=(
                        item[
                            "currency"
                        ]
                    ),

                    in_stock=(
                        item[
                            "available"
                        ]
                    ),

                    last_seen_at=(
                        datetime.utcnow()
                    ),
                )

                save_inventory_platform_data(

                    store_product,

                    quantity=(
                        safe_inventory_quantity(
                            item.get(
                                "inventory_quantity"
                            )
                        )
                    ),

                    quantity_known=(
                        bool(
                            item.get(
                                "inventory_quantity_known"
                            )
                        )
                    ),

                    variant_id=(
                        item.get(
                            "variant_id"
                        )
                    ),

                    product_state=(
                        item.get(
                            "product_state"
                        )
                    ),

                    discovery_sources=(
                        item.get(
                            "discovery_sources"
                        )
                    ),
                )

                if bool(
                    item.get(
                        "inventory_quantity_known"
                    )
                ):

                    stats[
                        "inventory_quantity_known"
                    ] += 1

                    MONITOR_STATUS[
                        "inventory_quantity_known"
                    ] += 1

                else:

                    stats[
                        "inventory_quantity_unknown"
                    ] += 1

                    MONITOR_STATUS[
                        "inventory_quantity_unknown"
                    ] += 1

                session.add(
                    store_product
                )

                try:

                    await session.flush()

                except IntegrityError:

                    await session.rollback()

                    continue

                if item.get(
                    "price"
                ) is not None:

                    session.add(

                        PriceHistory(

                            store_product_id=(
                                store_product.id
                            ),

                            price=(
                                item[
                                    "price"
                                ]
                            ),

                            currency=(
                                item[
                                    "currency"
                                ]
                            ),
                        )
                    )

                stats[
                    "new"
                ] += 1

                new_deal_data = None

                if item.get(
                    "price"
                ) is not None:

                    new_deal_data = (
                        await get_deal_data(

                            session,

                            item=item,

                            store_product=(
                                store_product
                            ),

                            current_price=(
                                item.get(
                                    "price"
                                )
                            ),

                            old_price=None,

                            currency=(
                                item.get(
                                    "currency",
                                    "USD",
                                )
                            ),
                        )
                    )

                if not initial_seed:

                    (
                        allow_new_product_alerts,
                        new_product_alert_reason,
                    ) = should_alert_new_shopify_product(
                        item
                    )

                    if allow_new_product_alerts:

                        add_new_product_events(

                            events_to_send,

                            item,

                            store,

                            deal_data=(
                                new_deal_data
                            ),
                        )

                        stats[
                            "new_product_alerts_allowed"
                        ] += 1

                        MONITOR_STATUS[
                            "new_product_alerts_allowed"
                        ] += 1

                    else:

                        stats[
                            "new_product_backfills_suppressed"
                        ] += 1

                        MONITOR_STATUS[
                            "new_product_backfills_suppressed"
                        ] += 1

                        print(
                            (
                                "SHOPIFY NEW PRODUCT BACKFILL SUPPRESSED | "
                                f"Store={store.name} | "
                                f"Product={item['title']} | "
                                f"Reason={new_product_alert_reason} | "
                                f"PublishedAt={item.get('published_at')} | "
                                f"CreatedAt={item.get('created_at')} | "
                                f"DiscoverySources={item.get('discovery_sources')}"
                            )
                        )

                continue

            old_stock = (
                bool(
                    store_product.in_stock
                )
            )

            new_stock = (
                bool(
                    item[
                        "available"
                    ]
                )
            )

            old_product_state = (
                get_previous_product_state(
                    store_product
                )
            )

            new_product_state = (
                normalize_shopify_product_state(
                    item.get(
                        "product_state"
                    )
                )
            )

            previous_discovery_sources = (
                get_previous_discovery_sources(
                    store_product
                )
            )

            current_discovery_sources = {
                str(value or "").strip()
                for value in (item.get("discovery_sources") or [])
                if str(value or "").strip()
            }

            adapter_new_collection_sources = {
                "COLLECTION:" + str(handle or "").strip()
                for handle in (item.get("new_collection_memberships") or [])
                if str(handle or "").strip()
            }

            # Only alert a collection-membership delta when the adapter has
            # already baselined that collection and explicitly observed this
            # product enter it. This prevents a deployment/restart from
            # backfilling every old product the first time a new collection
            # discovery path becomes visible.
            new_priority_collection_sources = {
                value
                for value in current_discovery_sources
                if value.startswith("COLLECTION:")
                and value not in previous_discovery_sources
                and value in adapter_new_collection_sources
            }

            old_price = (
                store_product.price
            )

            new_price = (
                item[
                    "price"
                ]
            )

            old_currency = (
                store_product.currency
                or "USD"
            )

            new_currency = (
                item[
                    "currency"
                ]
            )

            old_variant_id = (
                normalize_variant_id(
                    store_product.variant_id
                )
            )

            new_variant_id = (
                normalize_variant_id(
                    item.get(
                        "variant_id"
                    )
                )
            )

            (
                old_inventory_quantity,
                old_inventory_quantity_known,
            ) = (
                get_previous_inventory_snapshot(
                    store_product
                )
            )

            new_inventory_quantity_known = bool(
                item.get(
                    "inventory_quantity_known"
                )
            )

            new_inventory_quantity = (
                safe_inventory_quantity(
                    item.get(
                        "inventory_quantity"
                    )
                )
                if new_inventory_quantity_known
                else None
            )

            if new_inventory_quantity_known:

                stats[
                    "inventory_quantity_known"
                ] += 1

                MONITOR_STATUS[
                    "inventory_quantity_known"
                ] += 1

            else:

                stats[
                    "inventory_quantity_unknown"
                ] += 1

                MONITOR_STATUS[
                    "inventory_quantity_unknown"
                ] += 1

            inventory_quantity_changed = (
                old_inventory_quantity_known
                and
                new_inventory_quantity_known
                and
                old_inventory_quantity
                != new_inventory_quantity
            )

            if inventory_quantity_changed:

                stats[
                    "inventory_quantity_changes"
                ] += 1

                MONITOR_STATUS[
                    "inventory_quantity_changes"
                ] += 1

                print(
                    (
                        "SHOPIFY INVENTORY QUANTITY CHANGE | "
                        f"Store={store.name} | "
                        f"Product={item['title']} | "
                        f"Variant={new_variant_id} | "
                        f"{old_inventory_quantity}"
                        f"->{new_inventory_quantity}"
                    )
                )

            save_inventory_platform_data(

                store_product,

                quantity=(
                    new_inventory_quantity
                ),

                quantity_known=(
                    new_inventory_quantity_known
                ),

                variant_id=(
                    new_variant_id
                ),

                product_state=(
                    new_product_state
                ),

                discovery_sources=(
                    item.get(
                        "discovery_sources"
                    )
                ),
            )

            variant_changed = (
                old_variant_id
                != new_variant_id
            )

            changed = False

            if variant_changed:

                stats[
                    "variant_switches"
                ] += 1

                MONITOR_STATUS[
                    "variant_switches"
                ] += 1

                print(
                    (
                        "SHOPIFY VARIANT SWITCH | "
                        f"Store={store.name} | "
                        f"Product={item['title']} | "
                        f"OldVariant={old_variant_id} | "
                        f"NewVariant={new_variant_id} | "
                        f"VariantTitle={item.get('variant_title')} | "
                        f"VariantAvailable={item.get('variant_available')} | "
                        f"OldStock={old_stock} | "
                        f"NewStock={new_stock}"
                    )
                )

            store_product.sku = (
                item.get(
                    "sku"
                )
            )

            store_product.variant_id = (
                new_variant_id
            )

            store_product.purchase_limit = (
                item.get(
                    "purchase_limit"
                )
            )

            product_result = (
                await session.execute(

                    select(
                        Product
                    ).where(
                        Product.id
                        == store_product.product_id
                    )
                )
            )

            product_row = (
                product_result.scalars().first()
            )

            old_product_title = (
                getattr(
                    product_row,
                    "name",
                    None,
                )
                if product_row is not None
                else None
            )

            if product_row is not None:

                product_row.game = (
                    item[
                        "game"
                    ]
                )

                product_row.name = (
                    item[
                        "title"
                    ]
                )

                product_row.canonical_name = (
                    item[
                        "title"
                    ]
                )

                product_row.product_type = (
                    item.get(
                        "product_type"
                    )
                    or product_row.product_type
                )

                product_row.product_category = (
                    normalize_category(
                        item.get(
                            "product_category"
                        )
                    )
                )

                product_row.product_family = (
                    product_family
                )

                product_row.region = (
                    store.region
                    or product_row.region
                )

                product_row.language = (
                    family_language(
                        product_family
                    )
                )

            currency_changed = (
                old_currency
                != new_currency
            )

            if currency_changed:

                print(
                    (
                        "SHOPIFY CURRENCY CORRECTED | "
                        f"Store={store.name} | "
                        f"Product={item['title']} | "
                        f"Family={product_family} | "
                        f"{old_currency}->{new_currency}"
                    )
                )

                store_product.currency = (
                    new_currency
                )

                if new_price is not None:

                    session.add(

                        PriceHistory(

                            store_product_id=(
                                store_product.id
                            ),

                            price=(
                                new_price
                            ),

                            currency=(
                                new_currency
                            ),
                        )
                    )

            preorder_title_transition = (
                is_preorder_title(
                    item.get(
                        "title"
                    )
                )
                and not is_preorder_title(
                    old_product_title
                )
            )

            preorder_activation = (
                new_product_state
                == "PREORDER_LIVE"
                and (
                    old_product_state
                    != "PREORDER_LIVE"
                )
                and (
                    not old_stock
                    # A different discovery source can change the inferred
                    # state without a real preorder activation. Require new
                    # evidence when the product was already purchasable.
                    or bool(new_priority_collection_sources)
                    or preorder_title_transition
                )
            )

            if preorder_activation:

                changed = True

                stats[
                    "preorder_activations"
                ] += 1

                MONITOR_STATUS[
                    "preorder_activations"
                ] += 1

                preorder_deal_data = None

                if new_price is not None:

                    preorder_deal_data = (
                        await get_deal_data(

                            session,

                            item=item,

                            store_product=(
                                store_product
                            ),

                            current_price=(
                                new_price
                            ),

                            old_price=(
                                old_price
                            ),

                            currency=(
                                new_currency
                            ),
                        )
                    )

                events_to_send.append(

                    make_product_event(

                        event_type=(
                            ProductEventType.PREORDER_LIVE
                        ),

                        item=item,

                        store=store,

                        in_stock=True,

                        old_price=(
                            old_price
                            if (
                                old_price is not None
                                and new_price is not None
                                and old_price != new_price
                            )
                            else None
                        ),

                        deal_data=(
                            preorder_deal_data
                        ),
                    )
                )

                print(
                    (
                        "SHOPIFY PREORDER ACTIVATED | "
                        f"Store={store.name} | "
                        f"Product={item['title']} | "
                        f"OldState={old_product_state or 'UNTRACKED'} | "
                        f"NewState={new_product_state} | "
                        f"OldStock={old_stock} | "
                        f"NewStock={new_stock} | "
                        f"DiscoverySources={item.get('discovery_sources')}"
                    )
                )

            priority_membership_alerted = False

            if (
                new_priority_collection_sources
                and not preorder_activation
                and old_stock == new_stock
            ):
                changed = True
                priority_membership_alerted = True
                stats["priority_membership_alerts"] += 1
                MONITOR_STATUS["priority_membership_alerts"] += 1

                membership_event_type = (
                    ProductEventType.COMING_SOON
                    if new_product_state == "COMING_SOON"
                    else ProductEventType.PAGE_LIVE
                )

                events_to_send.append(
                    make_product_event(
                        event_type=membership_event_type,
                        item=item,
                        store=store,
                        in_stock=new_stock,
                        old_price=None,
                    )
                )

                print(
                    "SHOPIFY PRIORITY COLLECTION RELEASE SIGNAL | "
                    f"Store={store.name} | Product={item['title']} | "
                    f"Collections={sorted(new_priority_collection_sources)} | "
                    f"State={new_product_state} | Stock={new_stock}"
                )

            if old_stock != new_stock:

                changed = True

                flicker_result = (
                    await record_stock_transition(

                        store_product_id=(
                            store_product.id
                        ),

                        in_stock=(
                            new_stock
                        ),
                    )
                )

                stock_event = (
                    None
                    if (
                        preorder_activation
                        and new_stock
                    )
                    else (
                        ProductEventType.RESTOCK
                        if (
                            not old_stock
                            and new_stock
                        )
                        else ProductEventType.SOLD_OUT
                    )
                )

                restock_deal_data = None

                if (
                    stock_event
                    == ProductEventType.RESTOCK

                    and
                    new_price is not None
                ):

                    restock_deal_data = (
                        await get_deal_data(

                            session,

                            item=item,

                            store_product=(
                                store_product
                            ),

                            current_price=(
                                new_price
                            ),

                            old_price=(
                                old_price
                            ),

                            currency=(
                                new_currency
                            ),
                        )
                    )

                if stock_event is not None:

                    events_to_send.append(

                        make_product_event(

                            event_type=(
                                stock_event
                            ),

                        item=item,

                        store=store,

                        in_stock=(
                            new_stock
                        ),

                        old_price=(
                            old_price
                            if (
                                old_price is not None
                                and new_price is not None
                                and old_price != new_price
                            )
                            else None
                        ),

                        deal_data=(
                            restock_deal_data
                        ),
                    )
                )

                if flicker_result.get(
                    "flickering"
                ):

                    events_to_send.append(

                        make_product_event(

                            event_type=(
                                ProductEventType.INVENTORY_FLICKER
                            ),

                            item=item,

                            store=store,

                            in_stock=(
                                new_stock
                            ),

                            deal_data=(
                                restock_deal_data
                                if new_stock
                                else None
                            ),
                        )
                    )

                    stats[
                        "flickers"
                    ] += 1

            suppress_variant_switch_price_event = (
                variant_changed
                and old_stock
                and new_stock
            )

            if (
                not currency_changed
                and not suppress_variant_switch_price_event
                and old_price is not None
                and new_price is not None
                and old_price != new_price
            ):

                changed = True

                price_deal_data = (
                    await get_deal_data(

                        session,

                        item=item,

                        store_product=(
                            store_product
                        ),

                        current_price=(
                            new_price
                        ),

                        old_price=(
                            old_price
                        ),

                        currency=(
                            new_currency
                        ),
                    )
                )

                session.add(

                    PriceHistory(

                        store_product_id=(
                            store_product.id
                        ),

                        price=(
                            new_price
                        ),

                        currency=(
                            new_currency
                        ),
                    )
                )

                price_event = (
                    ProductEventType.PRICE_DROP
                    if new_price < old_price
                    else ProductEventType.PRICE_INCREASE
                )

                events_to_send.append(

                    make_product_event(

                        event_type=(
                            price_event
                        ),

                        item=item,

                        store=store,

                        in_stock=(
                            new_stock
                        ),

                        old_price=(
                            old_price
                        ),

                        deal_data=(
                            price_deal_data
                        ),
                    )
                )

            elif (
                suppress_variant_switch_price_event
                and old_price is not None
                and new_price is not None
                and old_price != new_price
            ):

                session.add(

                    PriceHistory(

                        store_product_id=(
                            store_product.id
                        ),

                        price=(
                            new_price
                        ),

                        currency=(
                            new_currency
                        ),
                    )
                )

                print(
                    (
                        "SHOPIFY VARIANT PRICE SWITCH | "
                        f"Store={store.name} | "
                        f"Product={item['title']} | "
                        f"{old_price}->{new_price} "
                        f"{new_currency} | "
                        "AlertSuppressed=True"
                    )
                )

            # Preserve the last known price if a temporary
            # storefront response does not include one.
            if new_price is not None:

                store_product.price = (
                    new_price
                )

            store_product.currency = (
                new_currency
            )

            store_product.in_stock = (
                new_stock
            )

            store_product.status = (
                new_product_state
            )

            store_product.last_seen_at = (
                datetime.utcnow()
            )

            if (
                changed
                or inventory_quantity_changed
            ):

                stats[
                    "updated"
                ] += 1

        await session.commit()

    publish_started = time.monotonic()
    for event in events_to_send:

        result = (
            await process_product_event(
                event
            )
        )

        if result.get(
            "redis_saved"
        ):

            stats[
                "events"
            ] += 1

    print(f"SHOPIFY BATCH PHASES | Store={store.name} | "
          f"NormalizeAndDBSeconds={publish_started-processing_started:.3f} | "
          f"PublishSeconds={time.monotonic()-publish_started:.3f}")
    return (
        stats
    )


async def scan_shopify_store(store):
    """Serialize scans for a single Shopify storefront."""
    lock = _get_store_scan_lock(store.id)
    async with lock:
        requested = time.monotonic()
        async with _STORE_SCAN_CAPACITY:
            started = time.monotonic()
            previous = _STORE_TIMINGS.get(store.id, {}).get("started_monotonic")
            timing = {
                "store": store.name,
                "started_monotonic": started,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "capacity_wait_seconds": round(started - requested, 3),
                "revisit_seconds": round(started - previous, 3) if previous else None,
            }
            _STORE_TIMINGS[store.id] = timing
            MONITOR_STATUS["scan_started_at"] = timing["started_at"]
            try:
                return await _scan_shopify_store_unlocked(store)
            finally:
                timing["duration_seconds"] = round(time.monotonic() - started, 3)
                MONITOR_STATUS["scan_finished_at"] = datetime.now(timezone.utc).isoformat()
                MONITOR_STATUS["scan_duration_seconds"] = timing["duration_seconds"]
                print(
                    "SHOPIFY STORE TIMING | "
                    f"Store={store.name} | RevisitSeconds={timing['revisit_seconds']} | "
                    f"ScanSeconds={timing['duration_seconds']} | "
                    f"CapacityWaitSeconds={timing['capacity_wait_seconds']}"
                )


async def _scan_all_shopify_stores_unlocked():

    stores = (
        await get_shopify_stores()
    )

    MONITOR_STATUS["active_shopify_stores"] = len(stores)

    results = []

    total_products = 0
    total_events = 0
    total_flickers = 0
    total_variant_switches = 0
    total_preorder_activations = 0
    total_preorder_pages = 0
    total_preorder_live_products = 0
    stores_scanned = 0

    total_categories = {

        "SEALED": 0,
        "SINGLE": 0,
        "ACCESSORY": 0,
        "UNKNOWN": 0,
    }

    total_families = {

        "GLOBAL_STANDARD": 0,
        "JP": 0,
        "KR": 0,
        "CN": 0,
        "UNKNOWN": 0,
    }

    MONITOR_STATUS[
        "last_error"
    ] = None

    for key, value in (
        ("stores_failed", 0),
        ("rate_limit_responses", 0),
        ("rate_limit_retries", 0),
        ("rate_limit_backoff_seconds", 0.0),
        ("rate_limit_exhausted", 0),
        ("partial_rate_limited_scans", 0),
        ("priority_collections", 0),
        ("collection_products_seen", 0),
        ("general_products_seen", 0),
        ("general_feed_skipped", 0),
        ("new_priority_collection_memberships", 0),
        ("priority_membership_alerts", 0),
    ):
        MONITOR_STATUS[key] = value

    MONITOR_STATUS[
        "inventory_quantity_changes"
    ] = 0

    MONITOR_STATUS[
        "inventory_quantity_known"
    ] = 0

    MONITOR_STATUS[
        "inventory_quantity_unknown"
    ] = 0

    MONITOR_STATUS[
        "new_product_alerts_allowed"
    ] = 0

    MONITOR_STATUS[
        "new_product_backfills_suppressed"
    ] = 0

    MONITOR_STATUS[
        "preorder_activations"
    ] = 0

    MONITOR_STATUS[
        "preorder_pages"
    ] = 0

    MONITOR_STATUS[
        "preorder_live_products"
    ] = 0

    for store in stores:

        try:

            result = (
                await scan_shopify_store(
                    store
                )
            )

            await record_store_success(
                store.id
            )

            results.append(
                result
            )

            stores_scanned += 1

            total_products += (
                result[
                    "seen"
                ]
            )

            total_events += (
                result[
                    "events"
                ]
            )

            total_flickers += (
                result[
                    "flickers"
                ]
            )

            total_variant_switches += (
                result.get(
                    "variant_switches",
                    0,
                )
            )

            total_preorder_activations += (
                result.get(
                    "preorder_activations",
                    0,
                )
            )

            total_preorder_pages += (
                result.get(
                    "preorder_pages",
                    0,
                )
            )

            total_preorder_live_products += (
                result.get(
                    "preorder_live_products",
                    0,
                )
            )

            for (
                category,
                count,
            ) in result.get(
                "categories",
                {}
            ).items():

                total_categories[
                    category
                ] = (
                    total_categories.get(
                        category,
                        0,
                    )
                    + count
                )

            for (
                family,
                count,
            ) in result.get(
                "families",
                {}
            ).items():

                total_families[
                    family
                ] = (
                    total_families.get(
                        family,
                        0,
                    )
                    + count
                )

        except ShopifyRateLimitError as error:

            error_text = (
                f"{store.name}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            # 429 is transient throttling, not proof the storefront is bad.
            # Do not increment the store-health failure counter here.
            MONITOR_STATUS["stores_failed"] += 1
            MONITOR_STATUS["last_error"] = error_text
            print(
                "SHOPIFY SCAN RATE LIMITED | "
                f"Store={store.name} | Error={error}"
            )

        except Exception as error:

            error_text = (
                f"{store.name}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            print(
                (
                    "SHOPIFY SCAN ERROR: "
                    f"{error_text}"
                )
            )

            MONITOR_STATUS["stores_failed"] += 1

            await record_store_failure(
                store.id,
                error_text,
            )

            MONITOR_STATUS[
                "last_error"
            ] = (
                error_text
            )

    MONITOR_STATUS[
        "last_scan"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "stores_scanned"
    ] = (
        stores_scanned
    )

    MONITOR_STATUS[
        "products_seen"
    ] = (
        total_products
    )

    MONITOR_STATUS[
        "events_created"
    ] = (
        total_events
    )

    MONITOR_STATUS[
        "flickers_detected"
    ] = (
        total_flickers
    )

    MONITOR_STATUS[
        "variant_switches"
    ] = (
        total_variant_switches
    )

    MONITOR_STATUS[
        "preorder_activations"
    ] = (
        total_preorder_activations
    )

    MONITOR_STATUS[
        "preorder_pages"
    ] = (
        total_preorder_pages
    )

    MONITOR_STATUS[
        "preorder_live_products"
    ] = (
        total_preorder_live_products
    )

    MONITOR_STATUS[
        "sealed_products"
    ] = (
        total_categories[
            "SEALED"
        ]
    )

    MONITOR_STATUS[
        "single_products"
    ] = (
        total_categories[
            "SINGLE"
        ]
    )

    MONITOR_STATUS[
        "accessory_products"
    ] = (
        total_categories[
            "ACCESSORY"
        ]
    )

    MONITOR_STATUS[
        "unknown_category_products"
    ] = (
        total_categories[
            "UNKNOWN"
        ]
    )

    MONITOR_STATUS[
        "global_family_products"
    ] = (
        total_families[
            "GLOBAL_STANDARD"
        ]
    )

    MONITOR_STATUS[
        "jp_family_products"
    ] = (
        total_families[
            "JP"
        ]
    )

    MONITOR_STATUS[
        "kr_family_products"
    ] = (
        total_families[
            "KR"
        ]
    )

    MONITOR_STATUS[
        "cn_family_products"
    ] = (
        total_families[
            "CN"
        ]
    )

    MONITOR_STATUS[
        "unknown_family_products"
    ] = (
        total_families[
            "UNKNOWN"
        ]
    )

    return (
        results
    )


async def scan_all_shopify_stores():
    """Run one full Shopify cycle; overlapping cycles are skipped."""
    if _SHOPIFY_SCAN_LOCK.locked():
        MONITOR_STATUS["scan_skipped_overlap"] += 1
        MONITOR_STATUS["last_scan_outcome"] = "SKIPPED_OVERLAP"
        print("SHOPIFY SCAN SKIPPED | Reason=OVERLAP")
        return []

    async with _SHOPIFY_SCAN_LOCK:
        started_monotonic = time.monotonic()
        MONITOR_STATUS["scan_in_progress"] = True
        MONITOR_STATUS["scan_started_at"] = datetime.utcnow().isoformat()
        MONITOR_STATUS["scan_finished_at"] = None
        MONITOR_STATUS["scan_duration_seconds"] = None
        MONITOR_STATUS["last_scan_outcome"] = "RUNNING"

        try:
            results = await _scan_all_shopify_stores_unlocked()
            MONITOR_STATUS["last_scan_outcome"] = (
                "SUCCESS" if results else "NO_SUCCESSFUL_STORES"
            )
            return results
        finally:
            MONITOR_STATUS["scan_in_progress"] = False
            MONITOR_STATUS["scan_finished_at"] = datetime.utcnow().isoformat()
            MONITOR_STATUS["scan_duration_seconds"] = round(
                max(0.0, time.monotonic() - started_monotonic),
                2,
            )


async def probe_shopify_store(
    store,
):

    adapter = ShopifyAdapter(

        store.domain,

        region=(
            store.region
            or "US"
        ),
    )

    lock = _get_store_scan_lock(store.id)
    async with lock:
        try:
            await adapter.probe_storefront()
        finally:
            _record_adapter_diagnostics(
                store,
                adapter.get_diagnostics(),
            )

    return (
        await record_store_success(

            store.id,

            allow_health_reenable=True,
        )
    )


async def run_health_recovery_probes():

    stores = (
        await get_health_recovery_candidates()
    )

    recovered_count = 0

    for store in stores:

        try:

            recovered = (
                await probe_shopify_store(
                    store
                )
            )

            if (
                recovered
                and recovered.active
            ):

                recovered_count += 1

        except ShopifyRateLimitError as error:

            MONITOR_STATUS["last_error"] = (
                f"{store.name}: {type(error).__name__}: {error}"
            )
            print(
                "SHOPIFY HEALTH PROBE RATE LIMITED | "
                f"Store={store.name} | Error={error}"
            )

        except Exception as error:

            await record_store_failure(

                store.id,

                (
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
            )

    MONITOR_STATUS[
        "last_health_probe"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "stores_recovered"
    ] = (
        recovered_count
    )

    return (
        recovered_count
    )


async def retry_shopify_store(
    store_id,
):

    store = (
        await get_shopify_store(
            store_id
        )
    )

    if store is None:

        return {
            "success": False,
            "reason": "NOT_FOUND",
            "store": None,
        }

    if store.disabled_reason == "MANUAL":

        return {
            "success": False,
            "reason": "MANUAL",
            "store": store,
        }

    if store.disabled_reason == "REMOVED":

        return {
            "success": False,
            "reason": "REMOVED",
            "store": store,
        }

    try:

        recovered = (
            await probe_shopify_store(
                store
            )
        )

        return {
            "success": True,
            "reason": "ONLINE",
            "store": recovered,
        }

    except ShopifyRateLimitError as error:

        return {
            "success": False,
            "reason": "RATE_LIMITED",
            "detail": str(error),
            "store": store,
        }

    except Exception as error:

        failed_store = (
            await record_store_failure(

                store.id,

                (
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
            )
        )

        return {
            "success": False,
            "reason": str(
                error
            ),
            "store": failed_store,
        }


def _refresh_background_status():
    """Existing status fields summarize the latest successful scan per store."""
    values = list(_STORE_RESULTS.values())
    MONITOR_STATUS["stores_scanned"] = len(values)
    for status_key, result_key in (
        ("products_seen", "seen"), ("events_created", "events"),
        ("flickers_detected", "flickers"), ("variant_switches", "variant_switches"),
        ("preorder_activations", "preorder_activations"),
        ("preorder_pages", "preorder_pages"),
        ("preorder_live_products", "preorder_live_products"),
    ):
        MONITOR_STATUS[status_key] = sum(int(v.get(result_key, 0) or 0) for v in values)
    for key, category in (("sealed_products", "SEALED"), ("single_products", "SINGLE"),
                          ("accessory_products", "ACCESSORY"), ("unknown_category_products", "UNKNOWN")):
        MONITOR_STATUS[key] = sum(v.get("categories", {}).get(category, 0) for v in values)
    for key, family in (("global_family_products", "GLOBAL_STANDARD"), ("jp_family_products", "JP"),
                        ("kr_family_products", "KR"), ("cn_family_products", "CN"),
                        ("unknown_family_products", "UNKNOWN")):
        MONITOR_STATUS[key] = sum(v.get("families", {}).get(family, 0) for v in values)


async def _run_scheduled_store(store_id):
    global _BACKGROUND_SCANS
    failures = 0
    while True:
        # Reload live activation/domain settings before every scan. Manual
        # removal/disable therefore stops further polling without a restart.
        store = await get_shopify_store(store_id)
        if store is None or not store.active or store.platform != "shopify":
            return
        started = time.monotonic()
        cooldown = POLL_SECONDS
        _BACKGROUND_SCANS += 1
        try:
            result = await scan_shopify_store(store)
            _STORE_RESULTS[store_id] = result
            if result.get("partial_rate_limited"):
                failures += 1
                cooldown = min(300, 30 * 2 ** min(failures - 1, 4))
            else:
                failures = 0
            await record_store_success(store.id)
            _refresh_background_status()
            MONITOR_STATUS["last_scan"] = datetime.utcnow().isoformat()
            MONITOR_STATUS["last_scan_outcome"] = "SUCCESS"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failures += 1
            cooldown = min(300, 30 * 2 ** min(failures - 1, 4))
            MONITOR_STATUS["stores_failed"] += 1
            MONITOR_STATUS["last_error"] = f"{store.name}: {type(error).__name__}: {error}"
            MONITOR_STATUS["last_scan_outcome"] = "STORE_ERROR"
            print("SHOPIFY SCHEDULED ERROR | " + MONITOR_STATUS["last_error"])
            if not isinstance(error, ShopifyRateLimitError):
                await record_store_failure(store.id, str(error))
        finally:
            _BACKGROUND_SCANS -= 1
        # No catch-up bursts. Healthy short scans target a five-second
        # start-to-start period; throttled/error sources get a full cooldown.
        delay = cooldown if failures else max(1.0, POLL_SECONDS - (time.monotonic() - started))
        await asyncio.sleep(delay)


async def run_shopify_monitor():
    MONITOR_STATUS["running"] = True
    print("Lotus Shopify Monitor 6K-2C4 (component 1.0.6-C4) started. "
          "Independent stores; target=5s; max concurrent scans=4.")
    tasks = {}
    health_task = None
    last_health_probe = 0.0
    try:
        await asyncio.sleep(2)
        while True:
            try:
                stores = await get_shopify_stores()
                active_ids = {store.id for store in stores}
                MONITOR_STATUS["active_shopify_stores"] = len(active_ids)
                # Let in-flight transactions/publication finish on disable.
                # Each store task rechecks activation before the next request.
                for store_id, task in list(tasks.items()):
                    if task.done():
                        if not task.cancelled() and task.exception() is not None:
                            print(f"SHOPIFY SCHEDULER TASK ERROR | StoreID={store_id} | {task.exception()}")
                        del tasks[store_id]
                for store in stores:
                    if store.id not in tasks:
                        tasks[store.id] = asyncio.create_task(_run_scheduled_store(store.id))
                for store_id in list(_STORE_RESULTS):
                    if store_id not in active_ids:
                        _STORE_RESULTS.pop(store_id, None)
                        _STORE_TIMINGS.pop(store_id, None)
                now = time.monotonic()
                if health_task is not None and health_task.done():
                    if not health_task.cancelled() and health_task.exception() is not None:
                        print(f"SHOPIFY HEALTH TASK ERROR | {health_task.exception()}")
                    health_task = None
                if health_task is None and now - last_health_probe >= HEALTH_PROBE_SECONDS:
                    health_task = asyncio.create_task(run_health_recovery_probes())
                    last_health_probe = now
            except asyncio.CancelledError:
                raise
            except Exception as error:
                MONITOR_STATUS["last_error"] = f"Scheduler: {type(error).__name__}: {error}"
                print("SHOPIFY SCHEDULER ERROR | " + MONITOR_STATUS["last_error"])
            await asyncio.sleep(5)
    finally:
        MONITOR_STATUS["running"] = False
        children = list(tasks.values()) + ([health_task] if health_task else [])
        for task in children:
            task.cancel()
        await asyncio.gather(*children, return_exceptions=True)


def get_shopify_monitor_status():
    data = dict(MONITOR_STATUS)
    data.update({
        "scheduler": "INDEPENDENT_STORES_6K_2C4",
        "target_interval_seconds": POLL_SECONDS,
        "max_concurrent_stores": MAX_CONCURRENT_STORE_SCANS,
        "background_scans": _BACKGROUND_SCANS,
        "scan_in_progress": bool(_BACKGROUND_SCANS or _SHOPIFY_SCAN_LOCK.locked()),
        "status_scope": "latest successful scan per store; adapter counters cumulative",
        "store_timings": {str(k): {name: value for name, value in v.items()
                                  if name != "started_monotonic"}
                          for k, v in _STORE_TIMINGS.items()},
    })
    return data
