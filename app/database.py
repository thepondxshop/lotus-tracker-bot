import asyncio
import os

from alembic import command
from alembic.config import Config

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
# LOTUS DATABASE
# PonDeX Trackers
# Version 0.6.3
# =========================================================


DATABASE_URL = os.getenv(
    "DATABASE_URL"
)


# =========================================================
# DATABASE URL
# =========================================================

def normalize_database_url(
    url: str | None,
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
# ALEMBIC
# =========================================================

def run_alembic_migrations():

    config = Config(
        "alembic.ini"
    )

    command.upgrade(
        config,
        "head",
    )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

async def init_database():

    if engine is None:

        raise RuntimeError(
            "DATABASE_URL is missing."
        )

    # -----------------------------------------------------
    # create_all still provides safe bootstrap behavior
    # for brand-new tables.
    #
    # It does NOT alter existing columns.
    # Alembic handles schema alterations.
    # -----------------------------------------------------

    async with engine.begin() as connection:

        await connection.run_sync(
            Base.metadata.create_all
        )

    # Run Alembic in its own thread so Alembic can manage
    # its async migration event loop without conflicting
    # with Discord's running loop.

    await asyncio.to_thread(
        run_alembic_migrations
    )


# =========================================================
# SAVE USER PREFERENCES
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
                discord_user_id=discord_user_id,
                username=username,
            )

            session.add(
                user
            )

        else:

            user.username = username

        subscription_result = await session.execute(

            select(
                Subscription
            ).where(
                Subscription.discord_user_id
                == discord_user_id
            )
        )

        subscription = (
            subscription_result.scalars().first()
        )

        if subscription is None:

            subscription = Subscription(
                discord_user_id=discord_user_id,
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

            session.add(

                UserGamePreference(
                    discord_user_id=discord_user_id,
                    game=game,
                    enabled=True,
                )
            )

        await session.commit()


# =========================================================
# LOAD USER PREFERENCES
# =========================================================

async def load_user_preferences(
    discord_user_id: int,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

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

        subscription_result = await session.execute(

            select(
                Subscription
            ).where(
                Subscription.discord_user_id
                == discord_user_id
            )
        )

        subscription = (
            subscription_result.scalars().first()
        )

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

        preferences = (
            games_result.scalars().all()
        )

        return {

            "discord_user_id":
                user.discord_user_id,

            "username":
                user.username,

            "subscription":
                (
                    subscription.tier
                    if subscription
                    else "Free"
                ),

            "games":
                sorted(
                    preference.game
                    for preference
                    in preferences
                ),
        }


# =========================================================
# SYNC DISCORD MEMBER
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
            "name",
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