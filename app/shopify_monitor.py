import asyncio
import time

from datetime import datetime

from sqlalchemy import (
    func,
    select,
)

from app.database import (
    SessionLocal,
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

from app.shopify_adapter import (
    ShopifyAdapter,
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
# Version 0.6.3
#
# Shopify Monitoring
# Product Intelligence
# Inventory Flicker
# Persistent Store Health
# Automatic Recovery
# =========================================================


POLL_SECONDS = 60

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

    "last_error":
        None,
}


# =========================================================
# ADD STORE
# =========================================================

async def add_shopify_store(
    name: str,
    domain: str,
    region: str = "US",
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    domain = (
        normalize_shopify_domain(
            domain
        )
    )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.domain
                == domain
            )
        )

        existing = (
            result.scalar_one_or_none()
        )

        if existing:

            existing.name = name

            existing.platform = (
                "shopify"
            )

            existing.region = region

            existing.active = True

            existing.health_status = (
                "HEALTHY"
            )

            existing.disabled_reason = None

            existing.consecutive_failures = 0

            existing.last_error = None

            await session.commit()

            await session.refresh(
                existing
            )

            return (
                existing,
                False,
            )

        store = Store(
            name=name,
            domain=domain,
            platform="shopify",
            region=region,
            active=True,
            health_status="HEALTHY",
            consecutive_failures=0,
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


# =========================================================
# LIST STORES
# =========================================================

async def list_shopify_stores(
    include_removed: bool = False,
):

    if SessionLocal is None:

        return []

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

        result = await session.execute(
            query
        )

        return list(
            result.scalars().all()
        )


# =========================================================
# GET STORE
# =========================================================

async def get_shopify_store(
    store_id: int,
):

    if SessionLocal is None:

        return None

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        return (
            result.scalar_one_or_none()
        )


# =========================================================
# STORE MANAGEMENT WRAPPERS
# =========================================================

async def set_shopify_store_active(
    store_id: int,
    active: bool,
):

    if active:

        return await manual_enable_store(
            store_id
        )

    return await manual_disable_store(
        store_id
    )


async def remove_shopify_store(
    store_id: int,
):

    return await mark_store_removed(
        store_id
    )


async def restore_shopify_store(
    store_id: int,
):

    return await restore_removed_store(
        store_id
    )


# =========================================================
# ACTIVE STORES
# =========================================================

async def get_shopify_stores():

    if SessionLocal is None:

        return []

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.active
                == True
            ).where(
                Store.platform
                == "shopify"
            ).order_by(
                Store.id.asc()
            )
        )

        return list(
            result.scalars().all()
        )


# =========================================================
# EVENT BUILDER
# =========================================================

def make_product_event(
    *,
    event_type,
    item,
    store,
    in_stock,
):

    return ProductEvent(
        event_type=event_type,
        game=item["game"],
        product_name=item["title"],
        store_name=store.name,
        product_url=item["url"],
        price=item["price"],
        currency="USD",
        in_stock=in_stock,
        region=(
            store.region
            or "US"
        ),
        language="English",
        product_type=item[
            "product_type"
        ],
    )


# =========================================================
# NEW PRODUCT EVENTS
# =========================================================

def add_new_product_events(
    events_to_send,
    item,
    store,
):

    events_to_send.append(

        make_product_event(
            event_type=(
                ProductEventType.DISCOVERED
            ),
            item=item,
            store=store,
            in_stock=item[
                "available"
            ],
        )
    )

    product_state = item.get(
        "product_state"
    )

    if product_state == "PAGE_LIVE":

        event_type = (
            ProductEventType.PAGE_LIVE
        )

        in_stock = False

    elif product_state == "COMING_SOON":

        event_type = (
            ProductEventType.COMING_SOON
        )

        in_stock = False

    elif product_state == "PREORDER_LIVE":

        event_type = (
            ProductEventType.PREORDER_LIVE
        )

        in_stock = True

    elif product_state == "PREORDER_PAGE":

        event_type = (
            ProductEventType.PAGE_LIVE
        )

        in_stock = False

    elif product_state == "STOCK_AVAILABLE":

        event_type = (
            ProductEventType.STOCK_AVAILABLE
        )

        in_stock = True

    else:

        return

    events_to_send.append(

        make_product_event(
            event_type=event_type,
            item=item,
            store=store,
            in_stock=in_stock,
        )
    )


