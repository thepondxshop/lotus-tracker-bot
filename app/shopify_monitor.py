import asyncio
import time

from datetime import datetime

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
# Version 0.9.0
#
# Historical Pricing + Deal Score v1
# Smart Cart v1 data passthrough
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

    "duplicate_rows_detected":
        0,

    "last_error":
        None,
}


# =========================================================
# ADD SHOPIFY STORE
# =========================================================

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

        result = await session.execute(

            select(
                Store
            ).where(
                Store.domain
                == domain
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

            name=name,

            domain=domain,

            platform="shopify",

            region=(
                region.upper()
            ),

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
# LIST SHOPIFY STORES
# =========================================================

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


# =========================================================
# GET SHOPIFY STORE
# =========================================================

async def get_shopify_store(
    store_id,
):

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
            result.scalars().first()
        )


# =========================================================
# ENABLE / DISABLE
# =========================================================

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


# =========================================================
# REMOVE STORE
# =========================================================

async def remove_shopify_store(
    store_id,
):

    return await mark_store_removed(
        store_id
    )


# =========================================================
# RESTORE STORE
# =========================================================

async def restore_shopify_store(
    store_id,
):

    return await restore_removed_store(
        store_id
    )


# =========================================================
# ACTIVE SHOPIFY STORES
# =========================================================

async def get_shopify_stores():

    async with SessionLocal() as session:

        result = await session.execute(

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
    old_price=None,
    deal_data=None,
):

    deal_fields = {}

    if deal_data is not None:
        try:
            deal_fields = (
                deal_data.to_event_fields()
            )
        except Exception:
            deal_fields = {}

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

        # =================================================
        # PRICING
        # =================================================

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

        # =================================================
        # HISTORICAL PRICE INTELLIGENCE
        # =================================================

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

        # =================================================
        # INVENTORY
        # =================================================

        in_stock=(
            in_stock
        ),

        # =================================================
        # PRODUCT INFORMATION
        # =================================================

        region=(
            store.region
            or "US"
        ),

        language="English",

        product_type=(
            item.get(
                "product_type",
                "TCG Product",
            )
        ),

        product_category=(
            item.get(
                "product_category",
                "UNKNOWN",
            )
        ),

        # =================================================
        # SOURCE
        # =================================================

        source_type="shopify",

        retailer_key=(
            store.domain
        ),

        image_url=(
            item.get(
                "image_url"
            )
        ),

        # =================================================
        # SMART CART
        # =================================================

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

            in_stock=(
                item[
                    "available"
                ]
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
            )
        )


# =========================================================
# FIND STORE PRODUCT
# =========================================================

