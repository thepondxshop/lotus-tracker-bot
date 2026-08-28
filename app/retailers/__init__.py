"""
Lotus Tracker Bot
PonDeX Trackers

Retailer Adapter Loader
Version: 1.0.4
"""

from __future__ import annotations

import logging


# =========================================================
# VERSION
# =========================================================

VERSION = "1.0.4"


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(
    "lotus.retailers"
)


# =========================================================
# ADAPTER LOADING STATE
# =========================================================

_ADAPTERS_LOADED = False


# =========================================================
# LOAD RETAILER ADAPTERS
# =========================================================

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

    # Keep reference so static analysis does not consider
    # the import unused.
    _ = square_weebly_adapter

    _ADAPTERS_LOADED = True

    logger.info(
        (
            "RETAILER ADAPTERS LOADED | "
            "Version=%s"
        ),
        VERSION,
    )


# =========================================================
# STATUS
# =========================================================

def retailer_adapters_loaded() -> bool:

    return _ADAPTERS_LOADED