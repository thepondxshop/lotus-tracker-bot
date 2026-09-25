"""Durable, guild-scoped release notices and post-publication review.

New tables only. No stock events, Redis writes, or network requests.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint, case, exists, func, or_, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .service import (CatalogError, Release, ReleaseSource, clean, digest, exact_date,
                      identity, public_source_url, snapshot, utcnow, FORMATS)
from .ingestion_store import Item, Watch, aware
from .official import OfficialCheck
from .radar import evidence_summary
from .extraction import GAMES

VERSION = '1.6.0'
FIELDS = {'title': 180, 'game': 80, 'set_code': 40, 'region': 40,
          'language': 40, 'product_format': 20, 'reported_date': 10}


class Base(DeclarativeBase):
    pass


class PublishingSettings(Base):
    __tablename__ = 'lotus_radar_publishing'
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    release_cursor: Mapped[int] = mapped_column(Integer, default=0)
    item_cursor: Mapped[int] = mapped_column(Integer, default=0)
    changed_by: Mapped[int] = mapped_column(BigInteger)
    changed_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notice(Base):
    __tablename__ = 'lotus_radar_notices'
    __table_args__ = (UniqueConstraint('guild_id', 'notice_key', name='uq_lotus_radar_notice'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    notice_key: Mapped[str] = mapped_column(String(90))
    release_id: Mapped[int | None] = mapped_column(Integer, index=True)
    item_id: Mapped[int | None] = mapped_column(Integer)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20), default='READY')
    payload_json: Mapped[str] = mapped_column(Text, default='{}')
    fingerprint: Mapped[str] = mapped_column(String(64), default='')
    overrides_json: Mapped[str] = mapped_column(Text, default='{}')
    review_state: Mapped[str] = mapped_column(String(20), default='PENDING')
    review_note: Mapped[str] = mapped_column(Text, default='')
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    dirty: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempt_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(80))


class ReviewAudit(Base):
    __tablename__ = 'lotus_radar_review_audit'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(Integer, index=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(24))
    details_json: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


def unpack(row):
    data = snapshot(row)
    data['payload'] = json.loads(row.payload_json)
    return data


def payload_signature(payload):
    return digest(payload)


class PublishingStore:
    def __init__(self, ingestion, verifier):
        self.ingestion = ingestion
        self.catalog = ingestion.catalog
        self.verifier = verifier
        self.engine = ingestion.engine
        self.sessions = ingestion.sessions
        self.ready = False
        self.schema_lock = asyncio.Lock()
        self.writes = asyncio.Lock()

    async def ensure(self):
        await self.verifier.ensure()
        async with self.schema_lock:
            if not self.ready:
                async with self.engine.begin() as conn:
                    if conn.dialect.name == 'postgresql':
                        await conn.execute(text('SELECT pg_advisory_xact_lock(1280460106)'))
                    await conn.run_sync(Base.metadata.create_all)
                self.ready = True

    async def configure(self, guild, actor, channel, enabled):
        await self.ensure()
        async with self.writes, self.sessions() as s, s.begin():
            await self.ingestion.guild_lock(s, guild)
            cfg = await s.get(PublishingSettings, guild)
            first = cfg is None
            if first:
                # Existing records are a baseline, not hundreds of new discoveries.
                high = await s.scalar(select(func.max(Release.id)).where(Release.guild_id == guild))
                items = await s.scalar(select(func.max(Item.id)).join(Watch, Watch.id == Item.watch_id)
                    .where(Watch.guild_id == guild))
                cfg = PublishingSettings(guild_id=guild, channel_id=channel, release_cursor=high or 0,
                    item_cursor=items or 0, changed_by=actor)
                s.add(cfg)
            cfg.channel_id, cfg.enabled = channel, enabled
            cfg.changed_by, cfg.changed_at = actor, utcnow()
            await s.flush()
            return {**snapshot(cfg), 'first_setup': first}

    async def settings(self, guild):
        await self.ensure()
        async with self.sessions() as s:
            cfg = await s.get(PublishingSettings, guild)
            counts = dict((await s.execute(select(Notice.state, func.count()).where(Notice.guild_id == guild)
                .group_by(Notice.state))).all())
            errors = (await s.scalars(select(Notice).where(Notice.guild_id == guild, Notice.error.is_not(None))
                .order_by(Notice.id.desc()).limit(5))).all()
            return {'configuration': snapshot(cfg) if cfg else None, 'deliveries': counts,
                    'errors': [{'id': n.id, 'state': n.state, 'error': n.error} for n in errors]}

    async def enabled_guilds(self):
        await self.ensure()
        async with self.sessions() as s:
            return list((await s.scalars(select(PublishingSettings.guild_id)
                .where(PublishingSettings.enabled.is_(True)))).all())

    async def _notice(self, s, guild, nid):
        row = await s.scalar(select(Notice).where(Notice.guild_id == guild, Notice.id == nid).with_for_update())
        if row is None:
            raise CatalogError('Alert not found in this server.')
        return row

    async def _queue_release(self, s, cfg, rid):
        notice = await s.scalar(select(Notice).where(Notice.guild_id == cfg.guild_id, Notice.release_id == rid))
        if notice:
            return notice
        # A previously unlinked source can later resolve to this catalog record.
        keys = list((await s.scalars(select(Item.url_key).join(Watch, Watch.id == Item.watch_id)
            .where(Watch.guild_id == cfg.guild_id, Item.release_id == rid))).all())
        if keys:
            notice = await s.scalar(select(Notice).where(Notice.guild_id == cfg.guild_id,
                Notice.notice_key.in_(['source:' + k for k in keys])).order_by(Notice.id).limit(1))
            if notice:
                notice.release_id = rid
                return notice
        notice = Notice(guild_id=cfg.guild_id, notice_key=f'release:{rid}', release_id=rid, channel_id=cfg.channel_id)
        s.add(notice)
        await s.flush()
        return notice

    async def stage(self, guild):
        await self.ensure()
        async with self.writes, self.sessions() as s, s.begin():
            await self.ingestion.guild_lock(s, guild)
            cfg = await s.get(PublishingSettings, guild)
            if cfg is None or not cfg.enabled:
                return
            releases = (await s.scalars(select(Release).where(Release.guild_id == guild,
                Release.id > cfg.release_cursor).order_by(Release.id).limit(50))).all()
            for row in releases:
                if row.status != 'ARCHIVED':
                    await self._queue_release(s, cfg, row.id)
                cfg.release_cursor = row.id
            # Source exceptions without a catalog match are public unverified leads too.
            items = (await s.scalars(select(Item).join(Watch, Watch.id == Item.watch_id).where(
                Watch.guild_id == guild, Item.id > cfg.item_cursor, Item.state == 'REVIEW', Item.payload_json != '{}',
                ~exists(select(Notice.id).where(Notice.guild_id == guild,
                    or_(Notice.notice_key == ('source:' + Item.url_key), Notice.release_id == Item.release_id)))
                ).order_by(Item.id).limit(50))).all()
            for item in items:
                if item.state == 'REVIEW' and item.payload_json:
                    if item.release_id:
                        await self._queue_release(s, cfg, item.release_id)
                    else:
                        key = 'source:' + item.url_key
                        found = await s.scalar(select(Notice.id).where(Notice.guild_id == guild, Notice.notice_key == key))
                        if found is None:
                            s.add(Notice(guild_id=guild, notice_key=key, item_id=item.id, channel_id=cfg.channel_id))
                # item_cursor remains the activation baseline. The NOT EXISTS query
                # revisits items that only acquire parse results in a later scan.

    async def queue_existing(self, guild, rid):
        await self.ensure()
        async with self.writes, self.sessions() as s, s.begin():
            await self.ingestion.guild_lock(s, guild)
            cfg = await s.get(PublishingSettings, guild)
            if cfg is None or not cfg.enabled:
                raise CatalogError('Configure /release radar publishing first.')
            row = await self.catalog._release(s, guild, rid)
            if row.status == 'ARCHIVED':
                raise CatalogError('This release is archived.')
            notice = await self._queue_release(s, cfg, rid)
            return unpack(notice)

    async def _payload(self, s, n):
        item = await s.get(Item, n.item_id) if n.item_id else None
        if item and n.notice_key.startswith('source:'):
            latest = await s.scalar(select(Item).join(Watch, Watch.id == Item.watch_id).where(
                Watch.guild_id == n.guild_id, Item.url_key == n.notice_key[7:], Item.payload_json != '{}')
                .order_by(Item.checked_at.desc().nullslast(), Item.id.desc()).limit(1))
            if latest:
                item, n.item_id = latest, latest.id
        if item and item.release_id and item.state != 'REVIEW':
            n.release_id = item.release_id
        if n.release_id:
            row = await self.catalog._release(s, n.guild_id, n.release_id)
            facts = {k: getattr(row, k) for k in FIELDS if k != 'reported_date'}
            facts.update(reported_date=row.release_date.isoformat() if row.release_date else None,
                         status=row.status, date_origin='CATALOG' if row.release_date else None)
            sources = (await s.scalars(select(ReleaseSource).where(ReleaseSource.release_id == row.id)
                .order_by(ReleaseSource.id.desc()).limit(3))).all()
            check = await s.scalar(select(OfficialCheck).where(OfficialCheck.guild_id == n.guild_id,
                OfficialCheck.release_id == row.id))
            summary = evidence_summary(json.loads(check.result_json) if check else None)
            flags = ['Date evidence differs between sources.'] if summary.get('date_review') else []
            windows = []
            for e in summary.get('evidence', [])[:3]:
                flags.extend(str(issue) for issue in e.get('issues', [])[:6])
                if e.get('stale'):
                    flags.append('Some publisher evidence needs refresh.')
                for w in e.get('windows', [])[:2]:
                    windows.append({'label': str(w.get('label') or 'Unknown')[:120],
                        'precision': w.get('precision', 'UNKNOWN'), 'scope': e.get('match_scope', 'UNKNOWN'),
                        'url': e.get('url'), 'stale': bool(e.get('stale'))})
            unresolved = (await s.scalars(select(Item.issues_json).join(Watch, Watch.id == Item.watch_id).where(
                Watch.guild_id == n.guild_id, Item.release_id == row.id, Item.state == 'REVIEW').limit(5))).all()
            for issues in unresolved:
                flags.extend(json.loads(issues or '[]')[:5])
            src = [{'kind': x.kind, 'label': x.label, 'url': x.url} for x in sources]
        elif item:
            watch = await s.get(Watch, item.watch_id)
            if not watch or watch.guild_id != n.guild_id:
                raise CatalogError('Source does not belong to this server.')
            raw = json.loads(item.payload_json or '{}')
            facts = {k: raw.get(k) or 'UNKNOWN' for k in FIELDS if k != 'reported_date'}
            facts.update(reported_date=raw.get('release_date'), status='RUMORED', date_origin='SOURCE_REPORT')
            src = [{'kind': watch.kind, 'label': watch.label, 'url': item.url}]
            windows = []
            flags = ['Product identity needs review.'] + json.loads(item.issues_json or '[]')[:8]
        else:
            raise CatalogError('The source record is unavailable.')
        applied = []
        for field, rule in json.loads(n.overrides_json or '{}').items():
            if facts.get(field) in (rule['before'], rule['value']):
                facts[field] = rule['value']
                applied.append(field)
                if field == 'reported_date':
                    facts['date_origin'] = 'ADMIN_REPORT'
            else:
                flags.append(f'New source information conflicts with the saved {field} correction.')
        for field in ('region', 'language', 'product_format'):
            if str(facts.get(field) or '').upper() in ('', 'UNKNOWN'):
                flags.append(field.replace('_', ' ').title() + ' not verified.')
        if facts['status'] != 'CONFIRMED':
            flags.insert(0, 'Release is not confirmed in the catalog.')
        return {'facts': facts, 'sources': src, 'windows': windows, 'flags': sorted(set(flags)),
                'admin_fields': sorted(applied)}

    async def _refresh(self, s, n):
        payload = await self._payload(s, n)
        signature = payload_signature(payload)
        if signature != n.fingerprint:
            n.payload_json, n.fingerprint = json.dumps(payload, ensure_ascii=False), signature
            n.review_state, n.review_note, n.reviewed_by = 'PENDING', '', None
            n.revision += 1
            n.dirty = True
        n.last_checked = utcnow()

    async def work(self, guild):
        async with self.sessions() as s:
            return list((await s.scalars(select(Notice.id).where(Notice.guild_id == guild,
                or_(Notice.retry_at.is_(None), Notice.retry_at <= utcnow()))
                .order_by(case((Notice.state.in_(('READY', 'RETRY')), 0), else_=1),
                    Notice.last_checked, Notice.id).limit(25))).all())

    async def refresh(self, guild, nid):
        async with self.writes, self.sessions() as s, s.begin():
            await self.ingestion.guild_lock(s, guild)
            n = await self._notice(s, guild, nid)
            await self._refresh(s, n)
            return unpack(n)

    async def from_message(self, guild, channel, message):
        await self.ensure()
        async with self.sessions() as s:
            n = await s.scalar(select(Notice).where(Notice.guild_id == guild, Notice.channel_id == channel,
                Notice.message_id == message))
            if n is None:
                raise CatalogError('This message is not a registered release alert.')
            return unpack(n)

    async def claim(self, guild, nid):
        async with self.writes, self.sessions() as s, s.begin():
            await self.ingestion.guild_lock(s, guild)
            cfg = await s.get(PublishingSettings, guild)
            n = await self._notice(s, guild, nid)
            if not cfg or not cfg.enabled or n.state not in ('READY', 'RETRY'):
                return None
            if n.retry_at and aware(n.retry_at) > utcnow():
                return None
            await self._refresh(s, n)
            # Configured destinations affect new sends, not already posted messages.
            n.channel_id = cfg.channel_id
            n.state, n.attempt_at, n.error = 'SENDING', utcnow(), None
            return unpack(n)

    async def delivery(self, guild, nid, *, state, message=None, error=None, revision=None):
        async with self.writes, self.sessions() as s, s.begin():
            await self.ingestion.guild_lock(s, guild)
            n = await self._notice(s, guild, nid)
            if state in ('RETRY', 'UNCERTAIN', 'SKIPPED') and n.state in ('SENT', 'DELETED'):
                return
            if message is not None and n.message_id is not None and n.message_id != message:
                raise CatalogError('An original message is already saved for this alert.')
            n.state, n.error = state, error
            if message is not None:
                n.message_id = message
            if state == 'SENT' and revision == n.revision:
                n.dirty = False
            delay = 60 if state == 'RETRY' or (state == 'SENT' and error) else 300 if state == 'UNCERTAIN' else 0
            n.retry_at = utcnow() + timedelta(seconds=delay) if delay else None

    async def reviewed(self, guild, actor, nid, revision, action, *, field=None, value=None, note='', source=None):
        if action not in ('CORRECT', 'INCORRECT', 'UNKNOWN', 'CORRECT_FIELD'):
            raise CatalogError('Unknown review action.')
        note = clean(note, 'Explanation', 1000, empty=action in ('CORRECT', 'UNKNOWN'))
        source = public_source_url(source, required=False)
        if action == 'CORRECT_FIELD':
            if field not in FIELDS:
                raise CatalogError('Choose a supported correction field.')
            value = clean(value, 'Correct information', FIELDS[field])
            if field == 'product_format':
                value = value.upper()
                if value not in FORMATS:
                    raise CatalogError('Format must be: ' + ', '.join(FORMATS))
            if field == 'game' and value not in {g for g, _ in GAMES}:
                raise CatalogError('Use an existing game name from /release radar list.')
            if field == 'reported_date' and value.upper() != 'UNKNOWN':
                exact_date(value)
        await self.ensure()
        async with self.writes, self.sessions() as s, s.begin():
            await self.ingestion.guild_lock(s, guild)
            n = await self._notice(s, guild, nid)
            current = await self._payload(s, n)
            if n.revision != revision or payload_signature(current) != n.fingerprint:
                raise CatalogError('Information changed since you opened review. Reopen Review before saving.')
            before = current['facts'].copy()
            if action == 'CORRECT_FIELD':
                rules = json.loads(n.overrides_json or '{}')
                rules[field] = {'before': before.get(field), 'value': value, 'actor': actor, 'source': source}
                if n.release_id and field != 'reported_date':
                    row = await self.catalog._release(s, guild, n.release_id, lock=True)
                    old_catalog = snapshot(row)
                    changed = {k: getattr(row, k) for k in ('game', 'title', 'region', 'language', 'product_format')}
                    if field in changed:
                        changed[field] = value
                    new_key = identity(**changed)
                    duplicate = await s.scalar(select(Release.id).where(Release.guild_id == guild,
                        Release.identity_key == new_key, Release.id != row.id))
                    if duplicate:
                        raise CatalogError(f'This correction conflicts with release #{duplicate}; no records were merged.')
                    setattr(row, field, value)
                    row.identity_key, row.updated_at = new_key, utcnow()
                    if row.status == 'CONFIRMED' and old_catalog.get(field) != value:
                        # Confirmation belonged to the previous identity. An admin
                        # correction is not publisher evidence for a different edition.
                        row.status, row.release_date = 'RUMORED', None
                        row.confirmed_source_id = row.confirmed_by = row.confirmed_at = None
                        self.catalog._audit(s, row, actor, 'RETRACTED', {
                            'reason': 'Identity corrected during alert review; confirmation needs new evidence.',
                            'before': old_catalog, 'after': snapshot(row)})
                    rules[field]['before'] = value
                    src = self.catalog._source(row, actor, 'COMMUNITY', 'Admin alert correction', source,
                        json.dumps({'field': field, 'value': value, 'note': note}, ensure_ascii=False))
                    exists = await s.scalar(select(ReleaseSource.id).where(ReleaseSource.release_id == row.id,
                        ReleaseSource.fingerprint == src.fingerprint))
                    if not exists:
                        s.add(src)
                n.overrides_json = json.dumps(rules, ensure_ascii=False)
                await s.flush()
                current = await self._payload(s, n)
            details = {'notice_id': nid, 'action': action, 'field': field, 'value': value,
                       'note': note, 'source': source, 'before': before, 'after': current['facts']}
            s.add(ReviewAudit(notice_id=nid, guild_id=guild, actor_id=actor, action=action,
                details_json=json.dumps(details, ensure_ascii=False)))
            if n.release_id:
                row = await self.catalog._release(s, guild, n.release_id)
                self.catalog._audit(s, row, actor, 'ALERT_REVIEW', details)
            n.payload_json, n.fingerprint = json.dumps(current, ensure_ascii=False), payload_signature(current)
            n.review_state = {'CORRECT': 'CONFIRMED', 'INCORRECT': 'INCORRECT',
                              'UNKNOWN': 'UNKNOWN', 'CORRECT_FIELD': 'CORRECTED'}[action]
            n.review_note, n.reviewed_by = note, actor
            n.revision += 1
            n.dirty = True
            return unpack(n)

    async def audit(self, guild, nid):
        async with self.sessions() as s:
            await self._notice(s, guild, nid)
            return [snapshot(x) for x in (await s.scalars(select(ReviewAudit).where(
                ReviewAudit.guild_id == guild, ReviewAudit.notice_id == nid)
                .order_by(ReviewAudit.id.desc()).limit(8))).all()]
