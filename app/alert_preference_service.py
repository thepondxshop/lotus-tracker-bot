"""Tier-aware member alert preferences for Lotus Tracker Bot.

Step 6K-2C

Design rules:
- Members can control every alert type their current tier includes.
- Alert types outside the current tier are hidden from the UI.
- Hidden/stale preferences are preserved, not deleted on downgrade.
- Backend entitlement checks always run even if a stale preference is True.
- Missing preference rows default to enabled to preserve pre-upgrade behavior.
- The table is created idempotently on PostgreSQL so this milestone can deploy
  without coupling to an unknown Alembic revision chain. A formal migration can
  absorb this table later without changing the service contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import text

from app.database import SessionLocal

VERSION = "1.0.6"

TIER_RANK = {
    "Free": 0,
    "Lite": 1,
    "Premium": 2,
    "Premium+": 3,
}


def normalize_tier(value: str | None) -> str:
    raw = str(value or "Free").strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "free": "Free",
        "basic": "Free",
        "lite": "Lite",
        "premium": "Premium",
        "premium+": "Premium+",
        "premium plus": "Premium+",
        "premiumplus": "Premium+",
    }
    return aliases.get(raw, "Free")


def tier_allows_preference(current_tier: str | None, minimum_tier: str) -> bool:
    current = normalize_tier(current_tier)
    required = normalize_tier(minimum_tier)
    return TIER_RANK[current] >= TIER_RANK[required]


@dataclass(frozen=True)
class AlertPreferenceDefinition:
    key: str
    label: str
    description: str
    minimum_tier: str
    emoji: str


ALERT_PREFERENCE_DEFINITIONS = (
    AlertPreferenceDefinition(
        "NEW_PRODUCT", "New Products",
        "New product discoveries your tier can receive.", "Free", "🆕"
    ),
    AlertPreferenceDefinition(
        "STOCK_AVAILABLE", "In Stock",
        "Products detected as available/in stock.", "Free", "🟢"
    ),
    AlertPreferenceDefinition(
        "RESTOCK", "Restocks",
        "Products that return to stock.", "Free", "🚨"
    ),
    AlertPreferenceDefinition(
        "SOLD_OUT", "Sold Out",
        "Products that become sold out.", "Free", "🔴"
    ),
    AlertPreferenceDefinition(
        "PREORDER", "Preorders",
        "Preorders that become available.", "Lite", "🟣"
    ),
    AlertPreferenceDefinition(
        "PAGE_LIVE", "Page Live / Coming Soon",
        "Early product pages and coming-soon pages.", "Premium", "🔵"
    ),
    AlertPreferenceDefinition(
        "PRICE_DROP", "Price Drops",
        "Tracked products whose price decreases.", "Premium", "🔥"
    ),
    AlertPreferenceDefinition(
        "PRICE_INCREASE", "Price Increases",
        "Tracked products whose price increases.", "Premium", "📈"
    ),
    AlertPreferenceDefinition(
        "PRICE_ERROR", "Possible Price Errors",
        "Possible pricing mistakes detected by Lotus.", "Premium", "⚠️"
    ),
    AlertPreferenceDefinition(
        "INTERNATIONAL", "International Alerts",
        "Eligible overseas retailer and exclusive-product alerts.", "Premium", "🌎"
    ),
    AlertPreferenceDefinition(
        "INVENTORY_FLICKER", "Inventory Flicker",
        "Rapid micro-restock / stock-transition alerts.", "Premium+", "⚡"
    ),
    AlertPreferenceDefinition(
        "RELEASE_RADAR", "Release Radar",
        "Release-date and release-intelligence alerts.", "Premium+", "📅"
    ),
    AlertPreferenceDefinition(
        "POKEMON_QUEUE", "Pokémon Center Queue",
        "Pokémon Center queue activity alerts.", "Premium+", "🚪"
    ),
)

DEFINITION_BY_KEY = {item.key: item for item in ALERT_PREFERENCE_DEFINITIONS}

_SCHEMA_LOCK = asyncio.Lock()
_SCHEMA_READY = False


async def ensure_alert_preference_schema() -> None:
    """Create the preference table/index if they do not exist."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        async with SessionLocal() as session:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS user_alert_preferences (
                    id BIGSERIAL PRIMARY KEY,
                    discord_user_id BIGINT NOT NULL,
                    game VARCHAR(150) NOT NULL,
                    alert_type VARCHAR(100) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_user_alert_preference
                        UNIQUE (discord_user_id, game, alert_type)
                )
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_user_alert_preferences_user_game
                ON user_alert_preferences (discord_user_id, game)
            """))
            await session.commit()
        _SCHEMA_READY = True


def get_available_alert_definitions(tier: str | None) -> list[AlertPreferenceDefinition]:
    return [
        item for item in ALERT_PREFERENCE_DEFINITIONS
        if tier_allows_preference(tier, item.minimum_tier)
    ]


def get_available_alert_keys(tier: str | None) -> set[str]:
    return {item.key for item in get_available_alert_definitions(tier)}


async def get_alert_preferences(discord_user_id: int, game: str) -> dict[str, bool]:
    """Return every known key. Missing rows default True for compatibility."""
    await ensure_alert_preference_schema()
    values = {item.key: True for item in ALERT_PREFERENCE_DEFINITIONS}
    async with SessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT alert_type, enabled
                FROM user_alert_preferences
                WHERE discord_user_id = :discord_user_id
                  AND game = :game
            """),
            {"discord_user_id": int(discord_user_id), "game": str(game)},
        )
        for row in result.mappings().all():
            key = str(row["alert_type"] or "").upper()
            if key in DEFINITION_BY_KEY:
                values[key] = bool(row["enabled"])
    return values


