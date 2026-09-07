"""
Lotus Tracker Bot
PonDeX Trackers

Retailer Adapter Loader
Version: 1.0.4
Step 6J-3F — Shopware 6 Universal Adapter Registration
"""

from __future__ import annotations

import logging

VERSION = "1.0.4"
logger = logging.getLogger("lotus.retailers")
_ADAPTERS_LOADED = False


def load_retailer_adapters() -> None:
    global _ADAPTERS_LOADED
    if _ADAPTERS_LOADED:
        return

    from app.retailers import square_weebly_adapter
    _ = square_weebly_adapter

    from app.retailers import woocommerce_adapter
    _ = woocommerce_adapter

    from app.retailers import bigcommerce_adapter
    _ = bigcommerce_adapter

    from app.retailers import prestashop_adapter
    _ = prestashop_adapter

    from app.retailers import shopware_adapter
    _ = shopware_adapter

    _ADAPTERS_LOADED = True
    logger.info(
        "RETAILER ADAPTERS LOADED | Version=%s | Platforms=square_weebly,woocommerce,bigcommerce,prestashop,shopware",
        VERSION,
    )


def retailer_adapters_loaded() -> bool:
    return _ADAPTERS_LOADED
