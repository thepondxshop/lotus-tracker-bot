from app.retailer_adapter import RetailerAdapter


# =========================================================
# LOTUS RETAILER REGISTRY
# PonDeX Trackers
# Version 1.0.4
# Step 6J-3A — PrestaShop Universal Platform Registration
# =========================================================

RETAILER_ADAPTERS = {}


def normalize_platform(platform):
    if platform is None:
        return "custom"

    platform = str(platform).strip().lower()

    aliases = {
        # WooCommerce
        "wc": "woocommerce",
        "woo": "woocommerce",
        "woo commerce": "woocommerce",
        "woo-commerce": "woocommerce",
        "woocommerce": "woocommerce",

        # BigCommerce
        "big commerce": "bigcommerce",
        "big-commerce": "bigcommerce",
        "bigcommerce": "bigcommerce",

        # PrestaShop
        "presta": "prestashop",
        "presta shop": "prestashop",
        "presta-shop": "prestashop",
        "presta_shop": "prestashop",
        "prestashop": "prestashop",

        # Square / Weebly
        "square": "square_weebly",
        "square online": "square_weebly",
        "square-online": "square_weebly",
        "square_online": "square_weebly",
        "square weebly": "square_weebly",
        "square-weebly": "square_weebly",
        "square_weebly": "square_weebly",
        "weebly": "square_weebly",

        # Custom
        "custom": "custom",

        # Dedicated monitors
        "shopify": "shopify",
        "pokemon center": "pokemon_center",
        "pokemon-center": "pokemon_center",
        "pokemon_center": "pokemon_center",
        "major retailer": "major_retailer",
        "major-retailer": "major_retailer",
        "major_retailer": "major_retailer",
    }
    return aliases.get(platform, platform)


def register_retailer_adapter(platform, adapter_class):
    platform = normalize_platform(platform)
    if not isinstance(adapter_class, type):
        raise TypeError("adapter_class must be a class.")
    if not issubclass(adapter_class, RetailerAdapter):
        raise TypeError(f"{adapter_class.__name__} must inherit RetailerAdapter.")
    RETAILER_ADAPTERS[platform] = adapter_class
    return adapter_class


def retailer_adapter(platform):
    def decorator(adapter_class):
        return register_retailer_adapter(platform, adapter_class)
    return decorator


def get_retailer_adapter_class(platform):
    return RETAILER_ADAPTERS.get(normalize_platform(platform))


def build_retailer_adapter(store):
    if store is None:
        raise ValueError("Store is required.")

    platform = normalize_platform(getattr(store, "platform", None))

    if platform == "shopify":
        raise ValueError("Shopify stores use ShopifyAdapter and are not handled by the universal retailer registry.")
    if platform == "pokemon_center":
        raise ValueError("Pokémon Center uses its dedicated monitor and is not handled by the universal retailer registry.")
    if platform == "major_retailer":
        raise ValueError("Major retailers currently use their dedicated monitoring path.")

    adapter_class = get_retailer_adapter_class(platform)
    if adapter_class is None:
        raise ValueError(f"No retailer adapter registered for platform '{platform}'.")

    domain = getattr(store, "domain", None)
    if not domain:
        raise ValueError("Store has no domain.")

    return adapter_class(
        domain=domain,
        region=getattr(store, "region", None) or "US",
        store_name=getattr(store, "name", None),
    )


def get_registered_retailer_platforms():
    return sorted(RETAILER_ADAPTERS.keys())
