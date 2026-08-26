import os

from sqlalchemy import (
    delete,
    select,
)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import (
    Base,
    Subscription,
    User,
    UserGamePreference,
)


# =========================================================
# LOTUS TRACKER DATABASE
# PonDeX Trackers
# Version 0.4.2
# =========================================================


DATABASE_URL = os.getenv(
    "DATABASE_URL"
)


# =========================================================
# DATABASE URL NORMALIZATION
# =========================================================

def normalize_database_url(
    url: str | None
):
    if not url:
        return None

    if url.startswith(
        "postgresql://"
    ):
        return url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    if url.startswith(
        "postgres://"
    ):
        return url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )

    return url


ASYNC_DATABASE_URL = (
    normalize_database_url(
        DATABASE_URL
    )
)


# =========================================================
# ENGINE
# =========================================================

engine = None
SessionLocal = None


if ASYNC_DATABASE_URL:

    engine = create_async_engine(
        ASYNC_DATABASE_URL,
        pool_pre_ping=True,
    )

    SessionLocal = (
        async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

async def init_database():

    if engine is None:

        raise RuntimeError(
            "DATABASE_URL is missing."
        )

    async with engine.begin() as connection:

        await connection.run_sync(
            Base.metadata.create_all
        )


# =========================================================
# SAVE USER + SUBSCRIPTION + GAME PREFERENCES
# =========================================================

async def save_user_preferences(
    discord_user_id: int,
    username: str,
    subscription_tier: str,
    selected_games: list[str],
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        # -------------------------------------------------
        # USER
        # -------------------------------------------------

        user_result = await session.execute(

            select(
                User
            ).where(
                User.discord_user_id
                == discord_user_id
            )
        )

        user = (
            user_result.scalar_one_or_none()
        )

        if user is None:

            user = User(
                discord_user_id=(
                    discord_user_id
                ),
                username=username,
            )

            session.add(
                user
            )

        else:

            user.username = username

        # -------------------------------------------------
        # SUBSCRIPTION
        # -------------------------------------------------

        subscription_result = (
            await session.execute(

                select(
                    Subscription
                ).where(
                    Subscription.discord_user_id
                    == discord_user_id
                )
            )
        )

        subscription = (
            subscription_result.scalar_one_or_none()
        )

        if subscription is None:

            subscription = Subscription(
                discord_user_id=(
                    discord_user_id
                ),
                tier=subscription_tier,
                active=True,
            )

            session.add(
                subscription
            )

        else:

            subscription.tier = (
                subscription_tier
            )

            subscription.active = True

        # -------------------------------------------------
        # REPLACE GAME PREFERENCES
        # -------------------------------------------------

        await session.execute(

            delete(
                UserGamePreference
            ).where(
                UserGamePreference.discord_user_id
                == discord_user_id
            )
        )

        for game in sorted(
            set(
                selected_games
            )
        ):

            preference = (
                UserGamePreference(
                    discord_user_id=(
                        discord_user_id
                    ),
                    game=game,
                    enabled=True,
                )
            )

            session.add(
                preference
            )

        # -------------------------------------------------
        # COMMIT
        # -------------------------------------------------

        await session.commit()


# =========================================================
# LOAD USER SETTINGS
# =========================================================

async def load_user_preferences(
    discord_user_id: int
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        # -------------------------------------------------
        # USER
        # -------------------------------------------------

        user_result = await session.execute(

            select(
                User
            ).where(
                User.discord_user_id
                == discord_user_id
            )
        )

        user = (
            user_result.scalar_one_or_none()
        )

        if user is None:

            return None

        # -------------------------------------------------
        # SUBSCRIPTION
        # -------------------------------------------------

        subscription_result = (
            await session.execute(

                select(
                    Subscription
                ).where(
                    Subscription.discord_user_id
                    == discord_user_id
                )
            )
        )

        subscription = (
            subscription_result.scalar_one_or_none()
        )

        # -------------------------------------------------
        # GAMES
        # -------------------------------------------------

        games_result = await session.execute(

            select(
                UserGamePreference
            ).where(
                UserGamePreference.discord_user_id
                == discord_user_id
            ).where(
                UserGamePreference.enabled
                == True
            )
        )

        game_preferences = (
            games_result.scalars().all()
        )

        games = [
            preference.game
            for preference
            in game_preferences
        ]

        return {
            "discord_user_id": (
                user.discord_user_id
            ),
            "username": (
                user.username
            ),
            "subscription": (
                subscription.tier
                if subscription
                else "Free"
            ),
            "games": sorted(
                games
            ),
        }


# =========================================================
# SYNC DISCORD MEMBER TO DATABASE
# =========================================================

async def sync_member_to_database(
    member,
    subscription_tier: str,
    selected_games: list[str],
):

    username = (
        member.name
        if hasattr(
            member,
            "name"
        )
        else str(
            member
        )
    )

    await save_user_preferences(
        discord_user_id=member.id,
        username=username,
        subscription_tier=subscription_tier,
        selected_games=selected_games,
    )