async def find_store_product(
    session,
    store_id,
    url,
):

    result = await session.execute(

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

    matches = list(
        result.scalars().all()
    )

    if (
        len(
            matches
        )
        > 1
    ):

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


# =========================================================
# DEAL INTELLIGENCE HELPER
# =========================================================

async def get_deal_data(
    session,
    *,
    store_product,
    current_price,
    old_price=None,
    currency="USD",
):

    if (
        store_product is None
        or store_product.id is None
        or current_price is None
    ):
        return None

    try:

        return await analyze_price_history(
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
        )

    except Exception as error:

        print(
            (
                "DEAL INTELLIGENCE ERROR | "
                f"StoreProduct={getattr(store_product, 'id', None)} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return None


# =========================================================
# SCAN STORE
# =========================================================

async def scan_shopify_store(
    store,
):

    adapter = ShopifyAdapter(

        store.domain,

        region=(
            store.region
            or "US"
        ),
    )

    # =====================================================
    # DETECT NATIVE STOREFRONT CURRENCY
    # =====================================================

    native_currency = (
        await adapter.fetch_store_currency()
    )

    print(
        (
            "SHOPIFY CURRENCY | "
            f"Store={store.name} | "
            f"Currency={native_currency}"
        )
    )

    # =====================================================
    # FETCH PRODUCTS
    # =====================================================

    raw_products = (
        await adapter.fetch_products()
    )

    normalized_products = []

    seen_urls = set()

    # =====================================================
    # NORMALIZE PRODUCTS
    # =====================================================

    for raw_product in raw_products:

        item = (
            adapter.normalize_product(
                raw_product
            )
        )

        if not item.get(
            "game"
        ):

            continue

        if not item.get(
            "url"
        ):

            continue

        if (
            item[
                "url"
            ]
            in seen_urls
        ):

            continue

        seen_urls.add(
            item[
                "url"
            ]
        )

        normalized_products.append(
            item
        )

    # =====================================================
    # EVENTS
    # =====================================================

    events_to_send = []

    stats = {

        "store":
            store.name,

        "currency":
            native_currency,

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

    # =====================================================
    # DATABASE
    # =====================================================

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

        # =================================================
        # EACH PRODUCT
        # =================================================

        for item in normalized_products:

            store_product = (
                await find_store_product(
                    session,
                    store.id,
                    item[
                        "url"
                    ],
                )
            )

            # =================================================
            # NEW PRODUCT
            # =================================================

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

                    status=(
                        "in_stock"
                        if item[
                            "available"
                        ]
                        else "sold_out"
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

                session.add(
                    store_product
                )

                try:

                    await session.flush()

                except IntegrityError:

                    await session.rollback()

                    continue

                # ---------------------------------------------
                # PRICE HISTORY BASELINE
                #
                # v0.9.0 begins recording the first observed
                # price for new products. This gives Deal
                # Intelligence a real baseline without writing
                # the same unchanged price every minute.
                # ---------------------------------------------

                if (
                    item.get(
                        "price"
                    )
                    is not None
                ):

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

                # Initial seed populates the DB silently so a
                # restart does not flood Discord.

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

            old_currency = (
                store_product.currency
                or "USD"
            )

            new_currency = (
                item[
                    "currency"
                ]
            )

            changed = False

            # =================================================
            # CURRENCY CORRECTION
            #
            # Never generate a fake price-change alert just
            # because the monitor corrected the currency.
            # =================================================

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
                        f"{old_currency}->{new_currency}"
                    )
                )

                store_product.currency = (
                    new_currency
                )

                # Start a clean baseline in the corrected
                # currency if a price exists.
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

            # =================================================
            # STOCK TRANSITION
            # =================================================

            if (
                old_stock
                != new_stock
            ):

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

                    ProductEventType.RESTOCK

                    if (
                        not old_stock
                        and new_stock
                    )

                    else

                    ProductEventType.SOLD_OUT
                )

                # Price Intelligence is most useful on a
                # RESTOCK. We calculate it for restocks but not
                # sold-out alerts.
                restock_deal_data = None

                if (
                    stock_event
                    == ProductEventType.RESTOCK
                    and new_price is not None
                ):

                    restock_deal_data = (
                        await get_deal_data(
                            session,
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

                # ---------------------------------------------
                # INVENTORY FLICKER / MICRO RESTOCK
                # ---------------------------------------------

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

            # =================================================
            # PRICE CHANGE
            # =================================================

            if (
                not currency_changed
                and old_price is not None
                and new_price is not None
                and old_price
                != new_price
            ):

                changed = True

                # Calculate BEFORE recording the new history
                # row. The engine folds current_price into the
                # working set itself, avoiding a double count.
                price_deal_data = (
                    await get_deal_data(
                        session,
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

                    if (
                        new_price
                        < old_price
                    )

                    else

                    ProductEventType.PRICE_INCREASE
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

            # =================================================
            # UPDATE STORED STATE
            # =================================================

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

        # =====================================================
        # COMMIT
        # =====================================================

        await session.commit()

    # =========================================================
    # SEND EVENTS AFTER DATABASE COMMIT
    # =========================================================

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

    return stats


# =========================================================
# SCAN ALL SHOPIFY STORES
# =========================================================

async def scan_all_shopify_stores():

    stores = (
        await get_shopify_stores()
    )

    results = []

    total_products = 0

    total_events = 0

    total_flickers = 0

    stores_scanned = 0

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

    return results


# =========================================================
# HEALTH
# =========================================================

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

    await adapter.fetch_products(
        max_pages=1
    )

    return await record_store_success(

        store.id,

        allow_health_reenable=True,
    )


# =========================================================
# HEALTH RECOVERY
# =========================================================

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

    return recovered_count


# =========================================================
# RETRY SHOPIFY STORE
# =========================================================

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

            "success":
                False,

            "reason":
                "NOT_FOUND",

            "store":
                None,
        }

    if (
        store.disabled_reason
        == "MANUAL"
    ):

        return {

            "success":
                False,

            "reason":
                "MANUAL",

            "store":
                store,
        }

    if (
        store.disabled_reason
        == "REMOVED"
    ):

        return {

            "success":
                False,

            "reason":
                "REMOVED",

            "store":
                store,
        }

    try:

        recovered = (
            await probe_shopify_store(
                store
            )
        )

        return {

            "success":
                True,

            "reason":
                "ONLINE",

            "store":
                recovered,
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

            "success":
                False,

            "reason":
                str(
                    error
                ),

            "store":
                failed_store,
        }


# =========================================================
# RUN MONITOR
# =========================================================

async def run_shopify_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

    print(
        "Lotus Shopify Monitor v0.9.0 started."
    )

    await asyncio.sleep(
        10
    )

    last_health_probe = (
        0.0
    )

    while True:

        try:

            await scan_all_shopify_stores()

            now = (
                time.monotonic()
            )

            if (
                now
                - last_health_probe
                >= HEALTH_PROBE_SECONDS
            ):

                await run_health_recovery_probes()

                last_health_probe = (
                    now
                )

        except asyncio.CancelledError:

            MONITOR_STATUS[
                "running"
            ] = False

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
                    "SHOPIFY MONITOR LOOP ERROR | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

        await asyncio.sleep(
            POLL_SECONDS
        )


# =========================================================
# MONITOR STATUS
# =========================================================

def get_shopify_monitor_status():

    return dict(
        MONITOR_STATUS
    )