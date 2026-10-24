import os


# =========================================================
# LOTUS CONFIGURATION
# PonDeX Trackers
# Bot release 1.0.6 • Game registry GAMES4
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
    "Beyblade X TCG — Blader League": (os.getenv("ROLE_BEYBLADE_X") or "1563394352531775618"),
    "World of Tanks TCG": (os.getenv("ROLE_WORLD_OF_TANKS") or "1563315646324940840"),
    "Vibes TCG": (os.getenv("ROLE_VIBES") or "1563315709277114501"),
    "Shadowverse Evolve": (os.getenv("ROLE_SHADOWVERSE") or "1563315730743693362"),
    "Final Fantasy TCG": os.getenv("ROLE_FINAL_FANTASY"),
    "CookieRun: Braverse": os.getenv("ROLE_COOKIE_RUN"),
    "Harry Potter TCG — Kakawow": os.getenv("ROLE_HARRY_POTTER"),
    "Horo Beat": os.getenv("ROLE_HORO_BEAT"),
    "Jurassic Park TCG": os.getenv("ROLE_JURASSIC_PARK"),
    "Godzilla TCG": os.getenv("ROLE_GODZILLA"),
    "Wuthering Waves": os.getenv("ROLE_WUTHERING_WAVES"),
    "Union Arena": os.getenv("ROLE_UNION_ARENA"),

    "Cataclysm Arcade": os.getenv("ROLE_CATACLYSM_ARCADE"),

    "MTG": os.getenv("ROLE_MTG"),

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
    ("Beyblade X TCG — Blader League", "🌪️", "Blader League TCG — announced for 2027; exact date TBA"),
    ("World of Tanks TCG", "🛡️", "World of Tanks: The Card Game alerts"),
    ("Vibes TCG", "🐧", "Vibes: The Pudgy TCG alerts"),
    ("Shadowverse Evolve", "🔮", "Shadowverse: Evolve physical TCG alerts"),
    ("Final Fantasy TCG", "⚔️", "Final Fantasy Trading Card Game alerts"),
    ("CookieRun: Braverse", "🍪", "CookieRun Braverse TCG alerts"),
    ("Harry Potter TCG — Kakawow", "🪄", "Kakawow Harry Potter TCG alerts"),
    ("Horo Beat", "👻", "Horo Beat Japanese TCG alerts"),
    ("Jurassic Park TCG", "🦖", "Jurassic Park TCG alerts"),
    ("Godzilla TCG", "👾", "Godzilla TCG alerts"),
    ("Wuthering Waves", "🧜‍♀️", "Wuthering Waves alerts"),
    ("Union Arena", "🃏", "Union Arena alerts"),

    ("Cataclysm Arcade", "🚇", "Cataclysm Arcade alerts"),

    ("MTG", "🧙", "Magic: The Gathering alerts"),

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
