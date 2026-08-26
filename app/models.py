from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


# =========================================================
# LOTUS TRACKER DATABASE MODELS
# PonDeX Trackers
# Version 0.7.2
# =========================================================


class Base(
    DeclarativeBase
):
    pass


# =========================================================
# USERS
# =========================================================

class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    discord_user_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=False,
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# SUBSCRIPTIONS
# =========================================================

class Subscription(Base):

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    discord_user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
        nullable=False,
    )

    tier: Mapped[str] = mapped_column(
        String(50),
        default="Free",
        nullable=False,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# USER GAME PREFERENCES
# =========================================================

class UserGamePreference(Base):

    __tablename__ = "user_game_preferences"

    __table_args__ = (
        UniqueConstraint(
            "discord_user_id",
            "game",
            name="uq_user_game_preference",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    discord_user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
        nullable=False,
    )

    game: Mapped[str] = mapped_column(
        String(150),
        index=True,
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# STORES
# =========================================================

class Store(Base):

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    domain: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        unique=True,
    )

    platform: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    region: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    trust_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # =====================================================
    # STORE HEALTH
    # =====================================================

    health_status: Mapped[str] = mapped_column(
        String(50),
        default="HEALTHY",
        nullable=False,
    )

    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Values:
    #
    # None
    # MANUAL
    # HEALTH
    # REMOVED

    disabled_reason: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# PRODUCTS
# =========================================================

class Product(Base):

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    game: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    canonical_name: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    product_type: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    region: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    language: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    release_date: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# STORE PRODUCTS
# =========================================================

class StoreProduct(Base):

    __tablename__ = "store_products"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    store_id: Mapped[int] = mapped_column(
        ForeignKey(
            "stores.id"
        ),
        nullable=False,
        index=True,
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey(
            "products.id"
        ),
        nullable=False,
        index=True,
    )

    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    sku: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="USD",
        nullable=False,
    )

    in_stock: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# ALERT HISTORY
# =========================================================

class Alert(Base):

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "products.id"
        ),
        nullable=True,
        index=True,
    )

    store_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "stores.id"
        ),
        nullable=True,
        index=True,
    )

    alert_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    minimum_tier: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    discord_channel_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    discord_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# PRODUCT EVENT HISTORY
# =========================================================

class ProductEventRecord(Base):

    __tablename__ = "product_event_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    game: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )

    product_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    store_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    product_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )

    price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="USD",
        nullable=False,
    )

    in_stock: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    region: Mapped[str] = mapped_column(
        String(100),
        default="US",
        nullable=False,
    )

    language: Mapped[str] = mapped_column(
        String(100),
        default="English",
        nullable=False,
    )

    product_type: Mapped[str] = mapped_column(
        String(150),
        default="Unknown",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# PRICE HISTORY
# =========================================================

class PriceHistory(Base):

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    store_product_id: Mapped[int] = mapped_column(
        ForeignKey(
            "store_products.id"
        ),
        nullable=False,
        index=True,
    )

    price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="USD",
        nullable=False,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# =========================================================
# POKEMON CENTER PRODUCT REGISTRY
# =========================================================

class PokemonCenterProduct(Base):

    __tablename__ = "pokemon_center_products"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    region: Mapped[str] = mapped_column(
        String(20),
        default="US",
        nullable=False,
        index=True,
    )

    url: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )

    product_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    last_state: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    last_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    last_available: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )