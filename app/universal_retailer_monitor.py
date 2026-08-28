"""
Lotus Tracker Bot
PonDeX Trackers

Universal Retailer Monitor
Version: 1.0.4

Universal Retailer Foundation

Current supported adapter:
- Square / Weebly

Safety:
- Shopify remains isolated in shopify_monitor.py
- Database commits before events are published
- First successful retailer scan establishes silent baseline
- Manual scans may explicitly suppress events
- Unknown availability never becomes SOLD_OUT
- Unknown availability never becomes RESTOCK
- Missing price never erases last known price
- No duplicate DISCOVERED + STOCK_AVAILABLE alert
- No automatic checkout
- No CAPTCHA / queue / anti-bot bypass
"""

from __future__ import annotations

import asyncio
import json
import logging

from datetime import datetime
from typing import Any

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

from app.retailer_registry import (
    build_retailer_adapter,
    get_registered_retailer_platforms,
    normalize_platform,
)

from app.retailers import (
    load_retailer_adapters,
)


# =========================================================
# VERSION
# =========================================================

VERSION = (
    "1.0.4"
)


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


# =========================================================
# CURRENT LIVE UNIVERSAL PLATFORMS
#
# Do NOT list future platforms here until their adapter
# actually exists and has been tested.
# =========================================================

SUPPORTED_UNIVERSAL_PLATFORMS = {

    "square_weebly",
}


# =========================================================
# MONITOR STATUS
# =========================================================

MONITOR_STATUS: dict[str, Any] = {

    "version":
        VERSION,

    "running":
        False,

    "adapters_loaded":
        False,

    "last_scan_started_at":
        None,

    "last_scan_completed_at":
        None,

    "last_error":
        None,

    "stores_scanned":
        0,

    "stores_failed":
        0,

    "stores_baselined":
        0,

    "products_seen":
        0,

    "products_created":
        0,

    "products_updated":
        0,

    "events_created":
        0,

    "events_suppressed_baseline":
        0,

    "events_suppressed_manual":
        0,

    "price_changes":
        0,

    "restocks":
        0,

    "sold_out":
        0,

    "unknown_availability":
        0,

    "missing_prices":
        0,
}


# =========================================================
# TIME
# =========================================================

def utcnow() -> datetime:

    return (
        datetime.utcnow()
    )


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_text(
    value: Any,
    default: str = "",
) -> str:

    if value is None:

        return (
            default
        )

    value = (
        str(
            value
        ).strip()
    )

    return (
        value
        or default
    )


def normalize_optional_text(
    value: Any,
) -> str | None:

    if value is None:

        return None

    value = (
        str(
            value
        ).strip()
    )

    if not value:

        return None

    return (
        value
    )


