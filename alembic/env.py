import asyncio
import os

from alembic import context

from sqlalchemy import pool

from sqlalchemy.ext.asyncio import (
    async_engine_from_config,
)

from app.models import (
    Base,
)


# =========================================================
# ALEMBIC ENVIRONMENT
# PonDeX Trackers
# =========================================================


config = context.config


def normalize_database_url(
    url: str,
):

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


database_url = os.getenv(
    "DATABASE_URL"
)


if not database_url:

    raise RuntimeError(
        "DATABASE_URL is missing for Alembic."
    )


config.set_main_option(
    "sqlalchemy.url",
    normalize_database_url(
        database_url
    ),
)


target_metadata = (
    Base.metadata
)


def run_migrations_offline():

    url = config.get_main_option(
        "sqlalchemy.url"
    )

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle":
                "named"
        },
    )

    with context.begin_transaction():

        context.run_migrations()


def do_run_migrations(
    connection,
):

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():

        context.run_migrations()


async def run_async_migrations():

    connectable = (
        async_engine_from_config(
            config.get_section(
                config.config_ini_section
            ),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
    )

    async with connectable.connect() as connection:

        await connection.run_sync(
            do_run_migrations
        )

    await connectable.dispose()


def run_migrations_online():

    asyncio.run(
        run_async_migrations()
    )


if context.is_offline_mode():

    run_migrations_offline()

else:

    run_migrations_online()