# =========================================================
# SCAN ONE STORE
# =========================================================

async def scan_shopify_store(
    store: Store,
):

    adapter = (
        ShopifyAdapter(
            store.domain
        )
    )

    raw_products = (
        await adapter.fetch_products()
    )

    normalized_products = []

    for raw_product in raw_products:

        item = (
            adapter.normalize_product(
                raw_product
            )
        )

        if not item[
            "game"
        ]:

            continue

        normalized_products.append(
            item
        )

    events_to_send = []

    stats = {
        "store":
            store.name,
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
        "initial_seed":
            False,
    }

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        count_result = await session.execute(

            select(
                func.count(
                    StoreProduct.id
                )
            ).where(
                StoreProduct.store_id
                == store.id
            )
        )

        existing_count = (
            count_result.scalar()
            or 0
        )

        initial_seed = (
            existing_count
            == 0
        )

        stats[
            "initial_seed"
        ] = initial_seed

        for item in normalized_products:

            result = await session.execute(

                select(
                    StoreProduct
                ).where(
                    StoreProduct.store_id
                    == store.id
                ).where(
                    StoreProduct.url
                    == item[
                        "url"
                    ]
                )
            )

            store_product = (
                result.scalar_one_or_none()
            )

            # =================================================
            # NEW PRODUCT
            # =================================================

            if store_product is None:

                product = Product(
                    game=item[
                        "game"
                    ],
                    name=item[
                        "title"
                    ],
                    canonical_name=item[
                        "title"
                    ],
                    product_type=item[
                        "product_type"
                    ],
                    region=(
                        store.region
                        or "US"
                    ),
                    language="English",
                )

                session.add(
                    product
                )

                await session.flush()

                store_product = (
                    StoreProduct(
                        store_id=store.id,
                        product_id=product.id,
                        url=item[
                            "url"
                        ],
                        status=(
                            "in_stock"
                            if item[
                                "available"
                            ]
                            else "sold_out"
                        ),
                        price=item[
                            "price"
                        ],
                        currency="USD",
                        in_stock=item[
                            "available"
                        ],
                        last_seen_at=(
                            datetime.utcnow()
                        ),
                    )
                )

                session.add(
                    store_product
                )

                await session.flush()

                stats[
                    "new"
                ] += 1

                if not initial_seed:

                    add_new_product_events(
                        events_to_send,
                        item,
                        store,
                    )

                continue

            # =================================================
            # EXISTING PRODUCT
            # =================================================

            old_stock = bool(
                store_product.in_stock
            )

            new_stock = bool(
                item[
                    "available"
                ]
            )

            old_price = (
                store_product.price
            )

            new_price = (
                item[
                    "price"
                ]
            )

            changed = False

            # =================================================
            # STOCK TRANSITION
            # =================================================

            if old_stock != new_stock:

                changed = True

                flicker_result = (
                    await record_stock_transition(
                        store_product_id=(
                            store_product.id
                        ),
                        in_stock=new_stock,
                    )
                )

                if (
                    not old_stock
                    and new_stock
                ):

                    stock_event = (
                        ProductEventType.RESTOCK
                    )

                else:

                    stock_event = (
                        ProductEventType.SOLD_OUT
                    )

                events_to_send.append(

                    make_product_event(
                        event_type=(
                            stock_event
                        ),
                        item=item,
                        store=store,
                        in_stock=new_stock,
                    )
                )

                if flicker_result[
                    "flickering"
                ]:

                    events_to_send.append(

                        make_product_event(
                            event_type=(
                                ProductEventType.INVENTORY_FLICKER
                            ),
                            item=item,
                            store=store,
                            in_stock=new_stock,
                        )
                    )

                    stats[
                        "flickers"
                    ] += 1

            # =================================================
            # PRICE CHANGE
            # =================================================

            if (
                old_price is not None
                and new_price is not None
                and old_price
                != new_price
            ):

                changed = True

                session.add(

                    PriceHistory(
                        store_product_id=(
                            store_product.id
                        ),
                        price=new_price,
                        currency="USD",
                    )
                )

                if new_price < old_price:

                    price_event = (
                        ProductEventType.PRICE_DROP
                    )

                else:

                    price_event = (
                        ProductEventType.PRICE_INCREASE
                    )

                events_to_send.append(

                    make_product_event(
                        event_type=price_event,
                        item=item,
                        store=store,
                        in_stock=new_stock,
                    )
                )

            store_product.price = (
                new_price
            )

            store_product.in_stock = (
                new_stock
            )

            store_product.status = (
                "in_stock"
                if new_stock
                else "sold_out"
            )

            store_product.last_seen_at = (
                datetime.utcnow()
            )

            if changed:

                stats[
                    "updated"
                ] += 1

        await session.commit()

    for event in events_to_send:

        result = (
            await process_product_event(
                event
            )
        )

        if result[
            "redis_saved"
        ]:

            stats[
                "events"
            ] += 1

    return stats


