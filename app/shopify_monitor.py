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
# Version 0.6
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

    "last_error":
        None,
}


# =========================================================
# ADD SHOPIFY STORE
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
            )
        )

        return list(
            result.scalars().all()
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

        normalized = (
            adapter.normalize_product(
                raw_product
            )
        )

        # Ignore unrelated products.
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

        "initial_seed":
            False,
    }

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

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

        # -------------------------------------------------
        # IMPORTANT:
        #
        # If this is the first scan ever for this store,
        # establish the baseline without alerting hundreds
        # of old products.
        # -------------------------------------------------

        initial_seed = (
            existing_count == 0
        )

        stats[
            "initial_seed"
        ] = initial_seed

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

                    language=(
                        "English"
                    ),
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

                # Do not blast alerts during first seed.
                if not initial_seed:

                    events_to_send.append(

                        ProductEvent(

                            event_type=(
                                ProductEventType.DISCOVERED
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
                                product_url
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
                    )

                    # If the newly-discovered product
                    # is immediately purchasable,
                    # create a live-stock event too.
                    if item[
                        "available"
                    ]:

                        events_to_send.append(

                            ProductEvent(

                                event_type=(
                                    ProductEventType.STOCK_AVAILABLE
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
                                    product_url
                                ),

                                price=(
                                    item[
                                        "price"
                                    ]
                                ),

                                currency="USD",

                                in_stock=True,

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
                        )

                continue

            # =================================================
            # EXISTING PRODUCT
            # =================================================

            old_stock = (
                store_product.in_stock
            )

            old_price = (
                store_product.price
            )

            new_stock = (
                item[
                    "available"
                ]
            )

            new_price = (
                item[
                    "price"
                ]
            )

            changed = False

            # =================================================
            # STOCK CHANGES
            # =================================================

            if (
                old_stock is False
                and new_stock is True
            ):

                changed = True

                events_to_send.append(

                    ProductEvent(

                        event_type=(
                            ProductEventType.RESTOCK
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
                            product_url
                        ),

                        price=(
                            new_price
                        ),

                        currency="USD",

                        in_stock=True,

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
                )

            elif (
                old_stock is True
                and new_stock is False
            ):

                changed = True

                events_to_send.append(

                    ProductEvent(

                        event_type=(
                            ProductEventType.SOLD_OUT
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
                            product_url
                        ),

                        price=(
                            new_price
                        ),

                        currency="USD",

                        in_stock=False,

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
                )

            # =================================================
            # PRICE CHANGES
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

                    price_event = (
                        ProductEventType.PRICE_DROP
                    )

                else:

                    price_event = (
                        ProductEventType.PRICE_INCREASE
                    )

                events_to_send.append(

                    ProductEvent(

                        event_type=(
                            price_event
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
                            product_url
                        ),

                        price=(
                            new_price
                        ),

                        currency="USD",

                        in_stock=(
                            new_stock
                        ),

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
                )

            # =================================================
            # UPDATE SNAPSHOT
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

        await session.commit()

    # =====================================================
    # SEND EVENTS AFTER DATABASE COMMIT
    # =====================================================

    for event in events_to_send:

        result = (
            await process_product_event(
                event
            )
        )

        if (
            result[
                "redis_saved"
            ]
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

    total_products = 0
    total_events = 0
    stores_scanned = 0

    results = []

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

    return results


# =========================================================
# BACKGROUND MONITOR LOOP
# =========================================================

async def run_shopify_monitor():

    MONITOR_STATUS[
        "running"
    ] = True

    print(
        "Lotus Shopify Monitor started."
    )

    # Give the rest of Lotus time to initialize.
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
# STATUS
# =========================================================

def get_shopify_monitor_status():

    return dict(
        MONITOR_STATUS
    )