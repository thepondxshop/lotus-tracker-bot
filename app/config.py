import os


# =========================================================
# LOTUS CONFIGURATION
# PonDeX Trackers
# Version 0.7.6-fixed
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
# TIER ROLE ALIAS
#
# Some older helper code may still import TIER_ROLES.
# Keeping this alias prevents version mismatch crashes.
# =========================================================

TIER_ROLES = (
    SUBSCRIPTION_ROLES
)


# =========================================================
# SUBSCRIPTION TIER LEVELS
#
# helpers.py uses this for tier comparisons.
# =========================================================

TIER_LEVELS = {

    "Free":
        0,

    "Lite":
        1,

    "Premium":
        2,

    "Premium+":
        3,
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
# CHANNELS
# =========================================================


# ---------------------------------------------------------
# Roles
# ---------------------------------------------------------

CHANNEL_ROLES = os.getenv(
    "CHANNEL_ROLES"
)


# ---------------------------------------------------------
# Major Retailers
#
# Target / Walmart / Best Buy / GameStop etc.
# ---------------------------------------------------------

CHANNEL_TARGET = os.getenv(
    "CHANNEL_TARGET"
)


# ---------------------------------------------------------
# Shopify / Independent TCG stores
#
# Saga Concepts
# Hobbiesville
# etc.
#
# Point this Railway variable to your existing
# #shopify-drops channel.
# ---------------------------------------------------------

CHANNEL_SHOPIFY_ALERTS = os.getenv(
    "CHANNEL_SHOPIFY_ALERTS"
)


# ---------------------------------------------------------
# Preorders
# ---------------------------------------------------------

CHANNEL_PREORDER_ALERTS = os.getenv(
    "CHANNEL_PREORDER_ALERTS"
)


# ---------------------------------------------------------
# Early Page Detection
# ---------------------------------------------------------

CHANNEL_EARLY_PAGE_DETECTION = os.getenv(
    "CHANNEL_EARLY_PAGE_DETECTION"
)


# ---------------------------------------------------------
# Deals
# ---------------------------------------------------------

CHANNEL_DEALS = os.getenv(
    "CHANNEL_DEALS"
)


# ---------------------------------------------------------
# International
# ---------------------------------------------------------

CHANNEL_INTERNATIONAL_EXCLUSIVES = os.getenv(
    "CHANNEL_INTERNATIONAL_EXCLUSIVES"
)


# ---------------------------------------------------------
# Inventory Flicker
# ---------------------------------------------------------

CHANNEL_INVENTORY_FLICKERS = os.getenv(
    "CHANNEL_INVENTORY_FLICKERS"
)


# ---------------------------------------------------------
# Release Radar
# ---------------------------------------------------------

CHANNEL_RELEASE_RADAR = os.getenv(
    "CHANNEL_RELEASE_RADAR"
)


# ---------------------------------------------------------
# Pokémon Center Queue
# ---------------------------------------------------------

CHANNEL_POKEMON_QUEUE = os.getenv(
    "CHANNEL_POKEMON_QUEUE"
)


# =========================================================
# CHANNEL MAP
#
# worker.py and main.py use symbolic channel names here.
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
# ALERT ACCESS MATRIX
# =========================================================

ALERT_ACCESS = {

    # -----------------------------------------------------
    # Major Retailers
    #
    # Target / Walmart / etc.
    # -----------------------------------------------------

    "major_retailer": {

        "minimum_tier":
            "Free",

        "channel_variable":
            "CHANNEL_TARGET",
    },


    # -----------------------------------------------------
    # Shopify / Independent TCG stores
    #
    # Saga Concepts / Hobbiesville
    # -----------------------------------------------------

    "shopify": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_SHOPIFY_ALERTS",
    },


    # -----------------------------------------------------
    # Preorders
    # -----------------------------------------------------

    "preorder": {

        "minimum_tier":
            "Lite",

        "channel_variable":
            "CHANNEL_PREORDER_ALERTS",
    },


    # -----------------------------------------------------
    # Early Page Detection
    # -----------------------------------------------------

    "page_live": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_EARLY_PAGE_DETECTION",
    },


    # -----------------------------------------------------
    # Deals
    # -----------------------------------------------------

    "deal": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_DEALS",
    },


    # -----------------------------------------------------
    # International
    # -----------------------------------------------------

    "international": {

        "minimum_tier":
            "Premium",

        "channel_variable":
            "CHANNEL_INTERNATIONAL_EXCLUSIVES",
    },


    # -----------------------------------------------------
    # Inventory Flicker
    # -----------------------------------------------------

    "inventory_flicker": {

        "minimum_tier":
            "Premium+",

        "channel_variable":
            "CHANNEL_INVENTORY_FLICKERS",
    },


    # -----------------------------------------------------
    # Release Radar
    # -----------------------------------------------------

    "release_radar": {

        "minimum_tier":
            "Premium+",

        "channel_variable":
            "CHANNEL_RELEASE_RADAR",
    },


    # -----------------------------------------------------
    # Pokémon Center Queue
    # -----------------------------------------------------

    "pokemon_queue": {

        "minimum_tier":
            "Premium+",

        "channel_variable":
            "CHANNEL_POKEMON_QUEUE",
    },
}