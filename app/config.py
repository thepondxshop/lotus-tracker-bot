import os


# =========================================================
# LOTUS TRACKER CONFIGURATION
# PonDeX Trackers
# Version 0.7
# =========================================================


# =========================================================
# DISCORD
# =========================================================

DISCORD_TOKEN = os.getenv(
    "DISCORD_TOKEN"
)


# =========================================================
# GAME ROLE IDS
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
# SUBSCRIPTION ROLE IDS
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
# DISCORD CHANNEL IDS
# =========================================================

CHANNEL_ROLES = os.getenv(
    "CHANNEL_ROLES"
)


# =========================================================
# MAJOR RETAILER / BASIC ALERTS
# =========================================================

CHANNEL_TARGET = os.getenv(
    "CHANNEL_TARGET"
)


# =========================================================
# LITE
# =========================================================

CHANNEL_PREORDER_ALERTS = os.getenv(
    "CHANNEL_PREORDER_ALERTS"
)


# =========================================================
# PREMIUM
# =========================================================

CHANNEL_EARLY_PAGE_DETECTION = os.getenv(
    "CHANNEL_EARLY_PAGE_DETECTION"
)

CHANNEL_DEALS = os.getenv(
    "CHANNEL_DEALS"
)

CHANNEL_INTERNATIONAL_EXCLUSIVES = os.getenv(
    "CHANNEL_INTERNATIONAL_EXCLUSIVES"
)


# =========================================================
# PREMIUM+
# =========================================================

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
#
# Event routing references Railway variable names instead
# of directly accessing environment variables.
# =========================================================

CHANNEL_MAP = {

    "CHANNEL_TARGET":
        CHANNEL_TARGET,

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
# SUBSCRIPTION LEVELS
# =========================================================

TIER_LEVELS = {

    "Free": 0,

    "Lite": 1,

    "Premium": 2,

    "Premium+": 3,
}


# =========================================================
# ALERT ACCESS MATRIX
# =========================================================

ALERT_ACCESS = {

    # -----------------------------------------------------
    # FREE
    # -----------------------------------------------------

    "major_retailer": {

        "minimum_tier":
            "Free",

        "channel_variable":
            "CHANNEL_TARGET",
    },

    # -----------------------------------------------------
    # LITE
    # -----------------------------------------------------

    "preorder": {

        "minimum_tier":
            "Lite",

        "channel_variable":
            "CHANNEL_PREORDER_ALERTS",
    },

    # -----------------------------------------------------
    # PREMIUM
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # PREMIUM+
    # -----------------------------------------------------

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


# =========================================================
# GAME SELECTOR DATA
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
        "Pokémon TCG alerts",
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