import os

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from app.models import Base


DATABASE_URL = os.getenv("DATABASE_URL")


def normalize_database_url(url: str | None):
    if not url:
        return None

    if url.startswith("postgresql://"):
        return url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    if url.startswith("postgres://"):
        return url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )

    return url


ASYNC_DATABASE_URL = normalize_database_url(
    DATABASE_URL
)


engine = None
SessionLocal = None


if ASYNC_DATABASE_URL:
    engine = create_async_engine(
        ASYNC_DATABASE_URL,
        pool_pre_ping=True,
    )

    SessionLocal = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def init_database():
    if engine is None:
        raise RuntimeError(
            "DATABASE_URL is missing."
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )


async def get_database_session():
    if SessionLocal is None:
        raise RuntimeError(
            "Database session is not configured."
        )

    async with SessionLocal() as session:
        yield session