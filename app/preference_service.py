from sqlalchemy import (
    delete,
    select,
)

from app.config import (
    GAME_ROLES,
)

from app.database import (
    SessionLocal,
)

from app.helpers import (
    safe_int,
)

from app.models import (
    UserProductPreference,
)


# =========================================================
# LOTUS ALERT PREFERENCE SERVICE
# PonDeX Trackers
# Version 0.7.8
#
# Product alert preferences:
#
# SEALED
# SINGLE
# ACCESSORY
# UNKNOWN
#
# These are maintained using Discord roles so Lotus can
# ping only the members who selected that product type.
# =========================================================


PRODUCT_CATEGORIES = (
    "SEALED",
    "SINGLE",
    "ACCESSORY",
    "UNKNOWN",
)


DEFAULT_PREFERENCES = {

    "SEALED": True,

    "SINGLE": False,

    "ACCESSORY": False,

    "UNKNOWN": True,
}


# =========================================================
# DISPLAY NAME
# =========================================================

def category_display_name(
    category,
):

    category = (
        category
        or "UNKNOWN"
    ).upper()

    return {

        "SEALED":
            "Sealed",

        "SINGLE":
            "Singles",

        "ACCESSORY":
            "Accessories",

        "UNKNOWN":
            "Unknown",

    }.get(
        category,
        "Unknown",
    )


# =========================================================
# ROLE NAME
# =========================================================

def category_role_name(
    game,
    category,
):

    return (
        f"Lotus • "
        f"{game} • "
        f"{category_display_name(category)}"
    )


# =========================================================
# FIND CATEGORY ROLE
# =========================================================

def find_category_role(
    guild,
    game,
    category,
):

    wanted_name = (
        category_role_name(
            game,
            category,
        )
    )

    for role in guild.roles:

        if (
            role.name
            == wanted_name
        ):

            return role

    return None


# =========================================================
# ENSURE CATEGORY ROLES
# =========================================================

async def ensure_category_roles(
    guild,
    game,
):

    roles = {}

    for category in PRODUCT_CATEGORIES:

        role = (
            find_category_role(
                guild,
                game,
                category,
            )
        )

        if role is None:

            role = (
                await guild.create_role(

                    name=(
                        category_role_name(
                            game,
                            category,
                        )
                    ),

                    mentionable=True,

                    reason=(
                        "Lotus product alert preferences"
                    ),
                )
            )

            print(
                (
                    "LOTUS ALERT ROLE CREATED | "
                    f"Game={game} | "
                    f"Category={category} | "
                    f"Role={role.name}"
                )
            )

        roles[
            category
        ] = role

    return roles


# =========================================================
# CHECK CUSTOM PREFS
# =========================================================

async def user_has_custom_preferences(
    discord_user_id,
    game,
):

    if SessionLocal is None:

        return False

    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    UserProductPreference.id
                )
                .where(
                    UserProductPreference.discord_user_id
                    == discord_user_id
                )
                .where(
                    UserProductPreference.game
                    == game
                )
                .limit(
                    1
                )
            )
        )

        return (
            result.scalar_one_or_none()
            is not None
        )


# =========================================================
# LOAD PREFERENCES
# =========================================================

async def get_product_preferences(
    discord_user_id,
    game,
):

    preferences = dict(
        DEFAULT_PREFERENCES
    )

    if SessionLocal is None:

        return preferences

    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    UserProductPreference
                )
                .where(
                    UserProductPreference.discord_user_id
                    == discord_user_id
                )
                .where(
                    UserProductPreference.game
                    == game
                )
            )
        )

        rows = (
            result.scalars().all()
        )

        for row in rows:

            category = (
                row.product_category
                or "UNKNOWN"
            ).upper()

            if (
                category
                in PRODUCT_CATEGORIES
            ):

                preferences[
                    category
                ] = bool(
                    row.enabled
                )

    return preferences


# =========================================================
# SAVE PREFERENCES
# =========================================================

