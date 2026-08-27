from app.retailer_adapter import (
    RetailerAdapter,
)


# =========================================================
# LOTUS RETAILER REGISTRY
# PonDeX Trackers
# Version 1.0.4
#
# Chooses the proper adapter for a retailer platform.
# =========================================================


RETAILER_ADAPTERS = {}


# =========================================================
# NORMALIZE PLATFORM
# =========================================================

def normalize_platform(
    platform,
):

    if platform is None:

        return (
            "custom"
        )

    platform = (
        str(
            platform
        )
        .strip()
        .lower()
    )

    aliases = {

        "wc":
            "woocommerce",

        "woo":
            "woocommerce",

        "woocommerce":
            "woocommerce",

        "big commerce":
            "bigcommerce",

        "big-commerce":
            "bigcommerce",

        "bigcommerce":
            "bigcommerce",

        "custom":
            "custom",

        "shopify":
            "shopify",

        "pokemon center":
            "pokemon_center",

        "pokemon-center":
            "pokemon_center",

        "pokemon_center":
            "pokemon_center",

        "major retailer":
            "major_retailer",

        "major-retailer":
            "major_retailer",

        "major_retailer":
            "major_retailer",
    }

    return (
        aliases.get(
            platform,
            platform,
        )
    )


# =========================================================
# REGISTER ADAPTER
# =========================================================

def register_retailer_adapter(
    platform,
    adapter_class,
):

    platform = (
        normalize_platform(
            platform
        )
    )

    if not isinstance(
        adapter_class,
        type,
    ):

        raise TypeError(
            "adapter_class must be a class."
        )

    if not issubclass(
        adapter_class,
        RetailerAdapter,
    ):

        raise TypeError(
            (
                f"{adapter_class.__name__} "
                "must inherit RetailerAdapter."
            )
        )

    RETAILER_ADAPTERS[
        platform
    ] = (
        adapter_class
    )

    return (
        adapter_class
    )


# =========================================================
# DECORATOR
# =========================================================

def retailer_adapter(
    platform,
):

    def decorator(
        adapter_class,
    ):

        return (
            register_retailer_adapter(
                platform,
                adapter_class,
            )
        )

    return (
        decorator
    )


# =========================================================
# GET REGISTERED ADAPTER CLASS
# =========================================================

def get_retailer_adapter_class(
    platform,
):

    platform = (
        normalize_platform(
            platform
        )
    )

    return (
        RETAILER_ADAPTERS.get(
            platform
        )
    )


# =========================================================
# BUILD ADAPTER
# =========================================================

def build_retailer_adapter(
    store,
):

    if store is None:

        raise ValueError(
            "Store is required."
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

    # Shopify continues to use the existing dedicated
    # ShopifyAdapter + Shopify monitor.
    #
    # We deliberately do NOT route Shopify through this
    # generic registry yet.

    if platform == "shopify":

        raise ValueError(
            (
                "Shopify stores use ShopifyAdapter "
                "and are not handled by the universal "
                "retailer registry."
            )
        )

    adapter_class = (
        get_retailer_adapter_class(
            platform
        )
    )

    if adapter_class is None:

        raise ValueError(
            (
                "No retailer adapter registered for "
                f"platform '{platform}'."
            )
        )

    domain = (
        getattr(
            store,
            "domain",
            None,
        )
    )

    if not domain:

        raise ValueError(
            "Store has no domain."
        )

    return adapter_class(

        domain=(
            domain
        ),

        region=(
            getattr(
                store,
                "region",
                None,
            )
            or "US"
        ),

        store_name=(
            getattr(
                store,
                "name",
                None,
            )
        ),
    )


# =========================================================
# REGISTRY STATUS
# =========================================================

def get_registered_retailer_platforms():

    return sorted(
        RETAILER_ADAPTERS.keys()
    )