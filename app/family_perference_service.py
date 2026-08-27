from sqlalchemy import (
    delete,
    select,
)

from app.database import (
    SessionLocal,
)

from app.models import (
    UserProductFamilyPreference,
)

from app.product_family import (
    normalize_product_family,
)


# =========================================================
# LOTUS PRODUCT FAMILY PREFERENCES
# PonDeX Trackers
# Version 1.0.2
# =========================================================


PRODUCT_FAMILIES = (

    "GLOBAL_STANDARD",
    "JP",
    "KR",
    "CN",
    "UNKNOWN",
)


DEFAULT_FAMILY_PREFERENCES = {

    "GLOBAL_STANDARD":
        True,

    "JP":
        False,

    "KR":
        False,

    "CN":
        False,

    "UNKNOWN":
        False,
}


# =========================================================
# NORMALIZE
# =========================================================

def normalize_family_preferences(
    preferences,
):

    result = dict(
        DEFAULT_FAMILY_PREFERENCES
    )

    if not preferences:

        return result


    for (
        family,
        enabled,
    ) in preferences.items():

        normalized_family = (
            normalize_product_family(
                family
            )
        )

        if (
            normalized_family
            not in PRODUCT_FAMILIES
        ):

            continue

        result[
            normalized_family
        ] = bool(
            enabled
        )


    return result


# =========================================================
# GET FAMILY PREFERENCES
# =========================================================

async def get_family_preferences(
    discord_user_id,
    game,
):

    defaults = dict(
        DEFAULT_FAMILY_PREFERENCES
    )


    if SessionLocal is None:

        return defaults


    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    UserProductFamilyPreference
                )
                .where(
                    UserProductFamilyPreference.discord_user_id
                    == discord_user_id
                )
                .where(
                    UserProductFamilyPreference.game
                    == game
                )
            )
        )


        rows = list(
            result.scalars().all()
        )


    if not rows:

        return defaults


    preferences = dict(
        defaults
    )


    for row in rows:

        family = (
            normalize_product_family(
                row.product_family
            )
        )

        if (
            family
            in PRODUCT_FAMILIES
        ):

            preferences[
                family
            ] = bool(
                row.enabled
            )


    return preferences


# =========================================================
# SAVE FAMILY PREFERENCES
# =========================================================

async def save_family_preferences(
    *,
    discord_user_id,
    game,
    preferences,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database unavailable."
        )


    normalized = (
        normalize_family_preferences(
            preferences
        )
    )


    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    UserProductFamilyPreference
                )
                .where(
                    UserProductFamilyPreference.discord_user_id
                    == discord_user_id
                )
                .where(
                    UserProductFamilyPreference.game
                    == game
                )
            )
        )


        existing_rows = {

            row.product_family:
                row

            for row
            in result.scalars().all()
        }


        for family in PRODUCT_FAMILIES:

            enabled = bool(
                normalized[
                    family
                ]
            )


            row = (
                existing_rows.get(
                    family
                )
            )


            if row is None:

                row = (
                    UserProductFamilyPreference(

                        discord_user_id=(
                            discord_user_id
                        ),

                        game=(
                            game
                        ),

                        product_family=(
                            family
                        ),

                        enabled=(
                            enabled
                        ),
                    )
                )


                session.add(
                    row
                )


            else:

                row.enabled = (
                    enabled
                )


        await session.commit()


    return normalized


# =========================================================
# ENSURE DEFAULT PREFERENCES
# =========================================================

async def ensure_family_preferences(
    discord_user_id,
    game,
):

    if SessionLocal is None:

        return dict(
            DEFAULT_FAMILY_PREFERENCES
        )


    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    UserProductFamilyPreference.id
                )
                .where(
                    UserProductFamilyPreference.discord_user_id
                    == discord_user_id
                )
                .where(
                    UserProductFamilyPreference.game
                    == game
                )
                .limit(
                    1
                )
            )
        )


        exists = (
            result.scalar()
            is not None
        )


    if exists:

        return (
            await get_family_preferences(

                discord_user_id,

                game,
            )
        )


    return (
        await save_family_preferences(

            discord_user_id=(
                discord_user_id
            ),

            game=(
                game
            ),

            preferences=(
                DEFAULT_FAMILY_PREFERENCES
            ),
        )
    )


# =========================================================
# DOES USER ALLOW FAMILY?
# =========================================================

async def user_allows_product_family(
    discord_user_id,
    game,
    product_family,
):

    family = (
        normalize_product_family(
            product_family
        )
        or "UNKNOWN"
    )


    preferences = (
        await get_family_preferences(

            discord_user_id,

            game,
        )
    )


    return bool(
        preferences.get(
            family,
            False,
        )
    )


# =========================================================
# BULK LOAD
#
# Worker can use this instead of doing one database lookup
# per member.
# =========================================================

async def get_family_preferences_for_users(
    discord_user_ids,
    game,
):

    ids = {

        int(
            user_id
        )

        for user_id
        in discord_user_ids

        if user_id
    }


    if not ids:

        return {}


    output = {

        user_id:
            dict(
                DEFAULT_FAMILY_PREFERENCES
            )

        for user_id
        in ids
    }


    if SessionLocal is None:

        return output


    async with SessionLocal() as session:

        result = (
            await session.execute(

                select(
                    UserProductFamilyPreference
                )
                .where(
                    UserProductFamilyPreference.discord_user_id.in_(
                        ids
                    )
                )
                .where(
                    UserProductFamilyPreference.game
                    == game
                )
            )
        )


        rows = list(
            result.scalars().all()
        )


    for row in rows:

        user_id = int(
            row.discord_user_id
        )


        family = (
            normalize_product_family(
                row.product_family
            )
        )


        if (
            user_id
            not in output

            or

            family
            not in PRODUCT_FAMILIES
        ):

            continue


        output[
            user_id
        ][
            family
        ] = bool(
            row.enabled
        )


    return output


# =========================================================
# REMOVE GAME FAMILY PREFERENCES
# =========================================================

async def clear_family_preferences(
    discord_user_id,
    game,
):

    if SessionLocal is None:

        return False


    async with SessionLocal() as session:

        await session.execute(

            delete(
                UserProductFamilyPreference
            )
            .where(
                UserProductFamilyPreference.discord_user_id
                == discord_user_id
            )
            .where(
                UserProductFamilyPreference.game
                == game
            )
        )


        await session.commit()


    return True