async def save_product_preferences(
    discord_user_id,
    game,
    preferences,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is unavailable."
        )

    async with SessionLocal() as session:

        await session.execute(

            delete(
                UserProductPreference
            )
            .where(
                UserProductPreference.discord_user_id
                == discord_user_id
            )
            .where(
                UserProductPreference.game
                == game
            )
        )

        for category in PRODUCT_CATEGORIES:

            enabled = bool(
                preferences.get(
                    category,
                    DEFAULT_PREFERENCES[
                        category
                    ],
                )
            )

            row = (
                UserProductPreference(

                    discord_user_id=(
                        discord_user_id
                    ),

                    game=game,

                    product_category=(
                        category
                    ),

                    enabled=enabled,
                )
            )

            session.add(
                row
            )

        await session.commit()


# =========================================================
# APPLY MEMBER ROLES
# =========================================================

async def apply_member_preference_roles(
    member,
    game,
    preferences,
):

    guild = (
        member.guild
    )

    roles = (
        await ensure_category_roles(
            guild,
            game,
        )
    )

    errors = []

    for (
        category,
        role,
    ) in roles.items():

        enabled = bool(
            preferences.get(
                category,
                DEFAULT_PREFERENCES[
                    category
                ],
            )
        )

        try:

            if enabled:

                if (
                    role
                    not in member.roles
                ):

                    await member.add_roles(

                        role,

                        reason=(
                            "Lotus alert preference enabled"
                        ),
                    )

            else:

                if (
                    role
                    in member.roles
                ):

                    await member.remove_roles(

                        role,

                        reason=(
                            "Lotus alert preference disabled"
                        ),
                    )

        except Exception as error:

            errors.append(
                (
                    f"{category}: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

    return errors


# =========================================================
# INITIALIZE EXISTING MEMBERS
#
# Existing users get:
#
# Sealed      = ON
# Singles     = OFF
# Accessories = OFF
# Unknown     = ON
# =========================================================

async def initialize_game_alert_roles(
    guild,
    game,
):

    roles = (
        await ensure_category_roles(
            guild,
            game,
        )
    )

    broad_role_id = (
        safe_int(
            GAME_ROLES.get(
                game
            )
        )
    )

    broad_role = (

        guild.get_role(
            broad_role_id
        )

        if broad_role_id

        else None
    )

    if broad_role is None:

        raise RuntimeError(
            (
                f"Main Discord role for "
                f"{game} was not found."
            )
        )

    members_initialized = 0

    for member in broad_role.members:

        custom = (
            await user_has_custom_preferences(
                member.id,
                game,
            )
        )

        if custom:

            prefs = (
                await get_product_preferences(
                    member.id,
                    game,
                )
            )

        else:

            prefs = dict(
                DEFAULT_PREFERENCES
            )

            await save_product_preferences(

                discord_user_id=(
                    member.id
                ),

                game=game,

                preferences=prefs,
            )

        await apply_member_preference_roles(

            member,

            game,

            prefs,
        )

        members_initialized += 1

    return {

        "game":
            game,

        "members":
            members_initialized,

        "roles":
            roles,
    }


# =========================================================
# EVENT ROLE
# =========================================================

def get_event_notification_role(
    guild,
    game,
    product_category,
):

    if not game:

        return None

    category = (
        product_category
        or "UNKNOWN"
    ).upper()

    # =====================================================
    # PREFERENCE ROLE
    # =====================================================

    category_role = (
        find_category_role(
            guild,
            game,
            category,
        )
    )

    if category_role is not None:

        return category_role


    # =====================================================
    # BACKWARDS-COMPATIBLE FALLBACK
    #
    # Until /setupalertprefs has been run:
    #
    # SEALED / UNKNOWN → main game role
    # SINGLE / ACCESSORY → no ping
    #
    # This prevents singles from blasting everyone.
    # =====================================================

    if (
        category
        not in (
            "SEALED",
            "UNKNOWN",
        )
    ):

        return None

    broad_role_id = (
        safe_int(
            GAME_ROLES.get(
                game
            )
        )
    )

    if not broad_role_id:

        return None

    return (
        guild.get_role(
            broad_role_id
        )
    )