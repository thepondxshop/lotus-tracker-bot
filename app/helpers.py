import discord

from app.config import (
    GAME_ROLES,
    SUBSCRIPTION_ROLES,
    TIER_LEVELS,
)


# =========================================================
# SAFE INTEGER CONVERSION
# =========================================================

def safe_int(value):
    try:
        return int(value)

    except (TypeError, ValueError):
        return None


# =========================================================
# SUBSCRIPTION DETECTION
# =========================================================

def get_subscription(
    member: discord.Member
):
    member_role_ids = {
        role.id
        for role in member.roles
    }

    tier_order = [
        "Premium+",
        "Premium",
        "Lite",
        "Free",
    ]

    for tier in tier_order:
        role_id = safe_int(
            SUBSCRIPTION_ROLES.get(tier)
        )

        if (
            role_id
            and role_id in member_role_ids
        ):
            return tier

    return "Free"


# =========================================================
# GAME ROLE DETECTION
# =========================================================

def get_followed_games(
    member: discord.Member
):
    member_role_ids = {
        role.id
        for role in member.roles
    }

    followed = []

    for game_name, role_id in GAME_ROLES.items():
        role_id = safe_int(
            role_id
        )

        if (
            role_id
            and role_id in member_role_ids
        ):
            followed.append(
                game_name
            )

    return followed


# =========================================================
# TIER ACCESS CHECK
# =========================================================

def tier_allows(
    current_tier,
    minimum_tier
):
    return (
        TIER_LEVELS.get(
            current_tier,
            0
        )
        >=
        TIER_LEVELS.get(
            minimum_tier,
            0
        )
    )