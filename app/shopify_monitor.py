import asyncio

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


# =========================================================
# LOTUS SHOPIFY MONITOR
# PonDeX Trackers
# Version 0.6.2
#
# Features:
#
# Shopify Monitoring
# URL Cleanup
# Store Management
# New Product Detection
# Page Live
# Coming Soon
# Preorders
# Restocks
# Sellouts
# Price Changes
# Inventory Flicker
# =========================================================


POLL_SECONDS = 60


MONITOR_STATUS = {

    "running":
        False,

    "last_scan":
        None,

    "stores_scanned":
        0,

    "products_seen":
        0,

    "events_created":
        0,

    "flickers_detected":
        0,

    "last_error":
        None,
}


# =========================================================
# ADD / UPDATE SHOPIFY STORE
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

async def list_shopify_stores():

    if SessionLocal is None:

        return []

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
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
# GET ONE STORE
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
# ENABLE / DISABLE STORE
# =========================================================

async def set_shopify_store_active(
    store_id: int,
    active: bool,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        store = (
            result.scalar_one_or_none()
        )

        if store is None:

            return None

        store.active = active

        await session.commit()

        await session.refresh(
            store
        )

        return store


# =========================================================
# REMOVE STORE FROM MONITORING
#
# We intentionally preserve database history.
# =========================================================

async def remove_shopify_store(
    store_id: int,
):

    return await set_shopify_store_active(

        store_id=store_id,

        active=False,
    )


# =========================================================
# GET ACTIVE SHOPIFY STORES
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
# CREATE PRODUCT EVENT
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
            item[
                "price"
            ]
        ),

        currency="USD",

        in_stock=in_stock,

        region=(
            store.region
            or "US"
        ),

        language="English",

        product_type=(
            item[
                "product_type"
            ]
        ),
    )


# =========================================================
# NEW PRODUCT EVENT CLASSIFICATION
# =========================================================

