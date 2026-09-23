"""Source watches, immutable extracted evidence, safe catalog links and review."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import timedelta, timezone

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, func, or_, select, text, update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import async_sessionmaker

from .extraction import (
    Candidate, CODE, canonical_url, code, languages, norm,
    product_format, same_site, scope, url_key,
)
from .service import (
    CatalogError, Release, ReleaseAudit, ReleaseSource, clean, digest,
    exact_date, identity, positive_id, snapshot, utcnow,
)


class Base(DeclarativeBase):
    pass


class Watch(Base):
    __tablename__ = "lotus_release_watches"
    __table_args__ = (
        UniqueConstraint("guild_id", "url_key", name="uq_lotus_watch_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    url: Mapped[str] = mapped_column(Text)
    url_key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(20))
    scope_json: Mapped[str] = mapped_column(Text)
    auto_confirm: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    next_due: Mapped[object] = mapped_column(
        DateTime(timezone=True), index=True
    )
    lease: Mapped[str | None] = mapped_column(String(32))
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    cursor_json: Mapped[str] = mapped_column(Text, default="{}")
    last_json: Mapped[str] = mapped_column(Text, default="{}")
    failures: Mapped[int] = mapped_column(Integer, default=0)


class WatchAudit(Base):
    __tablename__ = "lotus_release_watch_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int] = mapped_column(
        ForeignKey("lotus_release_watches.id"), index=True
    )
    actor_id: Mapped[int] = mapped_column(BigInteger)
    recorded_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    details_json: Mapped[str] = mapped_column(Text)


class Item(Base):
    __tablename__ = "lotus_release_ingestion_items"
    __table_args__ = (
        UniqueConstraint(
            "watch_id", "url_key", name="uq_lotus_ingested_url"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int] = mapped_column(
        ForeignKey("lotus_release_watches.id"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    url_key: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    identity_json: Mapped[str] = mapped_column(Text, default="{}")
    pending_json: Mapped[str | None] = mapped_column(Text)
    pending_policy: Mapped[int] = mapped_column(Integer, default=0)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    policy_revision: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    issues_json: Mapped[str] = mapped_column(Text, default="[]")
    release_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_id: Mapped[int | None] = mapped_column(Integer)
    forced_id: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_error: Mapped[str | None] = mapped_column(String(100))


class Evidence(Base):
    __tablename__ = "lotus_release_ingestion_evidence"
    __table_args__ = (
        UniqueConstraint(
            "item_id", "fingerprint", name="uq_lotus_ingested_evidence"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("lotus_release_ingestion_items.id"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class RetailerLink(Base):
    __tablename__ = "lotus_release_retailer_links"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "store_product_id",
            name="uq_lotus_retailer_release",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    store_product_id: Mapped[int] = mapped_column(Integer)
    release_id: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    details_json: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[object] = mapped_column(DateTime(timezone=True))


class RetailerCursor(Base):
    __tablename__ = "lotus_release_retailer_cursor"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    after_id: Mapped[int] = mapped_column(Integer, default=0)


def aware(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value and value.tzinfo is None
        else value
    )


def compatible(c, row):
    return (
        norm(c.game) == norm(row.game)
        and (
            c.product_format == "UNKNOWN"
            or row.product_format == "UNKNOWN"
            or c.product_format == row.product_format
        )
        and all(
            scope(getattr(c, key)) == "unknown"
            or scope(getattr(row, key)) == "unknown"
            or scope(getattr(c, key)) == scope(getattr(row, key))
            for key in ("region", "language")
        )
        and not (
            c.set_code
            and code(row.set_code)
            and c.set_code != code(row.set_code)
        )
    )


from .title_identity import title_relation, PACK_NOTE


def match(c, rows, sources, retailer=False):
    ids = {
        source.release_id
        for source in sources
        if source.url and url_key(source.url) == url_key(c.url)
    }

    if ids:
        found = [row for row in rows if row.id in ids]
        if len(found) != 1 or not compatible(c, found[0]):
            return None, "SOURCE_IDENTITY_CONFLICT"
        if not retailer:
            return found[0], None
    else:
        found = []
        for row in rows:
            if not compatible(c, row):
                continue

            codes = {code(m[0]) for m in CODE.finditer(row.title)}
            release_code = code(row.set_code) or (
                next(iter(codes)) if len(codes) == 1 else None
            )
            sku = bool(
                c.sku
                and re.search(
                    rf'(?i)\bSKU["\s]*:\s*["\s]*'
                    rf'{re.escape(c.sku)}(?![A-Z0-9])',
                    row.reported_details,
                )
            )

            if (
                (c.set_code and c.set_code == release_code)
                or norm(c.title) == norm(row.title)
                or (retailer and title_relation(c.title, row.title) is not None)
                or sku
            ):
                found.append(row)

    if len(found) > 1:
        return None, "AMBIGUOUS_RELEASE_MATCH"
    if not found:
        return None, None

    row = found[0]

    # Additional retailer title candidates never erase differing/missing counts,
    # even if another identity signal (code/SKU/source URL) also agrees.
    relation = title_relation(c.title, row.title) if retailer else None
    if relation == 'PACK_COUNT_CONFLICT':
        return None, relation
    if relation == 'PACK_COUNT_REVIEW':
        counts = PACK_NOTE.findall(c.title or '') + PACK_NOTE.findall(row.title or '')
        expected = getattr(row, 'reported_packs_per_box', None)
        supported = False
        # SET bundles use packs_per_box only if the admin explicitly supplies that
        # field; absent or ambiguous evidence never clears the count guard.
        for source in sources:
            if source.release_id != row.id or source.kind not in ('PUBLISHER','DISTRIBUTOR'):
                continue
            try:
                data = json.loads(source.note)
                if isinstance(data, dict) and data.get('catalog_enrichment_v1', {}).get('packs_per_box') == expected and expected is not None:
                    supported = True
            except (ValueError, TypeError, AttributeError):
                continue
        if not counts or not supported or any(int(n) != expected for n in counts):
            return None, 'PACK_COUNT_REVIEW'


    if c.product_format == "UNKNOWN" or row.product_format == "UNKNOWN":
        return None, "FORMAT_REQUIRED_FOR_MATCH"

    for name in ("region", "language"):
        new = scope(getattr(c, name))
        old = scope(getattr(row, name))

        if (
            (new == "unknown" and old != "unknown")
            or (retailer and "unknown" in (new, old))
        ):
            return None, "EDITION_REQUIRED_FOR_MATCH"

    return row, None


class IngestionStore:
    def __init__(self, catalog):
        self.catalog = catalog
        self.engine = catalog.engine
        self.sessions = (
            async_sessionmaker(self.engine, expire_on_commit=False)
            if self.engine is not None
            else None
        )
        self.ready = False
        self.schema_lock = asyncio.Lock()
        self.writes = asyncio.Lock()

    async def ensure_schema(self):
        await self.catalog.ensure_schema()

        async with self.schema_lock:
            if not self.ready:
                async with self.engine.begin() as conn:
                    if conn.dialect.name == "postgresql":
                        await conn.execute(
                            text("SELECT pg_advisory_xact_lock(1280460101)")
                        )
                    await conn.run_sync(Base.metadata.create_all)
                self.ready = True

    async def guild_lock(self, s, guild):
        if self.engine.dialect.name == "postgresql":
            await s.execute(
                text("SELECT pg_advisory_xact_lock(128047, :g)"),
                {"g": guild % 2147483647},
            )

    async def guard(self, s, guild, wid, token=None):
        positive_id(guild, "Server ID")
        positive_id(wid, "Watch ID")

        watch = await s.scalar(
            select(Watch)
            .where(Watch.id == wid, Watch.guild_id == guild)
            .with_for_update()
        )

        if watch is None:
            raise CatalogError("Source watch not found in this server.")

        if token and (
            not watch.enabled
            or watch.lease != token
            or not watch.lease_until
            or aware(watch.lease_until) <= utcnow()
        ):
            raise CatalogError(
                "Source scan lease expired or settings changed."
            )

        return watch

    @staticmethod
    def validate(kind, settings, auto, interval):
        if kind not in ("PUBLISHER", "DISTRIBUTOR", "RETAILER"):
            raise CatalogError(
                "Choose Publisher, Distributor or Retailer."
            )

        if type(interval) is not int or not 15 <= interval <= 10080:
            raise CatalogError("Interval must be 15ā€“10080 minutes.")

        if type(auto) is not bool:
            raise CatalogError(
                "Automatic confirmation must be True or False."
            )

        if auto and (
            kind == "RETAILER"
            or any(
                scope(settings[key]) == "unknown"
                for key in ("region", "language")
            )
        ):
            raise CatalogError(
                "Automatic calendar confirmation requires a "
                "publisher/distributor source with an explicitly "
                "reviewed region and language."
            )

    async def add_watch(
        self,
        guild,
        actor,
        *,
        url,
        kind,
        label,
        game=None,
        region="UNKNOWN",
        language="UNKNOWN",
        auto_confirm=False,
        interval_minutes=60,
    ):
        positive_id(guild, "Server ID")
        positive_id(actor, "Administrator ID")

        url = canonical_url(url)
        kind = clean(kind, "Source kind", 20).upper()
        label = clean(label, "Label", 180)

        settings = {
            "game": clean(game, "Game", 80) if game else None,
            "region": clean(region, "Region", 40),
            "language": clean(language, "Language", 40),
        }

        self.validate(kind, settings, auto_confirm, interval_minutes)
        await self.ensure_schema()

        async with self.writes, self.sessions() as s, s.begin():
            await self.guild_lock(s, guild)

            old = await s.scalar(
                select(Watch).where(
                    Watch.guild_id == guild,
                    Watch.url_key == url_key(url),
                )
            )
            if old:
                return snapshot(old)

            count = await s.scalar(
                select(func.count())
                .select_from(Watch)
                .where(Watch.guild_id == guild)
            )
            if count >= 25:
                raise CatalogError(
                    "This version supports 25 source watches per server."
                )

            watch = Watch(
                guild_id=guild,
                actor_id=actor,
                url=url,
                url_key=url_key(url),
                label=label,
                kind=kind,
                scope_json=json.dumps(settings),
                auto_confirm=auto_confirm,
                interval_minutes=interval_minutes,
                next_due=utcnow(),
            )

            s.add(watch)
            await s.flush()

            s.add(WatchAudit(
                watch_id=watch.id,
                actor_id=actor,
                details_json=json.dumps(snapshot(watch)),
            ))

            return snapshot(watch)

    async def settings(self, guild, actor, wid, **changes):
        positive_id(actor, "Administrator ID")
        await self.ensure_schema()

        async with self.writes, self.sessions() as s, s.begin():
            watch = await self.guard(s, guild, wid)
            old = snapshot(watch)
            settings = json.loads(watch.scope_json)

            for name in ("region", "language"):
                if changes.get(name) is not None:
                    settings[name] = clean(changes[name], name, 40)

            for name in ("enabled", "auto_confirm", "interval_minutes"):
                if changes.get(name) is not None:
                    if (
                        name != "interval_minutes"
                        and type(changes[name]) is not bool
                    ):
                        raise CatalogError(
                            f"{name} must be True or False."
                        )
                    setattr(watch, name, changes[name])

            self.validate(
                watch.kind,
                settings,
                watch.auto_confirm,
                watch.interval_minutes,
            )

            watch.scope_json = json.dumps(settings)
            watch.actor_id = actor
            watch.revision += 1
            watch.lease = watch.lease_until = None

            if json.loads(watch.last_json).get("error") != "RATE_LIMITED":
                watch.next_due = utcnow()

            s.add(WatchAudit(
                watch_id=watch.id,
                actor_id=actor,
                details_json=json.dumps({
                    "before": old,
                    "after": snapshot(watch),
                }),
            ))

            return snapshot(watch)

    async def watches(self, guild):
        positive_id(guild, "Server ID")
        await self.ensure_schema()

        async with self.sessions() as s:
            rows = (
                await s.scalars(
                    select(Watch)
                    .where(Watch.guild_id == guild)
                    .order_by(Watch.id)
                )
            ).all()
            return [snapshot(watch) for watch in rows]

    async def due(self):
        await self.ensure_schema()

        async with self.sessions() as s:
            rows = (
                await s.scalars(
                    select(Watch)
                    .where(
                        Watch.enabled.is_(True),
                        Watch.next_due <= utcnow(),
                        or_(
                            Watch.lease_until.is_(None),
                            Watch.lease_until < utcnow(),
                        ),
                    )
                    .order_by(Watch.next_due)
                    .limit(2)
                )
            ).all()
            return [snapshot(watch) for watch in rows]

    async def active_guilds(self):
        async with self.sessions() as s:
            return list(
                (
                    await s.scalars(
                        select(Watch.guild_id)
                        .where(Watch.enabled.is_(True))
                        .distinct()
                        .order_by(Watch.guild_id)
                    )
                ).all()
            )

    async def claim(self, guild, wid):
        await self.ensure_schema()

        async with self.sessions() as s, s.begin():
            watch = await self.guard(s, guild, wid)
            now = utcnow()

            if not watch.enabled:
                raise CatalogError("Source watch is paused.")

            if (
                json.loads(watch.last_json).get("error") == "RATE_LIMITED"
                and aware(watch.next_due) > now
            ):
                raise CatalogError(
                    "Source rate-limit backoff is active; "
                    "wait until its next scheduled scan."
                )

            token = uuid.uuid4().hex
            result = await s.execute(
                update(Watch)
                .where(
                    Watch.id == wid,
                    or_(
                        Watch.lease_until.is_(None),
                        Watch.lease_until < now,
                    ),
                )
                .values(
                    lease=token,
                    lease_until=now + timedelta(minutes=10),
                )
                .execution_options(synchronize_session=False)
            )

            if not result.rowcount:
                raise CatalogError(
                    "This source already has a scan in progress."
                )

            await s.refresh(watch)
            return snapshot(watch), token

    async def finish(self, w, token, stats, cursor, error):
        async with self.sessions() as s, s.begin():
            row = await s.scalar(
                select(Watch)
                .where(
                    Watch.id == w["id"],
                    Watch.guild_id == w["guild_id"],
                    Watch.lease == token,
                )
                .with_for_update()
            )

            if row is None:
                return

            row.failures = row.failures + 1 if error else 0

            delay = (
                max(
                    row.interval_minutes,
                    min(1440, 15 * 2 ** min(row.failures, 6)),
                )
                if error
                else row.interval_minutes
            )

            if error == "RATE_LIMITED":
                delay = max(delay, 60)

            row.next_due = utcnow() + timedelta(minutes=delay)
            row.lease = row.lease_until = None
            row.last_json = json.dumps({
                "at": utcnow().isoformat(),
                "error": error,
                "stats": stats,
            })
            row.cursor_json = json.dumps(cursor)

    async def queue(self, w, token, urls):
        async with self.writes, self.sessions() as s, s.begin():
            await self.guard(s, w["guild_id"], w["id"], token)

            known = set(
                (
                    await s.scalars(
                        select(Item.url_key).where(
                            Item.watch_id == w["id"]
                        )
                    )
                ).all()
            )
            added = 0

            for url in urls:
                try:
                    url = canonical_url(url)
                except CatalogError:
                    continue

                key = url_key(url)
                if key in known or not same_site(url, w["url"]):
                    continue

                if len(known) >= 10000:
                    raise CatalogError("SOURCE_ITEM_LIMIT")

                s.add(Item(
                    watch_id=w["id"],
                    url=url,
                    url_key=key,
                ))
                known.add(key)
                added += 1

            return added

    async def stage(self, w, token, candidates):
        await self.queue(w, token, [c.url for c in candidates])
        unchanged = 0

        async with self.writes, self.sessions() as s, s.begin():
            watch = await self.guard(
                s, w["guild_id"], w["id"], token
            )

            for candidate in candidates:
                row = await s.scalar(
                    select(Item).where(
                        Item.watch_id == watch.id,
                        Item.url_key == url_key(candidate.url),
                    )
                )

                if row is None:
                    continue

                if (
                    row.fingerprint == candidate.fingerprint()
                    and row.policy_revision == watch.revision
                ):
                    row.checked_at = utcnow()
                    row.last_error = None
                    row.pending_json = None
                    unchanged += 1
                else:
                    row.pending_json = json.dumps(candidate.payload())
                    row.pending_policy = watch.revision

        return unchanged

    async def pending(self, wid, before=None):
        async with self.sessions() as s:
            query = select(Item).where(
                Item.watch_id == wid,
                Item.state != "ALIAS",
            )

            if before:
                query = query.where(
                    or_(
                        Item.pending_json.is_not(None),
                        Item.checked_at.is_(None),
                        Item.checked_at < before,
                    )
                )

            rows = (
                await s.scalars(
                    query.order_by(
                        Item.checked_at.asc().nullsfirst(),
                        Item.id,
                    ).limit(100)
                )
            ).all()

            return [snapshot(item) for item in rows]

    async def fetched(self, w, token, url, error=None, alias=None):
        async with self.sessions() as s, s.begin():
            await self.guard(s, w["guild_id"], w["id"], token)

            item = await s.scalar(
                select(Item).where(
                    Item.watch_id == w["id"],
                    Item.url_key == url_key(url),
                )
            )

            if item:
                item.checked_at = utcnow()
                item.last_error = error

                if (
                    alias
                    and url_key(alias) != item.url_key
                    and item.release_id is None
                ):
                    item.state = "ALIAS"
                    item.payload_json = json.dumps({
                        "canonical_url": alias,
                    })

    async def catalog_rows(self, s, guild):
        rows = list(
            (
                await s.scalars(
                    select(Release)
                    .where(Release.guild_id == guild)
                    .limit(5001)
                )
            ).all()
        )
        sources = list(
            (
                await s.scalars(
                    select(ReleaseSource)
                    .join(Release)
                    .where(Release.guild_id == guild)
                    .limit(50001)
                )
            ).all()
        )

        if len(rows) > 5000 or len(sources) > 50000:
            raise CatalogError("CATALOG_MATCH_LIMIT")

        return rows, sources

    async def apply(self, w, token, c: Candidate):
        await self.queue(w, token, [c.url])

        async with self.writes, self.sessions() as s, s.begin():
            watch = await self.guard(
                s, w["guild_id"], w["id"], token
            )
            await self.guild_lock(s, watch.guild_id)

            item = await s.scalar(
                select(Item)
                .where(
                    Item.watch_id == watch.id,
                    Item.url_key == url_key(c.url),
                )
                .with_for_update()
            )

            if item is None:
                raise CatalogError("CROSS_SITE_PRODUCT")

            item.checked_at = utcnow()
            item.last_error = None
            fingerprint = c.fingerprint()
            item.pending_json = None

            if (
                item.fingerprint == fingerprint
                and item.policy_revision == watch.revision
            ):
                return {
                    "state": "UNCHANGED",
                    "item_id": item.id,
                    "release_id": item.release_id,
                    "issues": json.loads(item.issues_json),
                }

            old = json.loads(item.identity_json)
            rows, sources = await self.catalog_rows(s, watch.guild_id)
            issue = None
            row = None

            if item.forced_id or item.release_id:
                row = next(
                    (
                        release
                        for release in rows
                        if release.id == (
                            item.forced_id or item.release_id
                        )
                    ),
                    None,
                )

                if row is None or not compatible(c, row):
                    row = None
                    issue = "SOURCE_IDENTITY_CONFLICT"

                if old.get("sku") and c.sku and old["sku"] != c.sku:
                    row = None
                    issue = "SOURCE_SKU_CHANGED"

                if (
                    old.get("set_code")
                    and c.set_code
                    and old["set_code"] != c.set_code
                ):
                    row = None
                    issue = "SOURCE_SET_CHANGED"
            else:
                row, issue = match(c, rows, sources)

            if not row and not issue and not c.sku and not c.set_code:
                issue = "PRODUCT_IDENTITY_MISSING"

            item.payload_json = json.dumps(
                c.payload(), ensure_ascii=False
            )
            item.fingerprint = fingerprint
            item.policy_revision = watch.revision

            existing_evidence = await s.scalar(
                select(Evidence.id).where(
                    Evidence.item_id == item.id,
                    Evidence.fingerprint == fingerprint,
                )
            )
            if not existing_evidence:
                s.add(Evidence(
                    item_id=item.id,
                    fingerprint=fingerprint,
                    payload_json=item.payload_json,
                ))

            issues = list(c.issues)

            if issue:
                issues.append(issue)
                item.state = "REVIEW"
                item.issues_json = json.dumps(sorted(set(issues)))

                return {
                    "state": "REVIEW",
                    "item_id": item.id,
                    "release_id": None,
                    "issues": issues,
                }

            created = row is None
            note = (
                "Automatic public-source extraction.\n"
                + json.dumps(
                    {
                        key: value
                        for key, value in c.payload().items()
                        if key != "evidence"
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + c.evidence[:1300]
            )[:4000]

            if created:
                row = Release(
                    guild_id=watch.guild_id,
                    identity_key=identity(
                        c.game,
                        c.title,
                        c.region,
                        c.language,
                        c.product_format,
                    ),
                    game=c.game,
                    title=c.title,
                    set_code=c.set_code,
                    region=c.region,
                    language=c.language,
                    product_format=c.product_format,
                    status="RUMORED",
                    reported_details=note,
                    reported_cards_per_pack=c.cards_per_pack,
                    reported_packs_per_box=c.packs_per_box,
                    reported_boxes_per_case=c.boxes_per_case,
                    reported_all_foil=c.all_foil,
                    created_by=watch.actor_id,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                s.add(row)
                await s.flush()
            else:
                row = await self.catalog._release(
                    s, watch.guild_id, row.id, lock=True
                )
                await s.refresh(row)

                if not compatible(c, row):
                    raise CatalogError(
                        "Release changed during matching; retry the scan."
                    )

            source = self.catalog._source(
                row,
                watch.actor_id,
                watch.kind,
                "Automatic: " + watch.label[:169],
                c.url,
                note,
            )

            existing = await s.scalar(
                select(ReleaseSource).where(
                    ReleaseSource.release_id == row.id,
                    ReleaseSource.fingerprint == source.fingerprint,
                )
            )

            if existing:
                source = existing
            else:
                s.add(source)
                await s.flush()

            item.release_id = row.id
            item.source_id = source.id
            item.state = "CREATED" if created else "LINKED"

            if not old:
                item.identity_json = json.dumps({
                    "sku": c.sku,
                    "set_code": c.set_code,
                })

            for field, reported in (
                ("cards_per_pack", "reported_cards_per_pack"),
                ("packs_per_box", "reported_packs_per_box"),
                ("boxes_per_case", "reported_boxes_per_case"),
            ):
                if (
                    getattr(c, field) is not None
                    and getattr(row, reported) is not None
                    and getattr(c, field) != getattr(row, reported)
                ):
                    issues.append("CATALOG_PACKAGING_CONFLICT")

            if watch.auto_confirm and row.status != "ARCHIVED":
                last = await s.scalar(
                    select(ReleaseAudit)
                    .where(
                        ReleaseAudit.release_id == row.id,
                        ReleaseAudit.action.in_((
                            "CONFIRMED",
                            "AUTO_CONFIRMED",
                            "RETRACTED",
                            "ARCHIVED",
                        )),
                    )
                    .order_by(ReleaseAudit.id.desc())
                    .limit(1)
                )

                owned = (
                    last
                    and last.action == "AUTO_CONFIRMED"
                    and json.loads(last.details_json).get("watch_id")
                    == watch.id
                )

                if last and last.action == "RETRACTED":
                    issues.append("MANUAL_RETRACTION_PRESERVED")

                if not c.release_date:
                    issues.append("RELEASE_DATE_MISSING")

                if c.product_format == "UNKNOWN":
                    issues.append("PRODUCT_FORMAT_MISSING")

                if any(
                    scope(getattr(c, key)) == "unknown"
                    for key in ("region", "language")
                ):
                    issues.append("RELEASE_SCOPE_MISSING")

                preserve = row.status == "CONFIRMED" and not owned

                if (
                    preserve
                    and row.release_date != exact_date(c.release_date)
                ):
                    issues.append("CONFIRMED_DATE_CONFLICT")

                new_key = identity(
                    row.game,
                    row.title,
                    c.region,
                    c.language,
                    row.product_format,
                )

                duplicate = await s.scalar(
                    select(Release.id).where(
                        Release.guild_id == watch.guild_id,
                        Release.identity_key == new_key,
                        Release.id != row.id,
                    )
                )
                if duplicate:
                    issues.append("CONFIRMED_IDENTITY_CONFLICT")

                if not issues and not preserve:
                    before = snapshot(row)
                    row.status = "CONFIRMED"
                    row.release_date = exact_date(c.release_date)
                    row.region = c.region
                    row.language = c.language
                    row.identity_key = new_key
                    row.confirmed_source_id = source.id
                    row.confirmed_by = watch.actor_id
                    row.confirmed_at = row.updated_at = utcnow()

                    self.catalog._audit(
                        s,
                        row,
                        watch.actor_id,
                        "AUTO_CONFIRMED",
                        {
                            "before": before,
                            "after": snapshot(row),
                            "watch_id": watch.id,
                            "policy_revision": watch.revision,
                            "source_id": source.id,
                            "review_note": (
                                "Automatic source-policy confirmation; "
                                "no per-item human attestation."
                            ),
                        },
                    )

            item.issues_json = json.dumps(sorted(set(issues)))

            self.catalog._audit(
                s,
                row,
                watch.actor_id,
                "AUTO_INGESTED",
                {
                    "watch_id": watch.id,
                    "item_id": item.id,
                    "source_id": source.id,
                    "issues": issues,
                },
            )

            return {
                "state": item.state,
                "release_id": row.id,
                "item_id": item.id,
                "issues": issues,
            }

    async def items(self, guild, page=1, review=False):
        positive_id(guild, "Server ID")
        self.catalog._page(page)
        await self.ensure_schema()

        async with self.sessions() as s:
            query = (
                select(Item)
                .join(Watch)
                .where(Watch.guild_id == guild)
            )

            if review:
                query = query.where(Item.issues_json != "[]")

            rows = (
                await s.scalars(
                    query.order_by(Item.id.desc())
                    .offset((page - 1) * 10)
                    .limit(11)
                )
            ).all()

            return {
                "items": [snapshot(row) for row in rows[:10]],
                "page": page,
                "has_more": len(rows) > 10,
            }

    async def item(self, guild, iid):
        positive_id(guild, "Server ID")
        positive_id(iid, "Item ID")
        await self.ensure_schema()

        async with self.sessions() as s:
            item = await s.scalar(
                select(Item)
                .join(Watch)
                .where(
                    Watch.guild_id == guild,
                    Item.id == iid,
                )
            )

            if item is None:
                raise CatalogError("Item not found in this server.")

            return snapshot(item)

    async def link(self, guild, actor, iid, rid):
        positive_id(actor, "Administrator ID")
        await self.ensure_schema()

        async with self.writes, self.sessions() as s, s.begin():
            item = await s.scalar(
                select(Item)
                .join(Watch)
                .where(
                    Watch.guild_id == guild,
                    Item.id == iid,
                )
            )

            if (
                item is None
                or item.state == "ALIAS"
                or not json.loads(item.payload_json)
            ):
                raise CatalogError(
                    "No parsed item with that ID in this server."
                )

            watch = await self.guard(s, guild, item.watch_id)
            await self.guild_lock(s, guild)
            await s.refresh(item, with_for_update=True)

            row = await self.catalog._release(
                s, guild, rid, lock=True
            )
            current = Candidate(**json.loads(item.payload_json))

            if not compatible(current, row):
                raise CatalogError(
                    "Known game, format or edition conflicts "
                    "with this release."
                )

            item.forced_id = rid
            item.policy_revision = 0
            item.identity_json = json.dumps({
                "sku": current.sku,
                "set_code": current.set_code,
            })

            if json.loads(watch.last_json).get("error") != "RATE_LIMITED":
                watch.next_due = utcnow()

            self.catalog._audit(
                s,
                row,
                actor,
                "INGESTION_LINK_APPROVED",
                {
                    "item_id": iid,
                    "watch_id": watch.id,
                },
            )

            return {
                "item_id": iid,
                "release_id": rid,
                "watch_id": watch.id,
            }

    async def match_retailers(self, guild):
        from app.models import Product, Store, StoreProduct

        await self.ensure_schema()

        async with self.writes, self.sessions() as s, s.begin():
            await self.guild_lock(s, guild)
            cursor = await s.get(RetailerCursor, guild)

            if not cursor:
                cursor = RetailerCursor(
                    guild_id=guild,
                    after_id=0,
                )
                s.add(cursor)

            releases, sources = await self.catalog_rows(s, guild)

            rows = (
                await s.execute(
                    select(StoreProduct, Product, Store)
                    .join(
                        Product,
                        Product.id == StoreProduct.product_id,
                    )
                    .join(
                        Store,
                        Store.id == StoreProduct.store_id,
                    )
                    .where(
                        Store.active.is_(True),
                        StoreProduct.id > cursor.after_id,
                    )
                    .order_by(StoreProduct.id)
                    .limit(200)
                )
            ).all()

            stats = {
                "checked": len(rows),
                "matched": 0,
                "review": 0,
            }

            for offer, product, shop in rows:
                codes = {
                    code(match[0])
                    for match in CODE.finditer(product.name)
                }
                langs = languages(product.name)
                fmt = product_format(product.name)
                typed = product_format(product.product_type or "")

                try:
                    url = canonical_url(offer.url)
                except CatalogError:
                    continue

                candidate = Candidate(
                    url,
                    product.name,
                    product.game,
                    sku=offer.sku,
                    set_code=(
                        next(iter(codes))
                        if len(codes) == 1
                        else None
                    ),
                    product_format=(
                        fmt if fmt != "UNKNOWN" else typed
                    ),
                    region=(
                        product.region or shop.region or "UNKNOWN"
                    ),
                    language=(
                        product.language
                        or (
                            next(iter(langs))
                            if len(langs) == 1
                            else "UNKNOWN"
                        )
                    ),
                )

                row, issue = match(
                    candidate, releases, sources, True
                )

                if len(codes) > 1 or len(langs) > 1:
                    row = None
                    issue = "MULTIPLE_EDITIONS"

                if (
                    fmt != "UNKNOWN"
                    and typed != "UNKNOWN"
                    and fmt != typed
                ):
                    row = None
                    issue = "RETAILER_FORMAT_CONFLICT"

                if (
                    len(langs) == 1
                    and scope(candidate.language)
                    != scope(next(iter(langs)))
                ):
                    row = None
                    issue = "RETAILER_LANGUAGE_CONFLICT"

                link = await s.scalar(
                    select(RetailerLink).where(
                        RetailerLink.guild_id == guild,
                        RetailerLink.store_product_id == offer.id,
                    )
                )

                if row is None and not issue and link is None:
                    continue

                if link is None:
                    link = RetailerLink(
                        guild_id=guild,
                        store_product_id=offer.id,
                    )
                    s.add(link)

                state = (
                    "MATCHED"
                    if row and row.status != "ARCHIVED"
                    else "REVIEW" if issue else "UNMATCHED"
                )

                link.release_id = (
                    row.id if state == "MATCHED" else None
                )
                link.state = state
                link.checked_at = utcnow()
                link.details_json = json.dumps({
                    "title": product.name,
                    "store": shop.name,
                    "url": url,
                    "reason": issue,
                    "stock_state_used": False,
                })

                stats[
                    "matched" if state == "MATCHED" else "review"
                ] += 1

            cursor.after_id = rows[-1][0].id if rows else 0
            return stats

    async def retailers(self, guild, page=1):
        from app.models import Store, StoreProduct

        positive_id(guild, "Server ID")
        self.catalog._page(page)
        await self.ensure_schema()

        async with self.sessions() as s:
            rows = (
                await s.scalars(
                    select(RetailerLink)
                    .join(
                        StoreProduct,
                        StoreProduct.id
                        == RetailerLink.store_product_id,
                    )
                    .join(
                        Store,
                        Store.id == StoreProduct.store_id,
                    )
                    .where(
                        RetailerLink.guild_id == guild,
                        Store.active.is_(True),
                    )
                    .order_by(RetailerLink.id.desc())
                    .offset((page - 1) * 10)
                    .limit(11)
                )
            ).all()

            return {
                "items": [snapshot(row) for row in rows[:10]],
                "page": page,
                "has_more": len(rows) > 10,
            }