def normalize_price(
    value: Any,
) -> float | None:

    if value is None:

        return None

    try:

        return (
            float(
                value
            )
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

        return (
            value
        )

    if value is None:

        return False


    if isinstance(
        value,
        str,
    ):

        lowered = (
            value
            .strip()
            .lower()
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


    return (
        bool(
            value
        )
    )


def normalize_currency(
    value: Any,
) -> str:

    return (
        normalize_text(
            value,
            "USD",
        ).upper()
    )


def normalize_region(
    value: Any,
) -> str:

    return (
        normalize_text(
            value,
            "US",
        ).upper()
    )


def normalize_product_category(
    value: Any,
) -> str:

    value = (
        normalize_text(
            value,
            "UNKNOWN",
        ).upper()
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


def normalize_product_family(
    value: Any,
) -> str:

    value = (
        normalize_text(
            value,
            "UNKNOWN",
        )
        .upper()
        .replace(
            "-",
            "_",
        )
        .replace(
            " ",
            "_",
        )
    )


    aliases = {

        "GLOBAL":
            "GLOBAL_STANDARD",

        "STANDARD":
            "GLOBAL_STANDARD",

        "ENGLISH":
            "GLOBAL_STANDARD",

        "JAPAN":
            "JP",

        "JAPANESE":
            "JP",

        "KOREA":
            "KR",

        "KOREAN":
            "KR",

        "CHINA":
            "CN",

        "CHINESE":
            "CN",

        "SIMPLIFIED_CHINESE":
            "CN",
    }


    value = (
        aliases.get(
            value,
            value,
        )
    )


    if value not in {

        "GLOBAL_STANDARD",
        "JP",
        "KR",
        "CN",
        "UNKNOWN",

    }:

        return (
            "UNKNOWN"
        )


    return (
        value
    )


# =========================================================
# FAMILY LANGUAGE
# =========================================================

def family_language(
    product_family: str,
) -> str:

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


# =========================================================
# PLATFORM DATA
# =========================================================

def serialize_platform_data(
    value: Any,
) -> str | None:

    if value is None:

        return None


    if isinstance(
        value,
        str,
    ):

        value = (
            value.strip()
        )

        return (
            value
            if value
            else None
        )


    try:

        return (
            json.dumps(

                value,

                separators=(
                    ",",
                    ":",
                ),

                sort_keys=True,

                default=str,
            )
        )

    except Exception:

        try:

            return (
                str(
                    value
                )
            )

        except Exception:

            return None


def deserialize_platform_data(
    value: Any,
) -> dict[str, Any]:

    if isinstance(
        value,
        dict,
    ):

        return (
            dict(
                value
            )
        )


    if not value:

        return {}


    if isinstance(
        value,
        str,
    ):

        try:

            parsed = (
                json.loads(
                    value
                )
            )

            if isinstance(
                parsed,
                dict,
            ):

                return (
                    parsed
                )

        except Exception:

            pass


    return {}


# =========================================================
# AVAILABILITY
# =========================================================

def get_availability_info(
    item: dict[str, Any],
) -> tuple[
    bool,
    bool,
    str,
]:

    platform_data = (
        deserialize_platform_data(
            item.get(
                "platform_data"
            )
        )
    )


    availability_known = (
        platform_data.get(
            "availability_known"
        )
    )


    availability_state = (
        normalize_text(
            platform_data.get(
                "availability_state"
            ),
            "",
        ).upper()
    )


    # =====================================================
    # EXPLICIT STATE
    # =====================================================

    if availability_state == "IN_STOCK":

        return (
            True,
            True,
            "IN_STOCK",
        )


    if availability_state == "OUT_OF_STOCK":

        return (
            False,
            True,
            "OUT_OF_STOCK",
        )


    if availability_state == "UNKNOWN":

        return (
            False,
            False,
            "UNKNOWN",
        )


    # =====================================================
    # EXPLICIT KNOWN FLAG
    # =====================================================

    if availability_known is True:

        available = (
            normalize_bool(
                item.get(
                    "available"
                )
            )
        )

        return (

            available,

            True,

            (
                "IN_STOCK"
                if available
                else "OUT_OF_STOCK"
            ),
        )


    if availability_known is False:

        return (
            False,
            False,
            "UNKNOWN",
        )


    # =====================================================
    # LEGACY ADAPTER FALLBACK
    #
    # For adapters without tri-state support, available is
    # treated as known. Our Square/Weebly adapter DOES use
    # tri-state metadata.
    # =====================================================

    available = (
        normalize_bool(
            item.get(
                "available"
            )
        )
    )


    return (

        available,

        True,

        (
            "IN_STOCK"
            if available
            else "OUT_OF_STOCK"
        ),
    )


# =========================================================
# LOAD ADAPTERS
# =========================================================

def ensure_retailer_adapters_loaded() -> None:

    load_retailer_adapters()


    MONITOR_STATUS[
        "adapters_loaded"
    ] = True


# =========================================================
# EVENT
# =========================================================

def make_product_event(
    *,
    event_type: str | ProductEventType,
    item: dict[str, Any],
    store: Store,
    in_stock: bool,
    old_price: float | None = None,
    effective_price: float | None = None,
) -> ProductEvent:

    product_family = (
        normalize_product_family(
            item.get(
                "product_family"
            )
        )
    )


    product_category = (
        normalize_product_category(
            item.get(
                "product_category"
            )
        )
    )


    platform = (
        normalize_platform(
            getattr(
                store,
                "platform",
                None,
            )
        )
    )


    if isinstance(
        event_type,
        ProductEventType,
    ):

        normalized_event_type = (
            event_type
        )

    else:

        normalized_event_type = (
            ProductEventType(
                str(
                    event_type
                )
            )
        )


    event_price = (

        normalize_price(
            effective_price
        )

        if effective_price is not None

        else normalize_price(
            item.get(
                "price"
            )
        )
    )


    return ProductEvent(

        event_type=(
            normalized_event_type
        ),

        game=(
            normalize_text(
                item.get(
                    "game"
                ),
                "Unknown",
            )
        ),

        product_name=(
            normalize_text(
                item.get(
                    "title"
                ),
                "Unknown Product",
            )
        ),

        store_name=(
            normalize_text(
                getattr(
                    store,
                    "name",
                    None,
                ),
                "Unknown Store",
            )
        ),

        product_url=(
            normalize_text(
                item.get(
                    "url"
                )
            )
        ),

        price=(
            event_price
        ),

        old_price=(
            normalize_price(
                old_price
            )
        ),

        currency=(
            normalize_currency(
                item.get(
                    "currency"
                )
            )
        ),

        in_stock=(
            bool(
                in_stock
            )
        ),

        region=(
            normalize_region(
                getattr(
                    store,
                    "region",
                    None,
                )
            )
        ),

        language=(
            family_language(
                product_family
            )
        ),

        product_type=(
            normalize_text(
                item.get(
                    "product_type"
                ),
                "TCG Product",
            )
        ),

        product_category=(
            product_category
        ),

        product_family=(
            product_family
        ),

        source_type=(
            platform
        ),

        retailer_key=(
            normalize_text(
                getattr(
                    store,
                    "domain",
                    None,
                )
            )
        ),

        image_url=(
            normalize_optional_text(
                item.get(
                    "image_url"
                )
            )
        ),

        variant_id=(
            normalize_optional_text(
                item.get(
                    "variant_id"
                )
            )
        ),

        purchase_limit=(
            item.get(
                "purchase_limit"
            )
        ),

        cart_base_url=(
            normalize_optional_text(
                item.get(
                    "cart_base_url"
                )
            )
        ),
    )


# =========================================================
# STORE BASELINE
# =========================================================

async def store_has_baseline(
    store_id: int,
) -> bool:

    async with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    StoreProduct.id
                )
            )
            .where(
                StoreProduct.store_id
                ==
                store_id
            )
        )


        result = (
            await session.execute(
                statement
            )
        )


        count = (
            result.scalar_one()
            or 0
        )


        return (
            count > 0
        )


