import os


# =========================================================
# LOTUS CONFIGURATION
# PonDeX Trackers
# Version 0.7.6
# =========================================================


# =========================================================
# DISCORD
# =========================================================

DISCORD_TOKEN = os.getenv(
    "DISCORD_TOKEN"
)


# =========================================================
# GAME ROLES
# =========================================================

GAME_ROLES = {

    "One Piece":
        os.getenv(
            "ROLE_ONE_PIECE"
        ),

    "Pokemon":
        os.getenv(
            "ROLE_POKEMON"
        ),

    "Gundam":
        os.getenv(
            "ROLE_GUNDAM"
        ),

    "Dragon Ball Fusion World":
        os.getenv(
            "ROLE_DRAGON_BALL"
        ),

    "Riftbound":
        os.getenv(
            "ROLE_RIFTBOUND"
        ),

    "Palworld":
        os.getenv(
            "ROLE_PALWORLD"
        ),

    "Naruto":
        os.getenv(
            "ROLE_NARUTO"
        ),

    "Cyberpunk TCG":
        os.getenv(
            "ROLE_CYBERPUNK"
        ),

    "Azuki TCG":
        os.getenv(
            "ROLE_AZUKI"
        ),

    "Hellbreak TCG":
        os.getenv(
            "ROLE_HELLBREAK"
        ),
}


# =========================================================
# SUBSCRIPTION ROLES
# =========================================================

SUBSCRIPTION_ROLES = {

    "Premium+":
        os.getenv(
            "ROLE_PREMIUM_PLUS"
        ),

    "Premium":
        os.getenv(
            "ROLE_PREMIUM"
        ),

    "Lite":
        os.getenv(
            "ROLE_LITE"
        ),

    "Free":
        os.getenv(
            "ROLE_FREE"
        ),
}


# =========================================================
# GAME DATA
# =========================================================

GAME_DATA = [

    (
        "One Piece",
        "🏴‍☠️",
        "One Piece Card Game alerts",
    ),

    (
        "Pokemon",
        "⚡",
        "Pokemon TCG alerts",
    ),

    (
        "Gundam",
        "🤖",
        "Gundam Card Game alerts",
    ),

    (
        "Dragon Ball Fusion World",
        "🐉",
        "Dragon Ball Fusion World alerts",
    ),

    (
        "Riftbound",
        "🌀",
        "Riftbound alerts",
    ),

    (
        "Palworld",
        "🟢",
        "Palworld TCG alerts",
    ),

    (
        "Naruto",
        "🍥",
        "Naruto TCG alerts",
    ),

    (
        "Cyberpunk TCG",
        "🌃",
        "Cyberpunk TCG alerts",
    ),

    (
        "Azuki TCG",
        "🔴",
        "Azuki TCG alerts",
    ),

    (
        "Hellbreak TCG",
        "🔥",
        "Hellbreak TCG alerts",
    ),
]


# =========================================================
# CHANNEL VARIABLES
# =========================================================

CHANNEL_ROLES = os.getenv(
    "CHANNEL_ROLES"
)


# =========================================================
# MAJOR RETAILER
#
# Target / Walmart / Best Buy / GameStop etc.
# =========================================================

CHANNEL_TARGET = os.getenv(
    "CHANNEL_TARGET"
)


# =========================================================
# SHOPIFY / SMALL TCG STORES
#
# NEW in v0.7.6
# =========================================================

CHANNEL_SHOPIFY_ALERTS = os.getenv(
    "CHANNEL_SHOPIFY_ALERTS"
)


# =========================================================
# FEATURE CHANNELS
# =========================================================

CHANNEL_PREORDER_ALERTS = os.getenv(
    "CHANNEL_PREORDER_ALERTS"
)

CHANNEL_EARLY_PAGE_DETECTION = os.getenv(
    "CHANNEL_EARLY_PAGE_DETECTION"
)

CHANNEL_DEALS = os.getenv(
    "CHANNEL_DEALS"
)

CHANNEL_INTERNATIONAL_EXCLUSIVES = os.getenv(
    "CHANNEL_INTERNATIONAL_EXCLUSIVES"
)

CHANNEL_INVENTORY_FLICKERS = os.getenv(
    "CHANNEL_INVENTORY_FLICKERS"
)

CHANNEL_RELEASE_RADAR = os.getenv(
    "CHANNEL_RELEASE_RADAR"
)

CHANNEL_POKEMON_QUEUE = os.getenv(
    "CHANNEL_POKEMON_QUEUE"
)


# =========================================================
# CHANNEL MAP
# =========================================================

CHANNEL_MAP = {

    "CHANNEL_TARGET":
        CHANNEL_TARGET,

    "CHANNEL_SHOPIFY_ALERTS":
        CHANNEL_SHOPIFY_ALERTS,

    "CHANNEL_PREORDER_ALERTS":
        CHANNEL_PREORDER_ALERTS,

    "CHANNEL_EARLY_PAGE_DETECTION":
        CHANNEL_EARLY_PAGE_DETECTION,

    "CHANNEL_DEALS":
        CHANNEL_DEALS,

    "CHANNEL_INTERNATIONAL_EXCLUSIVES":
        CHANNEL_INTERNATIONAL_EXCLUSIVES,

    "CHANNEL_INVENTORY_FLICKERS":
        CHANNEL_INVENTORY_FLICKERS,

    "CHANNEL_RELEASE_RADAR":
        CHANNEL_RELEASE_RADAR,

    "CHANNEL_POKEMON_QUEUE":
        CHANNEL_POKEMON_QUEUE,
}


# =========================================================
# ALERT ACCESS
# =========================================================

ALERT_ACCESS = {

    # -----------------------------------------------------
    # True major retailers
    # -----------------------------------------------------

    "major_retailer": {

        "minimum_tier":
            "Free",

        "channel_variable":
            "CHANNEL_TARGET",
    },


    # -----------------------------------------------------
    # Shopify / independent TCG stores
    # -----------------------------------------------------

    "shopify": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_SHOPIFY_ALERTS",
    },


    # -----------------------------------------------------
    # Feature channels
    # -----------------------------------------------------

    "preorder": {

        "minimum_tier":
            "Lite",

        "channel_variable":
            "CHANNEL_PREORDER_ALERTS",
    },

    "page_live": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_EARLY_PAGE_DETECTION",
    },

    "deal": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_DEALS",
    },

    "international": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_INTERNATIONAL_EXCLUSIVES",
    },

    "inventory_flicker": {

        "minimum_tier":
            "Premium+",

        "channel_variable":
            "CHANNEL_INVENTORY_FLICKERS",
    },

    "release_radar": {

        "minimum_tier":
            "Premium+",

        "channel_variable":
            "CHANNEL_RELEASE_RADAR",
    },

    "pokemon_queue": {

        "minimum_tier":
            "Premium+",

        "channel_variable":
            "CHANNEL_POKEMON_QUEUE",
    },
}