# =========================================================
# SCAN ALL ACTIVE STORES
# =========================================================

async def scan_all_shopify_stores():

    stores = (
        await get_shopify_stores()
    )

    total_products = 0

    total_events = 0

    total_flickers = 0

    stores_scanned = 0

    results = []

    MONITOR_STATUS[
        "last_error"
    ] = None

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

            await record_store_failure(
                store.id,
                error_text,
            )

            MONITOR_STATUS[
                "last_error"
            ] = error_text

    MONITOR_STATUS[
        "last_scan"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "stores_scanned"
    ] = stores_scanned

    MONITOR_STATUS[
        "products_seen"
    ] = total_products

    MONITOR_STATUS[
        "events_created"
    ] = total_events

    MONITOR_STATUS[
        "flickers_detected"
    ] = total_flickers

    return results


# =========================================================
# HEALTH PROBE
# =========================================================

async def probe_shopify_store(
    store: Store,
):

    adapter = (
        ShopifyAdapter(
            store.domain
        )
    )

    # Only one page is needed for health verification.

    await adapter.fetch_products(
        max_pages=1
    )

    recovered = (
        await record_store_success(
            store.id,
            allow_health_reenable=True,
        )
    )

    return recovered


# =========================================================
# RECOVERY PROBES
# =========================================================

async def run_health_recovery_probes():

    stores = (
        await get_health_recovery_candidates()
    )

    recovered_count = 0

    for store in stores:

        try:

            await probe_shopify_store(
                store
            )

            recovered_count += 1

        except Exception as error:

            error_text = (
                f"{store.name}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            await record_store_failure(
                store.id,
                error_text,
            )

            print(
                (
                    "STORE RECOVERY PROBE FAILED: "
                    f"{error_text}"
                )
            )

    MONITOR_STATUS[
        "last_health_probe"
    ] = (
        datetime.utcnow().isoformat()
    )

    MONITOR_STATUS[
        "stores_recovered"
    ] = recovered_count

    return recovered_count


# =========================================================
# MANUAL RETRY
# =========================================================

async def retry_shopify_store(
    store_id: int,
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

    except Exception as error:

        error_text = (
            f"{type(error).__name__}: "
            f"{error}"
        )

        failed_store = (
            await record_store_failure(
                store.id,
                error_text,
            )
        )

        return {
            "success": False,
            "reason": error_text,
            "store": failed_store,
        }


# =========================================================
# BACKGROUND MONITOR
# =========================================================

async def run_shopify_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

    print(
        "Lotus Shopify Monitor started."
    )

    await asyncio.sleep(
        10
    )

    last_health_probe = 0.0

    while True:

        try:

            await scan_all_shopify_stores()

            now = time.monotonic()

            if (
                now
                - last_health_probe
                >= HEALTH_PROBE_SECONDS
            ):

                await run_health_recovery_probes()

                last_health_probe = now

        except asyncio.CancelledError:

            MONITOR_STATUS[
                "running"
            ] = False

            print(
                "Lotus Shopify Monitor stopped."
            )

            raise

        except Exception as error:

            MONITOR_STATUS[
                "last_error"
            ] = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            print(
                (
                    "SHOPIFY MONITOR ERROR: "
                    f"{MONITOR_STATUS['last_error']}"
                )
            )

        await asyncio.sleep(
            POLL_SECONDS
        )


# =========================================================
# STATUS
# =========================================================

def get_shopify_monitor_status():

    return dict(
        MONITOR_STATUS
    )