# =========================================================
# PRODUCT LOOKUP
# =========================================================

async def find_product(
    session,
    *,
    game: str,
    title: str,
    product_family: str,
) -> Product | None:

    statement = (
        select(
            Product
        )
        .where(

            Product.game
            ==
            game,

            Product.name
            ==
            title,

            Product.product_family
            ==
            product_family,
        )
        .limit(
            1
        )
    )


    result = (
        await session.execute(
            statement
        )
    )


    return (
        result.scalar_one_or_none()
    )


# =========================================================
# STORE PRODUCT LOOKUP
# =========================================================

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

            StoreProduct.store_id
            ==
            store_id,

            StoreProduct.url
            ==
            url,
        )
        .limit(
            1
        )
    )


    result = (
        await session.execute(
            statement
        )
    )


    return (
        result.scalar_one_or_none()
    )


# =========================================================
# PRODUCT
# =========================================================

async def get_or_create_product(
    session,
    *,
    item: dict[str, Any],
    store: Store,
) -> tuple[
    Product,
    bool,
]:

    game = (
        normalize_text(
            item.get(
                "game"
            )
        )
    )


    title = (
        normalize_text(
            item.get(
                "title"
            )
        )
    )


    product_family = (
        normalize_product_family(
            item.get(
                "product_family"
            )
        )
    )


    product_category = (
        normalize_product_category(
            item.get(
                "product_category"
            )
        )
    )


    product_type = (
        normalize_text(
            item.get(
                "product_type"
            ),
            "TCG Product",
        )
    )


    region = (
        normalize_region(
            getattr(
                store,
                "region",
                None,
            )
        )
    )


    language = (
        family_language(
            product_family
        )
    )


    existing = (
        await find_product(

            session,

            game=game,

            title=title,

            product_family=product_family,
        )
    )


    if existing is not None:

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

        product_category=(
            product_category
        ),

        product_family=(
            product_family
        ),

        region=region,

        language=language,
    )


    session.add(
        product
    )


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


    session.add(
        PriceHistory(

            store_product_id=(
                store_product.id
            ),

            price=price,

            currency=currency,

            recorded_at=(
                utcnow()
            ),
        )
    )


# =========================================================
# CREATE STORE PRODUCT
# =========================================================