def add_new_product_events(
    events_to_send,
    item,
    store,
):

    # -----------------------------------------------------
    # Every genuinely new product gets DISCOVERED.
    # -----------------------------------------------------

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

    product_state = (
        item.get(
            "product_state"
        )
    )

    # -----------------------------------------------------
    # PRODUCT PAGE EXISTS BUT NOT BUYABLE
    # -----------------------------------------------------

    if product_state == "PAGE_LIVE":

        events_to_send.append(

            make_product_event(

                event_type=(
                    ProductEventType.PAGE_LIVE
                ),

                item=item,

                store=store,

                in_stock=False,
            )
        )

    # -----------------------------------------------------
    # COMING SOON
    # -----------------------------------------------------

    elif product_state == "COMING_SOON":

        events_to_send.append(

            make_product_event(

                event_type=(
                    ProductEventType.COMING_SOON
                ),

                item=item,

                store=store,

                in_stock=False,
            )
        )

    # -----------------------------------------------------
    # LIVE PREORDER
    # -----------------------------------------------------

    elif product_state == "PREORDER_LIVE":

        events_to_send.append(

            make_product_event(

                event_type=(
                    ProductEventType.PREORDER_LIVE
                ),

                item=item,

                store=store,

                in_stock=True,
            )
        )

    # -----------------------------------------------------
    # PREORDER PAGE EXISTS BUT ORDERING NOT LIVE
    # -----------------------------------------------------

    elif product_state == "PREORDER_PAGE":

        events_to_send.append(

            make_product_event(

                event_type=(
                    ProductEventType.PAGE_LIVE
                ),

                item=item,

                store=store,

                in_stock=False,
            )
        )

    # -----------------------------------------------------
    # NORMAL LIVE PRODUCT
    # -----------------------------------------------------

    elif product_state == "STOCK_AVAILABLE":

        events_to_send.append(

            make_product_event(

                event_type=(
                    ProductEventType.STOCK_AVAILABLE
                ),

                item=item,

                store=store,

                in_stock=True,
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

    # =====================================================
    # NORMALIZE + FILTER TCG PRODUCTS
    # =====================================================

    for raw_product in raw_products:

        normalized = (
            adapter.normalize_product(
                raw_product
            )
        )

        if not normalized[
            "game"
        ]:

            continue

        normalized_products.append(
            normalized
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

        # =================================================
        # INITIAL BASELINE CHECK
        # =================================================

        existing_count_result = (
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

        existing_count = (
            existing_count_result.scalar()
            or 0
        )

        initial_seed = (
            existing_count
            == 0
        )

        stats[
            "initial_seed"
        ] = initial_seed

        # =================================================
        # PROCESS PRODUCTS
        # =================================================

        for item in normalized_products:

            product_url = (
                item[
                    "url"
                ]
            )

            result = await session.execute(

                select(
                    StoreProduct
                ).where(
                    StoreProduct.store_id
                    == store.id
                ).where(
                    StoreProduct.url
                    == product_url
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

                store_product = (
                    StoreProduct(

                        store_id=(
                            store.id
                        ),

                        product_id=(
                            product.id
                        ),

                        url=(
                            product_url
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

                        currency="USD",

                        in_stock=(
                            item[
                                "available"
                            ]
                        ),

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

                # -----------------------------------------
                # INITIAL BASELINE:
                #
                # Save everything,
                # alert nothing.
                # -----------------------------------------

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

                        in_stock=(
                            new_stock
                        ),
                    )
                )

                # -----------------------------------------
                # NORMAL STOCK EVENT
                # -----------------------------------------

                if (
                    old_stock is False
                    and new_stock is True
                ):

                    stock_event_type = (
                        ProductEventType.RESTOCK
                    )

                else:

                    stock_event_type = (
                        ProductEventType.SOLD_OUT
                    )

                events_to_send.append(

                    make_product_event(

                        event_type=(
                            stock_event_type
                        ),

                        item=item,

                        store=store,

                        in_stock=(
                            new_stock
                        ),
                    )
                )

                # -----------------------------------------
                # INVENTORY FLICKER
                #
                # Additional event.
                # Never suppress the underlying
                # RESTOCK / SOLD_OUT transition.
                # -----------------------------------------

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

                            in_stock=(
                                new_stock
                            ),
                        )
                    )

                    stats[
                        "flickers"
                    ] += 1

                    print(
                        (
                            "INVENTORY FLICKER DETECTED: "
                            f"{store.name} | "
                            f"{item['title']} | "
                            f"Transitions="
                            f"{flicker_result['transition_count']}"
                        )
                    )

            # =================================================
            # PRICE CHANGE
            # =================================================

            if (
                old_price is not None
                and new_price is not None
                and old_price != new_price
            ):

                changed = True

                session.add(

                    PriceHistory(

                        store_product_id=(
                            store_product.id
                        ),

                        price=(
                            new_price
                        ),

                        currency="USD",
                    )
                )

                if (
                    new_price
                    < old_price
                ):

                    price_event_type = (
                        ProductEventType.PRICE_DROP
                    )

                else:

                    price_event_type = (
                        ProductEventType.PRICE_INCREASE
                    )

                events_to_send.append(

                    make_product_event(

                        event_type=(
                            price_event_type
                        ),

                        item=item,

                        store=store,

                        in_stock=(
                            new_stock
                        ),
                    )
                )

            # =================================================
            # UPDATE CURRENT SNAPSHOT
            # =================================================

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

        # =================================================
        # COMMIT STORE STATE
        # =================================================

        await session.commit()

    # =====================================================
    # PUSH EVENTS AFTER DATABASE COMMIT
    # =====================================================

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
# SCAN ALL STORES
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
                "SHOPIFY SCAN ERROR: "
                f"{error_text}"
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
# BACKGROUND SHOPIFY MONITOR
# =========================================================

async def run_shopify_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

    print(
        "Lotus Shopify Monitor started."
    )

    # Give Discord, Redis and PostgreSQL
    # time to initialize.

    await asyncio.sleep(
        10
    )

    while True:

        try:

            await scan_all_shopify_stores()

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
                "SHOPIFY MONITOR ERROR: "
                f"{MONITOR_STATUS['last_error']}"
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