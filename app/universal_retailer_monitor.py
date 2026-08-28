"""
Lotus Tracker Bot
PonDeX Trackers

Universal Retailer Monitor
Version: 1.0.4

Purpose
-------
Monitor non-Shopify retailers through the universal retailer
adapter system.

Current event lifecycle:
- DISCOVERED
- STOCK_AVAILABLE
- RESTOCK
- SOLD_OUT
- PRICE_DROP
- PRICE_INCREASE

Important:
- Database changes are committed before Discord/Redis events
  are published.
- Shopify continues to use shopify_monitor.py.
- Universal retailers do NOT automatically receive Smart Cart.
- No checkout automation.
- No CAPTCHA / queue / anti-bot bypass.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal

from app.event_service import (
    process_product_event,
)

from app.events import (
    ProductEvent,
)

from app.models import (
    PriceHistory,
    Product,
    Store,
    StoreProduct,
)

from app.retailer_registry import (
    build_retailer_adapter,
    normalize_platform,
)


# =========================================================
# VERSION
# =========================================================

VERSION = "1.0.4"


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(
    "lotus.universal_retailer_monitor"
)


# =========================================================
# SETTINGS
# =========================================================

DEFAULT_SCAN_INTERVAL = 60

MAX_STORES_PER_CYCLE = 100

SUPPORTED_UNIVERSAL_PLATFORMS = {
    "square_weebly",
    "woocommerce",
    "bigcommerce",
    "custom",
}


# =========================================================
# MONITOR STATUS
# =========================================================

MONITOR_STATUS: dict[str, Any] = {
    "version": VERSION,
    "running": False,
    "last_scan_started_at": None,
    "last_scan_completed_at": None,
    "last_error": None,
    "stores_scanned": 0,
    "stores_failed": 0,
    "products_seen": 0,
    "products_created": 0,
    "products_updated": 0,
    "events_created": 0,
    "price_changes": 0,
    "restocks": 0,
    "sold_out": 0,
}


# =========================================================
# HELPERS
# =========================================================

def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_text(
    value: Any,
    default: str = "",
) -> str:

    if value is None:
        return default

    value = str(
        value
    ).strip()

    return value or default


def normalize_optional_text(
    value: Any,
) -> str | None:

    if value is None:
        return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    return value


def normalize_price(
    value: Any,
) -> float | None:

    if value is None:
        return None

    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def normalize_bool(
    value: Any,
) -> bool:

    if isinstance(
        value,
        bool,
    ):
        return value

    if value is None:
        return False

    if isinstance(
        value,
        str,
    ):

        lowered = (
            value.strip().lower()
        )

        if lowered in {
            "true",
            "1",
            "yes",
            "y",
            "available",
            "in_stock",
            "instock",
        }:
            return True

        if lowered in {
            "false",
            "0",
            "no",
            "n",
            "unavailable",
            "out_of_stock",
            "outofstock",
            "sold_out",
            "soldout",
        }:
            return False

    return bool(
        value
    )


def normalize_currency(
    value: Any,
) -> str:

    value = normalize_text(
        value,
        "USD",
    )

    return value.upper()


def normalize_region(
    value: Any,
) -> str:

    value = normalize_text(
        value,
        "US",
    )

    return value.upper()


def normalize_product_category(
    value: Any,
) -> str:

    value = normalize_text(
        value,
        "UNKNOWN",
    ).upper()

    if value not in {
        "SEALED",
        "SINGLE",
        "ACCESSORY",
        "UNKNOWN",
    }:
        return "UNKNOWN"

    return value


def normalize_product_family(
    value: Any,
) -> str:

    value = normalize_text(
        value,
        "UNKNOWN",
    ).upper()

    if value not in {
        "GLOBAL_STANDARD",
        "JP",
        "KR",
        "CN",
        "UNKNOWN",
    }:
        return "UNKNOWN"

    return value


def family_language(
    product_family: str,
) -> str:

    mapping = {
        "GLOBAL_STANDARD": "English",
        "JP": "Japanese",
        "KR": "Korean",
        "CN": "Simplified Chinese",
        "UNKNOWN": "Unknown",
    }

    return mapping.get(
        product_family,
        "Unknown",
    )


def serialize_platform_data(
    value: Any,
) -> str | None:

    if value is None:
        return None

    if isinstance(
        value,
        str,
    ):

        value = value.strip()

        return (
            value
            if value
            else None
        )

    try:

        return json.dumps(
            value,
            separators=(
                ",",
                ":",
            ),
            sort_keys=True,
            default=str,
        )

    except Exception:

        try:
            return str(
                value
            )

        except Exception:
            return None


# =========================================================
# EVENT CREATION
# =========================================================

def make_product_event(
    *,
    event_type: str,
    item: dict[str, Any],
    store: Store,
    in_stock: bool,
    old_price: float | None = None,
) -> ProductEvent:

    """
    Build the standard Lotus ProductEvent used by
    event_service.py and the Discord worker.

    Keep this compatible with the existing Shopify event
    pipeline.
    """

    product_family = normalize_product_family(
        item.get(
            "product_family"
        )
    )

    product_category = normalize_product_category(
        item.get(
            "product_category"
        )
    )

    platform = normalize_platform(
        getattr(
            store,
            "platform",
            None,
        )
    )

    return ProductEvent(
        event_type=event_type,

        game=normalize_text(
            item.get(
                "game"
            ),
            "Unknown",
        ),

        product_name=normalize_text(
            item.get(
                "title"
            ),
            "Unknown Product",
        ),

        store_name=normalize_text(
            getattr(
                store,
                "name",
                None,
            ),
            "Unknown Store",
        ),

        product_url=normalize_text(
            item.get(
                "url"
            )
        ),

        price=normalize_price(
            item.get(
                "price"
            )
        ),

        old_price=normalize_price(
            old_price
        ),

        currency=normalize_currency(
            item.get(
                "currency"
            )
        ),

        in_stock=bool(
            in_stock
        ),

        region=normalize_region(
            getattr(
                store,
                "region",
                None,
            )
        ),

        language=family_language(
            product_family
        ),

        product_type=normalize_text(
            item.get(
                "product_type"
            ),
            "TCG Product",
        ),

        product_category=product_category,

        product_family=product_family,

        source_type=platform,

        retailer_key=normalize_text(
            getattr(
                store,
                "domain",
                None,
            )
        ),

        image_url=normalize_optional_text(
            item.get(
                "image_url"
            )
        ),

        # Universal retailers intentionally do not invent
        # Shopify variants.

        variant_id=normalize_optional_text(
            item.get(
                "variant_id"
            )
        ),

        purchase_limit=item.get(
            "purchase_limit"
        ),

        # Only adapters with a legitimate supported cart
        # mechanism should ever populate this.

        cart_base_url=normalize_optional_text(
            item.get(
                "cart_base_url"
            )
        ),
    )


# =========================================================
# DATABASE LOOKUPS
# =========================================================

async def find_product(
    session,
    *,
    game: str,
    title: str,
    product_family: str,
) -> Product | None:

    """
    Locate an existing normalized Lotus Product.

    We intentionally avoid fuzzy matching here.

    Retailer-level identity is maintained by StoreProduct.
    """

    statement = (
        select(
            Product
        )
        .where(
            Product.game == game,
            Product.name == title,
            Product.product_family == product_family,
        )
        .limit(
            1
        )
    )

    result = await session.execute(
        statement
    )

    return result.scalar_one_or_none()


async def find_store_product(
    session,
    *,
    store_id: int,
    url: str,
) -> StoreProduct | None:

    statement = (
        select(
            StoreProduct
        )
        .where(
            StoreProduct.store_id == store_id,
            StoreProduct.url == url,
        )
        .limit(
            1
        )
    )

    result = await session.execute(
        statement
    )

    return result.scalar_one_or_none()


# =========================================================
# PRODUCT CREATION
# =========================================================

async def get_or_create_product(
    session,
    *,
    item: dict[str, Any],
    store: Store,
) -> tuple[Product, bool]:

    game = normalize_text(
        item.get(
            "game"
        )
    )

    title = normalize_text(
        item.get(
            "title"
        )
    )

    product_family = normalize_product_family(
        item.get(
            "product_family"
        )
    )

    product_category = normalize_product_category(
        item.get(
            "product_category"
        )
    )

    product_type = normalize_text(
        item.get(
            "product_type"
        ),
        "TCG Product",
    )

    region = normalize_region(
        getattr(
            store,
            "region",
            None,
        )
    )

    language = family_language(
        product_family
    )

    existing = await find_product(
        session,
        game=game,
        title=title,
        product_family=product_family,
    )

    if existing is not None:

        # Keep classification metadata current without
        # changing identity.

        existing.product_type = (
            product_type
        )

        existing.product_category = (
            product_category
        )

        existing.product_family = (
            product_family
        )

        existing.region = (
            region
        )

        existing.language = (
            language
        )

        return (
            existing,
            False,
        )

    product = Product(
        game=game,
        name=title,
        canonical_name=title,
        product_type=product_type,
        product_category=product_category,
        product_family=product_family,
        region=region,
        language=language,
    )

    session.add(
        product
    )

    # We need the ID for StoreProduct, but we do NOT commit
    # yet. The entire retailer product transaction remains
    # together.

    await session.flush()

    return (
        product,
        True,
    )


# =========================================================
# PRICE HISTORY
# =========================================================

def add_price_history(
    session,
    *,
    store_product: StoreProduct,
    price: float | None,
    currency: str,
) -> None:

    if price is None:
        return

    history = PriceHistory(
        store_product_id=store_product.id,
        price=price,
        currency=currency,
        recorded_at=utcnow(),
    )

    session.add(
        history
    )


# =========================================================
# NEW PRODUCT
# =========================================================

async def create_store_product(
    session,
    *,
    store: Store,
    product: Product,
    item: dict[str, Any],
) -> tuple[StoreProduct, list[ProductEvent]]:

    url = normalize_text(
        item.get(
            "url"
        )
    )

    price = normalize_price(
        item.get(
            "price"
        )
    )

    currency = normalize_currency(
        item.get(
            "currency"
        )
    )

    available = normalize_bool(
        item.get(
            "available"
        )
    )

    external_product_id = normalize_optional_text(
        item.get(
            "external_product_id"
        )
        or item.get(
            "external_id"
        )
    )

    offer_id = normalize_optional_text(
        item.get(
            "offer_id"
        )
    )

    sku = normalize_optional_text(
        item.get(
            "sku"
        )
    )

    variant_id = normalize_optional_text(
        item.get(
            "variant_id"
        )
    )

    purchase_limit = item.get(
        "purchase_limit"
    )

    platform_data = serialize_platform_data(
        item.get(
            "platform_data"
        )
    )

    product_state = normalize_text(
        item.get(
            "product_state"
        ),
        (
            "STOCK_AVAILABLE"
            if available
            else "PAGE_LIVE"
        ),
    )

    store_product = StoreProduct(
        store_id=store.id,
        product_id=product.id,
        url=url,
        sku=sku,
        variant_id=variant_id,
        external_product_id=external_product_id,
        offer_id=offer_id,
        platform_data=platform_data,
        purchase_limit=purchase_limit,
        status=product_state,
        price=price,
        currency=currency,
        in_stock=available,
        last_seen_at=utcnow(),
    )

    session.add(
        store_product
    )

    await session.flush()

    add_price_history(
        session,
        store_product=store_product,
        price=price,
        currency=currency,
    )

    events: list[ProductEvent] = []

    # Every first-seen supported TCG product gets DISCOVERED.

    events.append(
        make_product_event(
            event_type="DISCOVERED",
            item=item,
            store=store,
            in_stock=available,
        )
    )

    # If it is already purchasable on first discovery,
    # produce the stock event as well.
    #
    # This preserves discovery intelligence separately from
    # immediate availability.

    if available:

        events.append(
            make_product_event(
                event_type="STOCK_AVAILABLE",
                item=item,
                store=store,
                in_stock=True,
            )
        )

    return (
        store_product,
        events,
    )


# =========================================================
# EXISTING PRODUCT UPDATE
# =========================================================

async def update_store_product(
    session,
    *,
    store: Store,
    store_product: StoreProduct,
    item: dict[str, Any],
) -> list[ProductEvent]:

    events: list[ProductEvent] = []

    old_stock = bool(
        store_product.in_stock
    )

    old_price = normalize_price(
        store_product.price
    )

    old_currency = normalize_currency(
        store_product.currency
    )

    new_stock = normalize_bool(
        item.get(
            "available"
        )
    )

    new_price = normalize_price(
        item.get(
            "price"
        )
    )

    new_currency = normalize_currency(
        item.get(
            "currency"
        )
        or old_currency
    )

    # =====================================================
    # IDENTIFIERS / METADATA
    # =====================================================

    new_external_product_id = normalize_optional_text(
        item.get(
            "external_product_id"
        )
        or item.get(
            "external_id"
        )
    )

    new_offer_id = normalize_optional_text(
        item.get(
            "offer_id"
        )
    )

    new_sku = normalize_optional_text(
        item.get(
            "sku"
        )
    )

    new_variant_id = normalize_optional_text(
        item.get(
            "variant_id"
        )
    )

    new_platform_data = serialize_platform_data(
        item.get(
            "platform_data"
        )
    )

    if new_external_product_id is not None:
        store_product.external_product_id = (
            new_external_product_id
        )

    if new_offer_id is not None:
        store_product.offer_id = (
            new_offer_id
        )

    if new_sku is not None:
        store_product.sku = (
            new_sku
        )

    if new_variant_id is not None:
        store_product.variant_id = (
            new_variant_id
        )

    if new_platform_data is not None:
        store_product.platform_data = (
            new_platform_data
        )

    if item.get(
        "purchase_limit"
    ) is not None:

        store_product.purchase_limit = (
            item.get(
                "purchase_limit"
            )
        )

    # =====================================================
    # STOCK TRANSITIONS
    # =====================================================

    if (
        not old_stock
        and new_stock
    ):

        events.append(
            make_product_event(
                event_type="RESTOCK",
                item=item,
                store=store,
                in_stock=True,
                old_price=old_price,
            )
        )

        MONITOR_STATUS[
            "restocks"
        ] += 1

    elif (
        old_stock
        and not new_stock
    ):

        events.append(
            make_product_event(
                event_type="SOLD_OUT",
                item=item,
                store=store,
                in_stock=False,
                old_price=old_price,
            )
        )

        MONITOR_STATUS[
            "sold_out"
        ] += 1

    # =====================================================
    # PRICE TRANSITIONS
    # =====================================================

    price_changed = False

    if (
        old_price is not None
        and new_price is not None
        and old_currency == new_currency
        and old_price != new_price
    ):

        price_changed = True

        if new_price < old_price:

            events.append(
                make_product_event(
                    event_type="PRICE_DROP",
                    item=item,
                    store=store,
                    in_stock=new_stock,
                    old_price=old_price,
                )
            )

        elif new_price > old_price:

            events.append(
                make_product_event(
                    event_type="PRICE_INCREASE",
                    item=item,
                    store=store,
                    in_stock=new_stock,
                    old_price=old_price,
                )
            )

        MONITOR_STATUS[
            "price_changes"
        ] += 1

    # =====================================================
    # PRICE HISTORY
    # =====================================================

    if (
        new_price is not None
        and (
            old_price is None
            or price_changed
            or old_currency != new_currency
        )
    ):

        add_price_history(
            session,
            store_product=store_product,
            price=new_price,
            currency=new_currency,
        )

    # =====================================================
    # CURRENT STATE
    # =====================================================

    store_product.price = (
        new_price
    )

    store_product.currency = (
        new_currency
    )

    store_product.in_stock = (
        new_stock
    )

    store_product.status = normalize_text(
        item.get(
            "product_state"
        ),
        (
            "STOCK_AVAILABLE"
            if new_stock
            else "PAGE_LIVE"
        ),
    )

    store_product.last_seen_at = (
        utcnow()
    )

    return events


# =========================================================
# PROCESS ONE NORMALIZED PRODUCT
# =========================================================

async def process_normalized_product(
    *,
    store: Store,
    item: dict[str, Any],
) -> dict[str, Any]:

    result = {
        "processed": False,
        "created": False,
        "updated": False,
        "events": 0,
        "reason": None,
    }

    # =====================================================
    # BASIC VALIDATION
    # =====================================================

    if not isinstance(
        item,
        dict,
    ):

        result[
            "reason"
        ] = "INVALID_ITEM"

        return result

    game = normalize_text(
        item.get(
            "game"
        )
    )

    title = normalize_text(
        item.get(
            "title"
        )
    )

    url = normalize_text(
        item.get(
            "url"
        )
    )

    if not game:

        result[
            "reason"
        ] = "NO_SUPPORTED_GAME"

        return result

    if not title:

        result[
            "reason"
        ] = "NO_TITLE"

        return result

    if not url:

        result[
            "reason"
        ] = "NO_URL"

        return result

    # =====================================================
    # NORMALIZE ITEM
    # =====================================================

    item = dict(
        item
    )

    item[
        "game"
    ] = game

    item[
        "title"
    ] = title

    item[
        "url"
    ] = url

    item[
        "product_family"
    ] = normalize_product_family(
        item.get(
            "product_family"
        )
    )

    item[
        "product_category"
    ] = normalize_product_category(
        item.get(
            "product_category"
        )
    )

    item[
        "currency"
    ] = normalize_currency(
        item.get(
            "currency"
        )
    )

    item[
        "available"
    ] = normalize_bool(
        item.get(
            "available"
        )
    )

    events_to_send: list[ProductEvent] = []

    # =====================================================
    # DATABASE TRANSACTION
    # =====================================================

    try:

        async with SessionLocal() as session:

            store_product = (
                await find_store_product(
                    session,
                    store_id=store.id,
                    url=url,
                )
            )

            if store_product is None:

                (
                    product,
                    product_created,
                ) = await get_or_create_product(
                    session,
                    item=item,
                    store=store,
                )

                (
                    store_product,
                    new_events,
                ) = await create_store_product(
                    session,
                    store=store,
                    product=product,
                    item=item,
                )

                events_to_send.extend(
                    new_events
                )

                result[
                    "created"
                ] = True

                MONITOR_STATUS[
                    "products_created"
                ] += 1

                logger.info(
                    (
                        "UNIVERSAL PRODUCT DISCOVERED | "
                        "Store=%s | "
                        "Game=%s | "
                        "Family=%s | "
                        "Title=%s | "
                        "URL=%s"
                    ),
                    store.name,
                    game,
                    item[
                        "product_family"
                    ],
                    title,
                    url,
                )

            else:

                product_result = (
                    await session.execute(
                        select(
                            Product
                        )
                        .where(
                            Product.id
                            ==
                            store_product.product_id
                        )
                        .limit(
                            1
                        )
                    )
                )

                product = (
                    product_result
                    .scalar_one_or_none()
                )

                # Keep normalized product classification
                # current if the underlying Product exists.

                if product is not None:

                    product.game = (
                        game
                    )

                    product.name = (
                        title
                    )

                    product.product_type = normalize_text(
                        item.get(
                            "product_type"
                        ),
                        product.product_type
                        or "TCG Product",
                    )

                    product.product_category = (
                        item[
                            "product_category"
                        ]
                    )

                    product.product_family = (
                        item[
                            "product_family"
                        ]
                    )

                    product.region = normalize_region(
                        store.region
                    )

                    product.language = family_language(
                        item[
                            "product_family"
                        ]
                    )

                update_events = (
                    await update_store_product(
                        session,
                        store=store,
                        store_product=store_product,
                        item=item,
                    )
                )

                events_to_send.extend(
                    update_events
                )

                result[
                    "updated"
                ] = True

                MONITOR_STATUS[
                    "products_updated"
                ] += 1

            # -------------------------------------------------
            # CRITICAL:
            #
            # Commit state BEFORE publishing events.
            # -------------------------------------------------

            await session.commit()

    except Exception as error:

        result[
            "reason"
        ] = (
            f"DATABASE_ERROR:"
            f"{type(error).__name__}"
        )

        logger.exception(
            (
                "UNIVERSAL PRODUCT DATABASE ERROR | "
                "Store=%s | "
                "Title=%s | "
                "URL=%s"
            ),
            store.name,
            title,
            url,
        )

        return result

    # =====================================================
    # PUBLISH EVENTS AFTER COMMIT
    # =====================================================

    published_events = 0

    for event in events_to_send:

        try:

            await process_product_event(
                event
            )

            published_events += 1

            MONITOR_STATUS[
                "events_created"
            ] += 1

            logger.info(
                (
                    "UNIVERSAL EVENT | "
                    "Store=%s | "
                    "Event=%s | "
                    "Game=%s | "
                    "Title=%s"
                ),
                store.name,
                event.event_type,
                game,
                title,
            )

        except Exception:

            # The DB state has already been committed.
            #
            # A Redis/Discord pipeline problem must not roll
            # retailer state backward and cause false repeated
            # restocks on the next scan.

            logger.exception(
                (
                    "UNIVERSAL EVENT PUBLISH ERROR | "
                    "Store=%s | "
                    "Game=%s | "
                    "Title=%s"
                ),
                store.name,
                game,
                title,
            )

    result[
        "processed"
    ] = True

    result[
        "events"
    ] = published_events

    return result


# =========================================================
# SCAN ONE STORE
# =========================================================

async def scan_store(
    store: Store,
) -> dict[str, Any]:

    result = {
        "store_id": store.id,
        "store_name": store.name,
        "domain": store.domain,
        "platform": store.platform,
        "success": False,
        "products": 0,
        "created": 0,
        "updated": 0,
        "events": 0,
        "error": None,
    }

    platform = normalize_platform(
        store.platform
    )

    if platform == "shopify":

        result[
            "error"
        ] = "SHOPIFY_USES_SHOPIFY_MONITOR"

        return result

    if not store.domain:

        result[
            "error"
        ] = "NO_DOMAIN"

        return result

    # =====================================================
    # BUILD ADAPTER
    # =====================================================

    try:

        adapter = (
            build_retailer_adapter(
                store
            )
        )

    except Exception as error:

        result[
            "error"
        ] = (
            f"ADAPTER_ERROR:"
            f"{type(error).__name__}:"
            f"{error}"
        )

        logger.exception(
            (
                "UNIVERSAL ADAPTER ERROR | "
                "Store=%s | "
                "Platform=%s"
            ),
            store.name,
            platform,
        )

        return result

    # =====================================================
    # FETCH NORMALIZED PRODUCTS
    # =====================================================

    try:

        products = (
            await adapter.get_normalized_products()
        )

    except Exception as error:

        result[
            "error"
        ] = (
            f"FETCH_ERROR:"
            f"{type(error).__name__}:"
            f"{error}"
        )

        logger.exception(
            (
                "UNIVERSAL FETCH ERROR | "
                "Store=%s | "
                "Platform=%s | "
                "Domain=%s"
            ),
            store.name,
            platform,
            store.domain,
        )

        return result

    products = (
        products
        or []
    )

    result[
        "products"
    ] = len(
        products
    )

    MONITOR_STATUS[
        "products_seen"
    ] += len(
        products
    )

    logger.info(
        (
            "UNIVERSAL STORE SCAN | "
            "Store=%s | "
            "Platform=%s | "
            "Products=%s"
        ),
        store.name,
        platform,
        len(
            products
        ),
    )

    # =====================================================
    # PROCESS PRODUCTS
    # =====================================================

    for item in products:

        try:

            product_result = (
                await process_normalized_product(
                    store=store,
                    item=item,
                )
            )

        except Exception:

            logger.exception(
                (
                    "UNIVERSAL PRODUCT ERROR | "
                    "Store=%s"
                ),
                store.name,
            )

            continue

        if product_result.get(
            "created"
        ):

            result[
                "created"
            ] += 1

        if product_result.get(
            "updated"
        ):

            result[
                "updated"
            ] += 1

        result[
            "events"
        ] += int(
            product_result.get(
                "events",
                0,
            )
            or 0
        )

    result[
        "success"
    ] = True

    return result


# =========================================================
# LOAD UNIVERSAL STORES
# =========================================================

async def get_active_universal_stores() -> list[Store]:

    async with SessionLocal() as session:

        statement = (
            select(
                Store
            )
            .where(
                Store.active.is_(
                    True
                )
            )
            .order_by(
                Store.id.asc()
            )
            .limit(
                MAX_STORES_PER_CYCLE
            )
        )

        result = await session.execute(
            statement
        )

        stores = list(
            result.scalars().all()
        )

    universal_stores = []

    for store in stores:

        platform = normalize_platform(
            store.platform
        )

        # Shopify is deliberately isolated.

        if platform == "shopify":
            continue

        # Pokémon Center already has its own monitor.

        if platform == "pokemon_center":
            continue

        # Existing specialized major-retailer monitoring
        # should not accidentally be pulled into this monitor.

        if platform == "major_retailer":
            continue

        if (
            platform
            in SUPPORTED_UNIVERSAL_PLATFORMS
        ):

            universal_stores.append(
                store
            )

    return universal_stores


# =========================================================
# SCAN ALL STORES
# =========================================================

async def scan_all_universal_stores() -> dict[str, Any]:

    started_at = utcnow()

    MONITOR_STATUS[
        "last_scan_started_at"
    ] = started_at.isoformat()

    MONITOR_STATUS[
        "last_error"
    ] = None

    # Per-cycle counters.

    MONITOR_STATUS[
        "stores_scanned"
    ] = 0

    MONITOR_STATUS[
        "stores_failed"
    ] = 0

    MONITOR_STATUS[
        "products_seen"
    ] = 0

    MONITOR_STATUS[
        "products_created"
    ] = 0

    MONITOR_STATUS[
        "products_updated"
    ] = 0

    MONITOR_STATUS[
        "events_created"
    ] = 0

    MONITOR_STATUS[
        "price_changes"
    ] = 0

    MONITOR_STATUS[
        "restocks"
    ] = 0

    MONITOR_STATUS[
        "sold_out"
    ] = 0

    summary = {
        "success": True,
        "stores": [],
        "started_at": (
            started_at.isoformat()
        ),
        "completed_at": None,
    }

    try:

        stores = (
            await get_active_universal_stores()
        )

        logger.info(
            (
                "UNIVERSAL SCAN START | "
                "Stores=%s"
            ),
            len(
                stores
            ),
        )

        for store in stores:

            MONITOR_STATUS[
                "stores_scanned"
            ] += 1

            try:

                store_result = (
                    await scan_store(
                        store
                    )
                )

                summary[
                    "stores"
                ].append(
                    store_result
                )

                if not store_result.get(
                    "success"
                ):

                    MONITOR_STATUS[
                        "stores_failed"
                    ] += 1

            except Exception as error:

                MONITOR_STATUS[
                    "stores_failed"
                ] += 1

                logger.exception(
                    (
                        "UNIVERSAL STORE FATAL ERROR | "
                        "Store=%s"
                    ),
                    store.name,
                )

                summary[
                    "stores"
                ].append(
                    {
                        "store_id":
                            store.id,

                        "store_name":
                            store.name,

                        "success":
                            False,

                        "error":
                            (
                                f"{type(error).__name__}:"
                                f"{error}"
                            ),
                    }
                )

        completed_at = utcnow()

        MONITOR_STATUS[
            "last_scan_completed_at"
        ] = completed_at.isoformat()

        summary[
            "completed_at"
        ] = completed_at.isoformat()

        logger.info(
            (
                "UNIVERSAL SCAN COMPLETE | "
                "Stores=%s | "
                "Failed=%s | "
                "Products=%s | "
                "Created=%s | "
                "Updated=%s | "
                "Events=%s"
            ),
            MONITOR_STATUS[
                "stores_scanned"
            ],
            MONITOR_STATUS[
                "stores_failed"
            ],
            MONITOR_STATUS[
                "products_seen"
            ],
            MONITOR_STATUS[
                "products_created"
            ],
            MONITOR_STATUS[
                "products_updated"
            ],
            MONITOR_STATUS[
                "events_created"
            ],
        )

        return summary

    except Exception as error:

        MONITOR_STATUS[
            "last_error"
        ] = (
            f"{type(error).__name__}: "
            f"{error}"
        )

        summary[
            "success"
        ] = False

        logger.exception(
            "UNIVERSAL SCAN FATAL ERROR"
        )

        return summary


# =========================================================
# CONTINUOUS MONITOR
# =========================================================

async def run_universal_retailer_monitor(
    scan_interval: int = DEFAULT_SCAN_INTERVAL,
) -> None:

    scan_interval = max(
        int(
            scan_interval
        ),
        30,
    )

    if MONITOR_STATUS[
        "running"
    ]:

        logger.warning(
            "Universal retailer monitor is already running."
        )

        return

    MONITOR_STATUS[
        "running"
    ] = True

    logger.info(
        (
            "UNIVERSAL RETAILER MONITOR STARTED | "
            "Version=%s | "
            "Interval=%ss"
        ),
        VERSION,
        scan_interval,
    )

    try:

        while True:

            try:

                await scan_all_universal_stores()

            except asyncio.CancelledError:
                raise

            except Exception as error:

                MONITOR_STATUS[
                    "last_error"
                ] = (
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                logger.exception(
                    "UNIVERSAL MONITOR LOOP ERROR"
                )

            await asyncio.sleep(
                scan_interval
            )

    except asyncio.CancelledError:

        logger.info(
            "Universal retailer monitor stopped."
        )

        raise

    finally:

        MONITOR_STATUS[
            "running"
        ] = False


# =========================================================
# STATUS
# =========================================================

def get_universal_retailer_monitor_status() -> dict[str, Any]:

    return dict(
        MONITOR_STATUS
    )


# =========================================================
# MANUAL ONE-SHOT TEST
# =========================================================

async def run_once() -> dict[str, Any]:

    """
    Useful for a controlled one-cycle scan.

    This does not create a permanent background loop.
    """

    return await scan_all_universal_stores()


# =========================================================
# DIRECT EXECUTION
# =========================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
    )

    asyncio.run(
        run_once()
    )