"""
Lotus Tracker Bot
PonDeX Trackers

Retailer Adapter Loader
Version: 1.0.4
Step 6J-1A — WooCommerce Universal Adapter Registration
"""

from __future__ import annotations

import logging


VERSION = "1.0.4"

logger = logging.getLogger(
    "lotus.retailers"
)

_ADAPTERS_LOADED = False


def load_retailer_adapters() -> None:
    """
    Import all universal retailer adapters.

    Adapter modules register themselves with
    retailer_registry through their decorators.

    This function is intentionally explicit so Lotus does
    not depend on accidental Python import side effects.
    """

    global _ADAPTERS_LOADED

    if _ADAPTERS_LOADED:
        return

    # -----------------------------------------------------
    # Square / Weebly
    # -----------------------------------------------------

    from app.retailers import square_weebly_adapter
    _ = square_weebly_adapter

    # -----------------------------------------------------
    # WooCommerce
    # -----------------------------------------------------

    from app.retailers import woocommerce_adapter
    _ = woocommerce_adapter

    from app.retailers import bigcommerce_adapter
    _ = bigcommerce_adapter

    _ADAPTERS_LOADED = True

    logger.info(
        (
            "RETAILER ADAPTERS LOADED | "
            "Version=%s | "
            "Platforms=square_weebly,woocommerce,bigcommerce"
        ),
        VERSION,
    )


def retailer_adapters_loaded() -> bool:
    return _ADAPTERS_LOADED