async def save_alert_preferences_for_tier(
    *, discord_user_id: int, game: str, selected_keys: Iterable[str], tier: str | None,
) -> dict[str, bool]:
    """Update only keys currently visible/allowed for the member's tier."""
    await ensure_alert_preference_schema()
    allowed = get_available_alert_keys(tier)
    selected = {str(value).upper() for value in selected_keys if str(value).upper() in allowed}
    async with SessionLocal() as session:
        for key in sorted(allowed):
            await session.execute(
                text("""
                    INSERT INTO user_alert_preferences
                        (discord_user_id, game, alert_type, enabled, created_at, updated_at)
                    VALUES
                        (:discord_user_id, :game, :alert_type, :enabled,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (discord_user_id, game, alert_type)
                    DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "discord_user_id": int(discord_user_id),
                    "game": str(game),
                    "alert_type": key,
                    "enabled": key in selected,
                },
            )
        await session.commit()
    return await get_alert_preferences(discord_user_id, game)


def preference_keys_for_event(
    event_type: str | None,
    alert_route: str | None,
    region: str | None = None,
) -> list[str]:
    event = str(event_type or "").strip().upper()
    route = str(alert_route or "").strip().lower()
    keys: list[str] = []

    # Route-wide controls combine with event controls. International products
    # require the INTERNATIONAL switch even when a more-specific Premium+
    # route (for example Inventory Flicker) is used.
    region_value = str(region or "").strip().upper()
    is_international = bool(
        region_value
        and region_value not in {"US", "USA", "UNITED STATES"}
    )
    if route == "international" or is_international:
        keys.append("INTERNATIONAL")
    if route == "inventory_flicker":
        if "INVENTORY_FLICKER" not in keys:
            keys.append("INVENTORY_FLICKER")
        return keys
    if route == "release_radar":
        if "RELEASE_RADAR" not in keys:
            keys.append("RELEASE_RADAR")
        return keys
    if route == "pokemon_queue":
        if "POKEMON_QUEUE" not in keys:
            keys.append("POKEMON_QUEUE")
        return keys

    event_map = {
        "DISCOVERED": "NEW_PRODUCT",
        "PAGE_LIVE": "PAGE_LIVE",
        "COMING_SOON": "PAGE_LIVE",
        "PREORDER_LIVE": "PREORDER",
        "STOCK_AVAILABLE": "STOCK_AVAILABLE",
        "RESTOCK": "RESTOCK",
        "SOLD_OUT": "SOLD_OUT",
        "PRICE_DROP": "PRICE_DROP",
        "PRICE_INCREASE": "PRICE_INCREASE",
        "PRICE_ERROR": "PRICE_ERROR",
        "INVENTORY_FLICKER": "INVENTORY_FLICKER",
        "RELEASE_DATE_CHANGED": "RELEASE_RADAR",
        "QUEUE_DETECTED": "POKEMON_QUEUE",
        "QUEUE_ACTIVE": "POKEMON_QUEUE",
        "QUEUE_CLEARED": "POKEMON_QUEUE",
    }
    event_key = event_map.get(event)
    if event_key and event_key not in keys:
        keys.append(event_key)
    return keys


async def member_allows_alert(
    *, discord_user_id: int, game: str, event_type: str | None,
    alert_route: str | None, tier: str | None, region: str | None = None,
) -> bool:
    """Backend enforcement: entitlement AND saved preference must pass."""
    keys = preference_keys_for_event(event_type, alert_route, region)
    if not keys:
        # Unknown future event types are allowed only by route entitlement in
        # worker.py until they receive an explicit preference definition.
        return True
    preferences = await get_alert_preferences(discord_user_id, game)
    for key in keys:
        definition = DEFINITION_BY_KEY.get(key)
        if definition is None:
            continue
        if not tier_allows_preference(tier, definition.minimum_tier):
            return False
        if not bool(preferences.get(key, True)):
            return False
    return True