async def create_store_product(
    session,
    *,
    store: Store,
    product: Product,
    item: dict[str, Any],
    suppress_events: bool,
) -> tuple[
    StoreProduct,
    list[ProductEvent],
    int,
]:

    url = (
        normalize_text(
            item.get(
                "url"
            )
        )
    )


    price = (
        normalize_price(
            item.get(
                "price"
            )
        )
    )


    currency = (
        normalize_currency(
            item.get(
                "currency"
            )
        )
    )


    (
        available,
        availability_known,
        availability_state,
    ) = (
        get_availability_info(
            item
        )
    )


    if not availability_known:

        MONITOR_STATUS[
            "unknown_availability"
        ] += 1


    if price is None:

        MONITOR_STATUS[
            "missing_prices"
        ] += 1


    external_product_id = (
        normalize_optional_text(
            item.get(
                "external_product_id"
            )
            or
            item.get(
                "external_id"
            )
        )
    )


    offer_id = (
        normalize_optional_text(
            item.get(
                "offer_id"
            )
        )
    )


    sku = (
        normalize_optional_text(
            item.get(
                "sku"
            )
        )
    )


    variant_id = (
        normalize_optional_text(
            item.get(
                "variant_id"
            )
        )
    )


    platform_data = (
        serialize_platform_data(
            item.get(
                "platform_data"
            )
        )
    )


    if availability_state == "IN_STOCK":

        product_state = (
            "STOCK_AVAILABLE"
        )

    elif availability_state == "OUT_OF_STOCK":

        product_state = (
            "SOLD_OUT"
        )

    else:

        product_state = (
            "PAGE_LIVE"
        )


    explicit_product_state = (
        normalize_optional_text(
            item.get(
                "product_state"
            )
        )
    )


    if explicit_product_state:

        product_state = (
            explicit_product_state
        )


    store_product = StoreProduct(

        store_id=(
            store.id
        ),

        product_id=(
            product.id
        ),

        url=url,

        sku=sku,

        variant_id=(
            variant_id
        ),

        external_product_id=(
            external_product_id
        ),

        offer_id=(
            offer_id
        ),

        platform_data=(
            platform_data
        ),

        purchase_limit=(
            item.get(
                "purchase_limit"
            )
        ),

        status=(
            product_state
        ),

        price=price,

        currency=currency,

        # For a brand-new product with unknown stock, False
        # is only the storage default. platform_data retains
        # UNKNOWN so future scans do not interpret this as
        # a confirmed out-of-stock observation.

        in_stock=(
            available
            if availability_known
            else False
        ),

        last_seen_at=(
            utcnow()
        ),
    )


    session.add(
        store_product
    )


    await session.flush()


    add_price_history(

        session,

        store_product=(
            store_product
        ),

        price=price,

        currency=currency,
    )


    events: list[
        ProductEvent
    ] = []


    # =====================================================
    # SILENT MODE
    # =====================================================

    if suppress_events:

        suppressed = 1


        MONITOR_STATUS[
            "events_suppressed_baseline"
        ] += 1


        return (
            store_product,
            events,
            suppressed,
        )


    # =====================================================
    # LIVE NEW PRODUCT
    #
    # ONE event only.
    #
    # In stock:
    # STOCK_AVAILABLE
    #
    # Not in stock / unknown:
    # DISCOVERED
    # =====================================================

    if (
        availability_known
        and
        available
    ):

        event_type = (
            ProductEventType.STOCK_AVAILABLE
        )

    else:

        event_type = (
            ProductEventType.DISCOVERED
        )


    events.append(
        make_product_event(

            event_type=event_type,

            item=item,

            store=store,

            in_stock=(
                available
                if availability_known
                else False
            ),

            effective_price=price,
        )
    )


    return (
        store_product,
        events,
        0,
    )


# =========================================================
# UPDATE STORE PRODUCT
# =========================================================

