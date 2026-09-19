"""Source-backed, guild-scoped release records. No HTTP, Redis, or alert writes.

The first version creates only its three new tables, idempotently. It does not
modify the bot's existing Product table or Alembic revision chain. Later schema
changes require an explicit migration; create_all is NOT an upgrade mechanism.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func, select, text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

STATUSES = ("RUMORED", "CONFIRMED", "ARCHIVED")
SOURCE_KINDS = ("COMMUNITY", "RETAILER", "DISTRIBUTOR", "PUBLISHER")
FORMATS = ("UNKNOWN", "PACK", "BOX", "CASE", "SET", "DECK", "ACCESSORY")
UNKNOWN = "UNKNOWN"
PAGE_SIZE = 10


class CatalogError(ValueError):
    """Safe, actionable input/state error that may be shown to an administrator."""


class ReleaseBase(DeclarativeBase):
    pass


class Release(ReleaseBase):
    __tablename__ = "lotus_release_catalog"
    __table_args__ = (
        UniqueConstraint("guild_id", "identity_key", name="uq_lotus_release_identity"),
        CheckConstraint("status IN ('RUMORED','CONFIRMED','ARCHIVED')", name="ck_lotus_release_status"),
        Index("ix_lotus_release_calendar", "guild_id", "status", "release_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    identity_key: Mapped[str] = mapped_column(String(64))
    game: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(180))
    set_code: Mapped[str | None] = mapped_column(String(40))
    region: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(40))
    product_format: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16))
    reported_details: Mapped[str] = mapped_column(Text)
    reported_cards_per_pack: Mapped[int | None] = mapped_column(Integer)
    reported_packs_per_box: Mapped[int | None] = mapped_column(Integer)
    reported_boxes_per_case: Mapped[int | None] = mapped_column(Integer)
    reported_all_foil: Mapped[bool | None] = mapped_column(Boolean)
    release_date: Mapped[date | None] = mapped_column(Date)
    # Intentionally no circular FK. Every assignment verifies source ownership
    # within the same locked release transaction. There are no delete commands.
    confirmed_source_id: Mapped[int | None] = mapped_column(Integer)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReleaseSource(ReleaseBase):
    __tablename__ = "lotus_release_sources"
    __table_args__ = (
        UniqueConstraint("release_id", "fingerprint", name="uq_lotus_release_source"),
        CheckConstraint("kind IN ('COMMUNITY','RETAILER','DISTRIBUTOR','PUBLISHER')", name="ck_lotus_source_kind"),
        Index("ix_lotus_release_source_parent", "release_id", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("lotus_release_catalog.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(180))
    url: Mapped[str | None] = mapped_column(String(1500))
    note: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    recorded_by: Mapped[int] = mapped_column(BigInteger)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReleaseAudit(ReleaseBase):
    __tablename__ = "lotus_release_audit"
    __table_args__ = (Index("ix_lotus_release_audit_parent", "release_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("lotus_release_catalog.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[int] = mapped_column(BigInteger)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details_json: Mapped[str] = mapped_column(Text)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clean(value: str, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CatalogError(f"{label} must be text.")
    value = unicodedata.normalize("NFKC", value).strip()
    if (not value and not empty) or len(value) > maximum:
        raise CatalogError(f"{label} must be {'0' if empty else '1'}–{maximum} characters.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise CatalogError(f"{label} contains unsupported control characters.")
    return value


def positive_id(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise CatalogError(f"{label} must be a positive ID.")
    return value


def quantity(value: int | None, label: str) -> int | None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10000):
        raise CatalogError(f"{label} must be 1–10000, or omitted when unknown.")
    return value


def choice(value: str, values: tuple[str, ...], label: str) -> str:
    value = clean(value, label, 30).upper()
    if value not in values:
        raise CatalogError(f"{label} must be one of: {', '.join(values)}.")
    return value


def public_source_url(value: str | None, *, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            raise CatalogError("This source type requires a public HTTPS source URL.")
        return None
    value = clean(value, "Source URL", 1500)
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError:
        raise CatalogError("Source URL is invalid.") from None
    if (
        parsed.scheme != "https" or not host or parsed.username is not None
        or parsed.password is not None or any(c.isspace() for c in value)
        or any(c in value for c in "<>\\")
        or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))
        or (port is not None and port != 443)
    ):
        raise CatalogError("Use a public HTTPS source URL without credentials or a custom port.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise CatalogError("Source URL must use a public hostname (ASCII/punycode).") from None
    else:
        if not address.is_global:
            raise CatalogError("Source URL cannot point to a private or local address.")
    # Manual evidence is saved only. The opt-in source worker separately uses
    # DNS and redirect checks before requesting public source URLs.
    return value


def exact_date(value: str | None) -> date | None:
    if not value:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CatalogError("Use an exact YYYY-MM-DD date, or omit it if unknown. Do not guess a day.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CatalogError("Release date is not a valid calendar date.") from None


def digest(*parts: object) -> str:
    data = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def identity(game: str, title: str, region: str, language: str, product_format: str) -> str:
    return digest(*(" ".join(v.casefold().split()) for v in (game, title, region, language, product_format)))


def snapshot(row) -> dict:
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, datetime):
            value = (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        result[column.name] = value
    return result


class ReleaseCatalog:
    def __init__(self, engine: AsyncEngine | None):
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False) if engine is not None else None
        self._schema_lock = asyncio.Lock()
        self._schema_ready = False

    async def ensure_schema(self) -> None:
        if self.engine is None:
            raise CatalogError("Release catalog unavailable: the bot has no configured database.")
        if self._schema_ready:
            return
        async with self._schema_lock:
            if not self._schema_ready:
                async with self.engine.begin() as connection:
                    if connection.dialect.name == "postgresql":
                        # Transaction-scoped: released on success OR rollback.
                        await connection.execute(text("SELECT pg_advisory_xact_lock(1280460100)"))
                    await connection.run_sync(ReleaseBase.metadata.create_all)
                self._schema_ready = True

    @staticmethod
    async def _release(session, guild_id: int, release_id: int, *, lock: bool = False) -> Release:
        positive_id(guild_id, "Server ID")
        positive_id(release_id, "Release ID")
        query = select(Release).where(Release.guild_id == guild_id, Release.id == release_id)
        if lock:
            query = query.with_for_update()
        row = await session.scalar(query)
        if row is None:
            raise CatalogError("Release not found in this server.")
        return row

    @staticmethod
    def _audit(session, row: Release, actor_id: int, action: str, details: dict) -> None:
        positive_id(actor_id, "Administrator ID")
        session.add(ReleaseAudit(
            release_id=row.id, actor_id=actor_id, action=action,
            recorded_at=utcnow(), details_json=json.dumps(details, ensure_ascii=False, sort_keys=True),
        ))

    @staticmethod
    def _source(row: Release, actor_id: int, kind: str, label: str, url: str | None, note: str) -> ReleaseSource:
        return ReleaseSource(
            release_id=row.id, kind=kind, label=label, url=url, note=note,
            fingerprint=digest(kind, label, url, note), recorded_by=actor_id, recorded_at=utcnow(),
        )

    async def add(
        self, guild_id: int, actor_id: int, *, game: str, title: str, details: str,
        source_label: str = "Forwarded community message; original source unknown",
        source_url: str | None = None, set_code: str | None = None,
        region: str = UNKNOWN, language: str = UNKNOWN, product_format: str = "UNKNOWN",
        cards_per_pack: int | None = None, packs_per_box: int | None = None,
        boxes_per_case: int | None = None, all_foil: bool | None = None,
    ) -> dict:
        positive_id(guild_id, "Server ID")
        positive_id(actor_id, "Administrator ID")
        game, title = clean(game, "Game", 80), clean(title, "Title", 180)
        details = clean(details, "Reported details", 4000)
        label = clean(source_label, "Source label", 180)
        url = public_source_url(source_url, required=False)
        region, language = clean(region, "Region", 40), clean(language, "Language", 40)
        region = UNKNOWN if region.casefold() == "unknown" else region
        language = UNKNOWN if language.casefold() == "unknown" else language
        product_format = choice(product_format, FORMATS, "Format")
        set_code = clean(set_code, "Reported set code", 40) if set_code else None
        cards_per_pack = quantity(cards_per_pack, "Cards per pack")
        packs_per_box = quantity(packs_per_box, "Packs per box")
        boxes_per_case = quantity(boxes_per_case, "Boxes per case")
        if all_foil is not None and not isinstance(all_foil, bool):
            raise CatalogError("All-foil must be true, false, or omitted if unknown.")
        key = identity(game, title, region, language, product_format)
        await self.ensure_schema()
        async with self.sessions() as session:
            try:
                async with session.begin():
                    existing = await session.scalar(select(Release).where(Release.guild_id == guild_id, Release.identity_key == key))
                    if existing is not None:
                        return {"created": False, "release": snapshot(existing)}
                    now = utcnow()
                    row = Release(
                        guild_id=guild_id, identity_key=key, game=game, title=title,
                        region=region, language=language, product_format=product_format,
                        set_code=set_code, status="RUMORED", reported_details=details,
                        reported_cards_per_pack=cards_per_pack, reported_packs_per_box=packs_per_box,
                        reported_boxes_per_case=boxes_per_case, reported_all_foil=all_foil,
                        created_by=actor_id, created_at=now, updated_at=now,
                    )
                    session.add(row)
                    await session.flush()
                    source = self._source(row, actor_id, "COMMUNITY", label, url, details)
                    session.add(source)
                    await session.flush()
                    self._audit(session, row, actor_id, "CREATED", {"source_id": source.id, "status": "RUMORED"})
                    result = {"created": True, "release": snapshot(row), "source_id": source.id}
                return result
            except IntegrityError:
                # A concurrent retry may have committed the same identity first.
                await session.rollback()
                existing = await session.scalar(select(Release).where(Release.guild_id == guild_id, Release.identity_key == key))
                if existing is None:
                    raise
                return {"created": False, "release": snapshot(existing)}

    async def add_source(self, guild_id: int, actor_id: int, release_id: int, *, kind: str, label: str, note: str, url: str | None = None) -> dict:
        positive_id(actor_id, "Administrator ID")
        kind = choice(kind, SOURCE_KINDS, "Source type")
        label, note = clean(label, "Source label", 180), clean(note, "Source note", 4000)
        url = public_source_url(url, required=kind != "COMMUNITY")
        await self.ensure_schema()
        async with self.sessions() as session, session.begin():
            row = await self._release(session, guild_id, release_id, lock=True)
            source = self._source(row, actor_id, kind, label, url, note)
            existing = await session.scalar(select(ReleaseSource).where(ReleaseSource.release_id == row.id, ReleaseSource.fingerprint == source.fingerprint))
            if existing is not None:
                return {"created": False, "source": snapshot(existing)}
            session.add(source)
            await session.flush()
            row.updated_at = utcnow()
            self._audit(session, row, actor_id, "SOURCE_ADDED", {"source_id": source.id, "kind": kind})
            return {"created": True, "source": snapshot(source)}

    async def get(self, guild_id: int, release_id: int) -> dict:
        await self.ensure_schema()
        async with self.sessions() as session:
            row = await self._release(session, guild_id, release_id)
            sources = (await session.scalars(select(ReleaseSource).where(ReleaseSource.release_id == row.id).order_by(ReleaseSource.id.desc()).limit(5))).all()
            audits = (await session.scalars(select(ReleaseAudit).where(ReleaseAudit.release_id == row.id).order_by(ReleaseAudit.id.desc()).limit(5))).all()
            result = snapshot(row)
            confirmation = await session.scalar(select(ReleaseAudit).where(ReleaseAudit.release_id == row.id, ReleaseAudit.action.in_(("CONFIRMED", "AUTO_CONFIRMED", "RETRACTED", "ARCHIVED"))).order_by(ReleaseAudit.id.desc()).limit(1))
            result["confirmation_mode"] = "AUTOMATIC_SOURCE_POLICY" if confirmation and confirmation.action == "AUTO_CONFIRMED" and row.status == "CONFIRMED" else "MANUAL"
            return {"release": result, "sources": [snapshot(s) for s in sources], "audit": [snapshot(a) for a in audits]}

    async def sources(self, guild_id: int, release_id: int, page: int = 1) -> dict:
        self._page(page)
        await self.ensure_schema()
        async with self.sessions() as session:
            await self._release(session, guild_id, release_id)
            query = select(ReleaseSource).where(ReleaseSource.release_id == release_id).order_by(ReleaseSource.id.desc())
            rows = (await session.scalars(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1))).all()
            return {"items": [snapshot(row) for row in rows[:PAGE_SIZE]], "page": page, "has_more": len(rows) > PAGE_SIZE}

    async def evidence(self, guild_id: int, release_id: int, source_id: int) -> dict:
        positive_id(source_id, "Source ID")
        await self.ensure_schema()
        async with self.sessions() as session:
            await self._release(session, guild_id, release_id)
            source = await session.scalar(select(ReleaseSource).where(ReleaseSource.id == source_id, ReleaseSource.release_id == release_id))
            if source is None:
                raise CatalogError("Source not found on this release.")
            return snapshot(source)

    async def history(self, guild_id: int, release_id: int, page: int = 1) -> dict:
        self._page(page)
        await self.ensure_schema()
        async with self.sessions() as session:
            await self._release(session, guild_id, release_id)
            query = select(ReleaseAudit).where(ReleaseAudit.release_id == release_id).order_by(ReleaseAudit.id.desc())
            rows = (await session.scalars(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1))).all()
            return {"items": [snapshot(row) for row in rows[:PAGE_SIZE]], "page": page, "has_more": len(rows) > PAGE_SIZE}

    async def confirm(
        self, guild_id: int, actor_id: int, release_id: int, *, source_id: int,
        reviewed: bool, review_note: str, release_date: str | None = None,
        title: str | None = None, region: str | None = None, language: str | None = None,
        set_code: str | None = None,
    ) -> dict:
        positive_id(actor_id, "Administrator ID")
        positive_id(source_id, "Source ID")
        if reviewed is not True:
            raise CatalogError("Read the source and set reviewed:True to attest that it supports this release and date/scope.")
        note, when = clean(review_note, "Review note", 1500), exact_date(release_date)
        await self.ensure_schema()
        try:
            async with self.sessions() as session, session.begin():
                row = await self._release(session, guild_id, release_id, lock=True)
                if row.status == "ARCHIVED":
                    raise CatalogError("This release is archived. Use /release retract to restore it to unverified first.")
                source = await session.scalar(select(ReleaseSource).where(ReleaseSource.id == source_id, ReleaseSource.release_id == row.id))
                if source is None or source.kind not in ("PUBLISHER", "DISTRIBUTOR"):
                    raise CatalogError("Confirmation requires a publisher/distributor source attached to this release. Community/retailer claims cannot confirm it.")
                public_source_url(source.url, required=True)
                old = snapshot(row)
                for field, value, maximum in (("title", title, 180), ("region", region, 40), ("language", language, 40), ("set_code", set_code, 40)):
                    if value is not None:
                        setattr(row, field, clean(value, field.replace("_", " ").title(), maximum))
                if when and any(value.casefold() in ("unknown", "tbd", "tba", "unspecified", "?") for value in (row.region, row.language)):
                    raise CatalogError("A dated release needs a known region and language. Specify both from the source, or omit the date.")
                row.identity_key = identity(row.game, row.title, row.region, row.language, row.product_format)
                row.status, row.release_date = "CONFIRMED", when
                row.confirmed_source_id, row.confirmed_by = source.id, actor_id
                row.confirmed_at = row.updated_at = utcnow()
                await session.flush()
                self._audit(session, row, actor_id, "CONFIRMED", {
                    "before": old, "after": snapshot(row), "source_id": source.id,
                    "review_note": note, "scope": "release identity/date only; reported packaging remains unverified",
                })
                return snapshot(row)
        except IntegrityError:
            raise CatalogError("That title/game/region/language/format already has a release record. No changes were saved.") from None

    async def change_status(self, guild_id: int, actor_id: int, release_id: int, *, status: str, reason: str) -> dict:
        positive_id(actor_id, "Administrator ID")
        status = choice(status, ("RUMORED", "ARCHIVED"), "New status")
        reason = clean(reason, "Reason", 1500)
        await self.ensure_schema()
        async with self.sessions() as session, session.begin():
            row = await self._release(session, guild_id, release_id, lock=True)
            old = snapshot(row)
            row.status, row.release_date = status, None
            row.confirmed_source_id = row.confirmed_by = row.confirmed_at = None
            row.updated_at = utcnow()
            self._audit(session, row, actor_id, "ARCHIVED" if status == "ARCHIVED" else "RETRACTED", {"before": old, "reason": reason})
            return snapshot(row)

    @staticmethod
    def _page(page: int) -> None:
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 10000:
            raise CatalogError("Page must be 1–10000.")

    async def list_releases(self, guild_id: int, *, status: str = "ALL", game: str | None = None, page: int = 1) -> dict:
        positive_id(guild_id, "Server ID")
        self._page(page)
        status = choice(status, STATUSES + ("ALL",), "Status")
        await self.ensure_schema()
        query = select(Release).where(Release.guild_id == guild_id)
        if status != "ALL":
            query = query.where(Release.status == status)
        if game:
            query = query.where(func.lower(Release.game) == clean(game, "Game", 80).lower())
        query = query.order_by(Release.updated_at.desc(), Release.id.desc())
        async with self.sessions() as session:
            rows = (await session.scalars(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1))).all()
            return {"items": [snapshot(row) for row in rows[:PAGE_SIZE]], "page": page, "has_more": len(rows) > PAGE_SIZE}

    async def calendar(self, guild_id: int, *, start: str | None = None, days: int = 90, game: str | None = None, region: str | None = None, language: str | None = None, page: int = 1) -> dict:
        positive_id(guild_id, "Server ID")
        self._page(page)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 730:
            raise CatalogError("Calendar range must be 1–730 days.")
        first = exact_date(start) or utcnow().date()
        try:
            last = first + timedelta(days=days - 1)
        except OverflowError:
            raise CatalogError("Calendar range exceeds the supported dates.") from None
        await self.ensure_schema()
        query = select(Release).where(Release.guild_id == guild_id, Release.status == "CONFIRMED", Release.release_date.between(first, last))
        for column, value in ((Release.game, game), (Release.region, region), (Release.language, language)):
            if value:
                query = query.where(func.lower(column) == clean(value, "Filter", 80).lower())
        query = query.order_by(Release.release_date, Release.id)
        async with self.sessions() as session:
            rows = (await session.scalars(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1))).all()
            return {"items": [snapshot(row) for row in rows[:PAGE_SIZE]], "page": page, "has_more": len(rows) > PAGE_SIZE, "start": first.isoformat(), "end": last.isoformat()}

    async def stats(self, guild_id: int) -> dict:
        positive_id(guild_id, "Server ID")
        await self.ensure_schema()
        async with self.sessions() as session:
            rows = (await session.execute(select(Release.status, func.count()).where(Release.guild_id == guild_id).group_by(Release.status))).all()
            return {status: dict(rows).get(status, 0) for status in STATUSES}