async def update_store_product(
    session,
    *,
    store: Store,
    store_product: StoreProduct,
    item: dict[str, Any],
    suppress_events: bool,
) -> tuple[
    list[ProductEvent],
    int,
]:

    events: list[
        ProductEvent
    ] = []


    suppressed = 0


    old_stock = (
        bool(
            store_product.in_stock
        )
    )


    old_price = (
        normalize_price(
            store_product.price
        )
    )


    old_currency = (
        normalize_currency(
            store_product.currency
        )
    )


    (
        parsed_stock,
        availability_known,
        availability_state,
    ) = (
        get_availability_info(
            item
        )
    )


    if availability_known:

        new_stock = (
            parsed_stock
        )

    else:

        # =================================================
        # CRITICAL:
        # Unknown scrape result preserves last known state.
        # =================================================

        new_stock = (
            old_stock
        )


        MONITOR_STATUS[
            "unknown_availability"
        ] += 1


    parsed_price = (
        normalize_price(
            item.get(
                "price"
            )
        )
    )


    if parsed_price is None:

        # =================================================
        # CRITICAL:
        # Missing scrape price preserves last known price.
        # =================================================

        new_price = (
            old_price
        )


        MONITOR_STATUS[
            "missing_prices"
        ] += 1

    else:

        new_price = (
            parsed_price
        )


    new_currency = (
        normalize_currency(
            item.get(
                "currency"
            )
            or old_currency
        )
    )


    # =====================================================
    # IDENTIFIERS
    # =====================================================

    new_external_product_id = (
        normalize_optional_text(
            item.get(
                "external_product_id"
            )
            or
            item.get(
                "external_id"
            )
        )
    )


    new_offer_id = (
        normalize_optional_text(
            item.get(
                "offer_id"
            )
        )
    )


    new_sku = (
        normalize_optional_text(
            item.get(
                "sku"
            )
        )
    )


    new_variant_id = (
        normalize_optional_text(
            item.get(
                "variant_id"
            )
        )
    )


    new_platform_data = (
        serialize_platform_data(
            item.get(
                "platform_data"
            )
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
    #
    # Only explicit availability can create stock events.
    # =====================================================

    if availability_known:

        if (
            not old_stock
            and
            new_stock
        ):

            if suppress_events:

                suppressed += 1

            else:

                events.append(
                    make_product_event(

                        event_type=(
                            ProductEventType.RESTOCK
                        ),

                        item=item,

                        store=store,

                        in_stock=True,

                        old_price=(
                            old_price
                        ),

                        effective_price=(
                            new_price
                        ),
                    )
                )


                MONITOR_STATUS[
                    "restocks"
                ] += 1


        elif (
            old_stock
            and
            not new_stock
        ):

            if suppress_events:

                suppressed += 1

            else:

                events.append(
                    make_product_event(

                        event_type=(
                            ProductEventType.SOLD_OUT
                        ),

                        item=item,

                        store=store,

                        in_stock=False,

                        old_price=(
                            old_price
                        ),

                        effective_price=(
                            new_price
                        ),
                    )
                )


                MONITOR_STATUS[
                    "sold_out"
                ] += 1


    # =====================================================
    # PRICE TRANSITIONS
    #
    # A missing price never creates an event.
    # =====================================================

    price_changed = False


    if (
        old_price is not None

        and
        parsed_price is not None

        and
        old_currency == new_currency

        and
        old_price != parsed_price
    ):

        price_changed = True


        if suppress_events:

            suppressed += 1


        elif parsed_price < old_price:

            events.append(
                make_product_event(

                    event_type=(
                        ProductEventType.PRICE_DROP
                    ),

                    item=item,

                    store=store,

                    in_stock=(
                        new_stock
                    ),

                    old_price=(
                        old_price
                    ),

                    effective_price=(
                        parsed_price
                    ),
                )
            )


            MONITOR_STATUS[
                "price_changes"
            ] += 1


        else:

            events.append(
                make_product_event(

                    event_type=(
                        ProductEventType.PRICE_INCREASE
                    ),

                    item=item,

                    store=store,

                    in_stock=(
                        new_stock
                    ),

                    old_price=(
                        old_price
                    ),

                    effective_price=(
                        parsed_price
                    ),
                )
            )


            MONITOR_STATUS[
                "price_changes"
            ] += 1


    # =====================================================
    # PRICE HISTORY
    # =====================================================

    if (
        parsed_price is not None

        and
        (
            old_price is None

            or
            price_changed

            or
            old_currency != new_currency
        )
    ):

        add_price_history(

            session,

            store_product=(
                store_product
            ),

            price=(
                parsed_price
            ),

            currency=(
                new_currency
            ),
        )


    # =====================================================
    # CURRENT STATE
    # =====================================================

    # Only update price when scrape supplied one.

    if parsed_price is not None:

        store_product.price = (
            parsed_price
        )


    # Currency remains known even when price temporarily
    # disappears.

    store_product.currency = (
        new_currency
    )


    # Only update stock when scrape supplied an explicit
    # stock state.

    if availability_known:

        store_product.in_stock = (
            new_stock
        )


    # =====================================================
    # STATUS
    # =====================================================

    if availability_state == "IN_STOCK":

        store_product.status = (
            "STOCK_AVAILABLE"
        )


    elif availability_state == "OUT_OF_STOCK":

        store_product.status = (
            "SOLD_OUT"
        )


    else:

        # Preserve known stock status on an uncertain scrape.
        #
        # Do not rewrite an existing STOCK_AVAILABLE /
        # SOLD_OUT state to PAGE_LIVE just because the
        # parser temporarily lost the stock indicator.

        if not store_product.status:

            store_product.status = (
                "PAGE_LIVE"
            )


    store_product.last_seen_at = (
        utcnow()
    )


    return (
        events,
        suppressed,
    )


# =========================================================
# PROCESS NORMALIZED PRODUCT
# =========================================================

async def process_normalized_product(
    *,
    store: Store,
    item: dict[str, Any],
    baseline_mode: bool = False,
    suppress_events: bool = False,
) -> dict[str, Any]:

    result = {

        "processed":
            False,

        "created":
            False,

        "updated":
            False,

        "events":
            0,

        "suppressed":
            0,

        "reason":
            None,
    }


    # =====================================================
    # VALIDATION
    # =====================================================

    if not isinstance(
        item,
        dict,
    ):

        result[
            "reason"
        ] = (
            "INVALID_ITEM"
        )

        return (
            result
        )


    game = (
        normalize_text(
            item.get(
                "game"
            )
        )
    )


    title = (
        normalize_text(
            item.get(
                "title"
            )
        )
    )


    url = (
        normalize_text(
            item.get(
                "url"
            )
        )
    )


    if not game:

        result[
            "reason"
        ] = (
            "NO_SUPPORTED_GAME"
        )

        return (
            result
        )


    if not title:

        result[
            "reason"
        ] = (
            "NO_TITLE"
        )

        return (
            result
        )


    if not url:

        result[
            "reason"
        ] = (
            "NO_URL"
        )

        return (
            result
        )


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
    ] = (
        normalize_product_family(
            item.get(
                "product_family"
            )
        )
    )


    item[
        "product_category"
    ] = (
        normalize_product_category(
            item.get(
                "product_category"
            )
        )
    )


    item[
        "currency"
    ] = (
        normalize_currency(
            item.get(
                "currency"
            )
        )
    )


    # =====================================================
    # SILENT MODE
    # =====================================================

    effective_suppress = (

        bool(
            baseline_mode
        )

        or
        bool(
            suppress_events
        )
    )


    events_to_send: list[
        ProductEvent
    ] = []


    # =====================================================
    # DATABASE
    # =====================================================

    try:

        async with SessionLocal() as session:


            store_product = (
                await find_store_product(

                    session,

                    store_id=(
                        store.id
                    ),

                    url=url,
                )
            )


            # =================================================
            # NEW
            # =================================================

            if store_product is None:

                (
                    product,
                    _product_created,
                ) = (
                    await get_or_create_product(

                        session,

                        item=item,

                        store=store,
                    )
                )


                (
                    store_product,
                    new_events,
                    suppressed_count,
                ) = (
                    await create_store_product(

                        session,

                        store=store,

                        product=product,

                        item=item,

                        suppress_events=(
                            effective_suppress
                        ),
                    )
                )


                events_to_send.extend(
                    new_events
                )


                result[
                    "created"
                ] = True


                result[
                    "suppressed"
                ] += (
                    suppressed_count
                )


                MONITOR_STATUS[
                    "products_created"
                ] += 1


                logger.info(
                    (
                        "UNIVERSAL PRODUCT DISCOVERED | "
                        "Store=%s | "
                        "Silent=%s | "
                        "Game=%s | "
                        "Family=%s | "
                        "Title=%s"
                    ),

                    store.name,

                    effective_suppress,

                    game,

                    item[
                        "product_family"
                    ],

                    title,
                )


            # =================================================
            # EXISTING
            # =================================================

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


                if product is not None:

                    product.game = (
                        game
                    )

                    product.name = (
                        title
                    )

                    product.canonical_name = (
                        product.canonical_name
                        or title
                    )

                    product.product_type = (
                        normalize_text(

                            item.get(
                                "product_type"
                            ),

                            product.product_type
                            or "TCG Product",
                        )
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

                    product.region = (
                        normalize_region(
                            store.region
                        )
                    )

                    product.language = (
                        family_language(
                            item[
                                "product_family"
                            ]
                        )
                    )


                (
                    update_events,
                    suppressed_count,
                ) = (
                    await update_store_product(

                        session,

                        store=store,

                        store_product=(
                            store_product
                        ),

                        item=item,

                        suppress_events=(
                            effective_suppress
                        ),
                    )
                )


                events_to_send.extend(
                    update_events
                )


                result[
                    "suppressed"
                ] += (
                    suppressed_count
                )


                result[
                    "updated"
                ] = True


                MONITOR_STATUS[
                    "products_updated"
                ] += 1


            # =================================================
            # COMMIT BEFORE PUBLISH
            # =================================================

            await session.commit()


    except Exception as error:

        result[
            "reason"
        ] = (
            "DATABASE_ERROR:"
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


        return (
            result
        )


    # =====================================================
    # PUBLISH
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

                event.event_type.value,

                game,

                title,
            )


        except Exception:

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
    ] = (
        published_events
    )


    return (
        result
    )


# =========================================================
# SCAN ONE STORE
#
# suppress_events=True gives us a guaranteed controlled
# silent scan even if the store already has DB rows.
# =========================================================

async def scan_store(
    store: Store,
    *,
    suppress_events: bool = False,
) -> dict[str, Any]:

    result = {

        "store_id":
            store.id,

        "store_name":
            store.name,

        "domain":
            store.domain,

        "platform":
            store.platform,

        "baseline_mode":
            False,

        "manual_suppression":
            bool(
                suppress_events
            ),

        "success":
            False,

        "products":
            0,

        "created":
            0,

        "updated":
            0,

        "events":
            0,

        "suppressed":
            0,

        "error":
            None,
    }


    platform = (
        normalize_platform(
            store.platform
        )
    )


    if platform == "shopify":

        result[
            "error"
        ] = (
            "SHOPIFY_USES_SHOPIFY_MONITOR"
        )

        return (
            result
        )


    if (
        platform
        not in
        SUPPORTED_UNIVERSAL_PLATFORMS
    ):

        result[
            "error"
        ] = (
            "UNSUPPORTED_PLATFORM:"
            f"{platform}"
        )

        return (
            result
        )


    if not store.domain:

        result[
            "error"
        ] = (
            "NO_DOMAIN"
        )

        return (
            result
        )


    # =====================================================
    # ADAPTER REGISTRATION
    # =====================================================

    ensure_retailer_adapters_loaded()


    registered = set(
        get_registered_retailer_platforms()
    )


    if platform not in registered:

        result[
            "error"
        ] = (
            "ADAPTER_NOT_REGISTERED:"
            f"{platform}"
        )

        return (
            result
        )


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
            "ADAPTER_ERROR:"
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


        return (
            result
        )


    # =====================================================
    # FETCH
    # =====================================================

    try:

        products = (
            await adapter
            .get_normalized_products()
        )


    except Exception as error:

        result[
            "error"
        ] = (
            "FETCH_ERROR:"
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


        return (
            result
        )


    products = (
        products
        or []
    )


    result[
        "products"
    ] = (
        len(
            products
        )
    )


    MONITOR_STATUS[
        "products_seen"
    ] += (
        len(
            products
        )
    )


    # =====================================================
    # EMPTY SAFETY
    # =====================================================

    if not products:

        result[
            "error"
        ] = (
            "NO_PRODUCTS_RETURNED"
        )


        logger.warning(
            (
                "UNIVERSAL EMPTY SCAN | "
                "Store=%s | "
                "Platform=%s | "
                "Baseline NOT established"
            ),

            store.name,

            platform,
        )


        return (
            result
        )


    # =====================================================
    # BASELINE
    # =====================================================

    has_baseline = (
        await store_has_baseline(
            store.id
        )
    )


    baseline_mode = (
        not has_baseline
    )


    result[
        "baseline_mode"
    ] = (
        baseline_mode
    )


    effective_suppression = (

        baseline_mode

        or
        suppress_events
    )


    if baseline_mode:

        MONITOR_STATUS[
            "stores_baselined"
        ] += 1


        logger.info(
            (
                "UNIVERSAL BASELINE START | "
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


    if (
        suppress_events
        and
        not baseline_mode
    ):

        logger.info(
            (
                "UNIVERSAL MANUAL SILENT SCAN | "
                "Store=%s | "
                "Platform=%s"
            ),

            store.name,

            platform,
        )


    # =====================================================
    # PRODUCTS
    # =====================================================

    for item in products:

        try:

            product_result = (
                await process_normalized_product(

                    store=store,

                    item=item,

                    baseline_mode=(
                        baseline_mode
                    ),

                    suppress_events=(
                        suppress_events
                    ),
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
            "suppressed"
        ] += int(

            product_result.get(
                "suppressed",
                0,
            )

            or 0
        )


    # =====================================================
    # SUPPRESSION ACCOUNTING
    # =====================================================

    if (
        suppress_events
        and
        not baseline_mode
    ):

        MONITOR_STATUS[
            "events_suppressed_manual"
        ] += (
            result[
                "suppressed"
            ]
        )


    # =====================================================
    # SUCCESS
    # =====================================================

    result[
        "success"
    ] = True


    if baseline_mode:

        logger.info(
            (
                "UNIVERSAL BASELINE COMPLETE | "
                "Store=%s | "
                "Products=%s | "
                "Created=%s | "
                "SuppressedEvents=%s"
            ),

            store.name,

            result[
                "products"
            ],

            result[
                "created"
            ],

            result[
                "suppressed"
            ],
        )


    elif effective_suppression:

        logger.info(
            (
                "UNIVERSAL SILENT SCAN COMPLETE | "
                "Store=%s | "
                "Products=%s | "
                "Created=%s | "
                "Updated=%s | "
                "SuppressedEvents=%s"
            ),

            store.name,

            result[
                "products"
            ],

            result[
                "created"
            ],

            result[
                "updated"
            ],

            result[
                "suppressed"
            ],
        )


    return (
        result
    )


# =========================================================
# ACTIVE UNIVERSAL STORES
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


        result = (
            await session.execute(
                statement
            )
        )


        stores = list(
            result.scalars().all()
        )


    universal_stores = []


    for store in stores:

        platform = (
            normalize_platform(
                store.platform
            )
        )


        if (
            platform
            in
            SUPPORTED_UNIVERSAL_PLATFORMS
        ):

            universal_stores.append(
                store
            )


    return (
        universal_stores
    )


# =========================================================
# RESET CYCLE STATUS
# =========================================================

def reset_cycle_status() -> None:

    keys = (

        "stores_scanned",
        "stores_failed",
        "stores_baselined",
        "products_seen",
        "products_created",
        "products_updated",
        "events_created",
        "events_suppressed_baseline",
        "events_suppressed_manual",
        "price_changes",
        "restocks",
        "sold_out",
        "unknown_availability",
        "missing_prices",
    )


    for key in keys:

        MONITOR_STATUS[
            key
        ] = 0


# =========================================================
# SCAN ALL
# =========================================================

async def scan_all_universal_stores(
    *,
    suppress_events: bool = False,
) -> dict[str, Any]:

    ensure_retailer_adapters_loaded()


    reset_cycle_status()


    started_at = (
        utcnow()
    )


    MONITOR_STATUS[
        "last_scan_started_at"
    ] = (
        started_at.isoformat()
    )


    MONITOR_STATUS[
        "last_error"
    ] = None


    summary = {

        "success":
            True,

        "stores":
            [],

        "started_at":
            started_at.isoformat(),

        "completed_at":
            None,

        "suppress_events":
            bool(
                suppress_events
            ),
    }


    try:

        stores = (
            await get_active_universal_stores()
        )


        logger.info(
            (
                "UNIVERSAL SCAN START | "
                "Stores=%s | "
                "Silent=%s"
            ),

            len(
                stores
            ),

            suppress_events,
        )


        for store in stores:

            MONITOR_STATUS[
                "stores_scanned"
            ] += 1


            try:

                store_result = (
                    await scan_store(

                        store,

                        suppress_events=(
                            suppress_events
                        ),
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


        completed_at = (
            utcnow()
        )


        MONITOR_STATUS[
            "last_scan_completed_at"
        ] = (
            completed_at.isoformat()
        )


        summary[
            "completed_at"
        ] = (
            completed_at.isoformat()
        )


        logger.info(
            (
                "UNIVERSAL SCAN COMPLETE | "
                "Stores=%s | "
                "Failed=%s | "
                "Baselined=%s | "
                "Products=%s | "
                "Created=%s | "
                "Updated=%s | "
                "Events=%s | "
                "Suppressed=%s | "
                "UnknownStock=%s | "
                "MissingPrice=%s"
            ),

            MONITOR_STATUS[
                "stores_scanned"
            ],

            MONITOR_STATUS[
                "stores_failed"
            ],

            MONITOR_STATUS[
                "stores_baselined"
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

            (
                MONITOR_STATUS[
                    "events_suppressed_baseline"
                ]
                +
                MONITOR_STATUS[
                    "events_suppressed_manual"
                ]
            ),

            MONITOR_STATUS[
                "unknown_availability"
            ],

            MONITOR_STATUS[
                "missing_prices"
            ],
        )


        return (
            summary
        )


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


        return (
            summary
        )


# =========================================================
# CONTINUOUS MONITOR
#
# DO NOT START THIS FROM main.py YET.
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
            (
                "Universal retailer monitor "
                "is already running."
            )
        )

        return


    ensure_retailer_adapters_loaded()


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
            (
                "Universal retailer "
                "monitor stopped."
            )
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

    return (
        dict(
            MONITOR_STATUS
        )
    )


# =========================================================
# MANUAL ONE-SHOT
# =========================================================

async def run_once(
    *,
    suppress_events: bool = True,
) -> dict[str, Any]:

    return (
        await scan_all_universal_stores(
            suppress_events=(
                suppress_events
            )
        )
    )


# =========================================================
# DIRECT EXECUTION
# =========================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
    )


    # Direct execution is intentionally silent.

    asyncio.run(
        run_once(
            suppress_events=True
        )
    )