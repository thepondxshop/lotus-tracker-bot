"""Guild-scoped calendar preferences and durable release-day delivery receipts."""
from __future__ import annotations
import asyncio
import hashlib
import json
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String, Text, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from .service import Release, ReleaseSource, CatalogError, snapshot, utcnow, public_source_url
from .official import OfficialCheck
from .source_confidence import classify, structured
from .calendar_dates import parse_period, placement
from .tcg_scope import non_tcg_reason

VERSION = '1.0.0-CAL1'

class Base(DeclarativeBase): pass

class Settings(Base):
    __tablename__ = 'lotus_calendar_settings'
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    panel_id: Mapped[int | None] = mapped_column(BigInteger)
    announcement_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    announcements_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(80), default='America/New_York')
    announcement_hour: Mapped[int] = mapped_column(Integer, default=9)
    announcement_region: Mapped[str] = mapped_column(String(40), default='US')
    minimum_tier: Mapped[str] = mapped_column(String(16), default='Lite')
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)

class Preference(Base):
    __tablename__ = 'lotus_calendar_preferences'
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    games_json: Mapped[str] = mapped_column(Text, default='null')
    announcements_json: Mapped[str] = mapped_column(Text, default='[]')
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)

class Delivery(Base):
    __tablename__ = 'lotus_calendar_deliveries'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    release_id: Mapped[int] = mapped_column(Integer)
    release_date: Mapped[date] = mapped_column(Date)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20), default='SENDING')
    error: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)

class ImageOverride(Base):
    __tablename__ = 'lotus_calendar_images'
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    release_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


def public_url(value):
    try: return public_source_url(value, required=True)
    except (CatalogError, TypeError, ValueError): return None


def json_details(value):
    parsed = structured(value)
    if parsed: return parsed
    if isinstance(value, str) and '{' in value:
        try:
            obj, _ = json.JSONDecoder().raw_decode(value[value.index('{'):])
            return obj if isinstance(obj, dict) else {}
        except ValueError: pass
    return {}


def source_dates(row, sources):
    """Exact dates in retained product evidence, keeping the latest note per URL.

    Reading evidence never promotes a record or changes announcement eligibility.
    Free-text dates and order deadlines are deliberately not interpreted here.
    """
    latest = {}
    for source in sources:
        url = public_url(source.get('url'))
        if url and str(source.get('kind', '')).upper() in ('PUBLISHER', 'DISTRIBUTOR'):
            latest[url] = source
    result = []
    for url, source in latest.items():
        data = json_details(source.get('note'))
        if data.get('match_scope') == 'GAME_LAUNCH': continue
        if any(x in (data.get('issues') or []) for x in
               ('INVALID_RELEASE_DATE', 'SOURCE_SCOPE_CONFLICT', 'MULTIPLE_LANGUAGES')): continue
        conflict = False
        for field in ('region', 'language'):
            a, b = str(row.get(field) or '').casefold(), str(data.get(field) or '').casefold()
            if a not in ('', 'unknown') and b not in ('', 'unknown') and a != b:
                conflict = True
        if conflict: continue
        p = placement(parse_period(data.get('release_date')))
        if p and not p['tba']:
            p.update(scope='PRODUCT', source_url=url, source_kind=str(source['kind']).upper())
            result.append(p)
    return result


def make_entry(row, sources, check=None, image_override=None):
    """Exact catalog dates win; broad endpoints only determine TBA placement."""
    confidence = classify(row, sources)
    periods, evidence_images = [], []
    notes = []
    for e in (check or {}).get('evidence', []):
        if e.get('match_scope') == 'PRODUCT' and e.get('image_url'):
            evidence_images.append(e['image_url'])
        for w in e.get('windows', []):
            p = placement(w)
            if p:
                p.update(scope=e.get('match_scope'), source_url=public_url(e.get('url')))
                # Game-wide windows remain labeled and can never announce a SKU.
                if e.get('match_scope') == 'GAME_LAUNCH' and p['precision'] == 'DAY':
                    notes.append('Game launch date is not an exact product release date.')
                    continue
                periods.append(p)
        if e.get('stale'): notes.append('Publisher evidence needs a fresh check.')
        if e.get('state') == 'DATE_REVIEW': notes.append('Date evidence needs review.')
    raw = json_details(row.get('reported_details'))
    source_url = next((public_url(s.get('url')) for s in reversed(sources) if public_url(s.get('url'))), None)
    if row.get('release_date'):
        period = placement(parse_period(row['release_date']))
        date_origin = 'Catalog date'
    else:
        recorded = source_dates(row, sources)
        exact_dates = {p['anchor'] for p in recorded}
        distinct = {(p['start'], p['end'], p['precision']): p for p in periods}
        if recorded and (len(exact_dates) > 1 or any(
                not p['start'] <= recorded[0]['anchor'] <= p['end'] for p in periods)):
            period = None; date_origin = 'Conflicting release windows'
            notes.append('Recorded product dates disagree; no single date selected.')
        elif recorded:
            period = recorded[-1]
            date_origin = 'Distributor-listed date' if period['source_kind'] == 'DISTRIBUTOR' else 'Publisher-listed date'
            source_url = period['source_url']
            notes.append('Exact date from saved product evidence; catalog confirmation is tracked separately.')
        elif len(distinct) == 1:
            period = next(iter(distinct.values())); date_origin = 'Publisher window'
            source_url = period.get('source_url') or source_url
        elif len(distinct) > 1:
            period = None; date_origin = 'Conflicting release windows'
            notes.append('Multiple release windows; no single date selected.')
        else:
            # Read only explicitly named fields, never arbitrary years in a title.
            period = next((placement(parse_period(raw.get(k))) for k in
                ('release_date', 'release_window', 'release_period', 'release_season')
                if parse_period(raw.get(k))), None)
            date_origin = 'Reported date/window' if period else 'Date not announced'
    image = public_url(image_override) if image_override else None
    if not image:
        image = next((public_url(v) for v in evidence_images + [raw.get('image_url'), raw.get('image')]
                      if isinstance(v, str) and public_url(v)), None)
    exact = bool(period and not period['tba'])
    return {**row, 'period': period, 'image_url': image, 'source_url': source_url,
        'confidence': confidence['label'], 'date_origin': date_origin, 'notes': list(dict.fromkeys(notes)),
        'announceable': bool(exact and row.get('release_date') and row.get('status') == 'CONFIRMED'
                            and row.get('confirmed_source_id') and 'Date evidence needs review.' not in notes)}


class CalendarStore:
    def __init__(self, catalog, verifier):
        self.catalog, self.verifier = catalog, verifier
        self.engine, self.sessions = catalog.engine, catalog.sessions
        self.ready = False
        self.schema_lock, self.writes = asyncio.Lock(), asyncio.Lock()

    async def ensure(self):
        await self.verifier.ensure()
        async with self.schema_lock:
            if not self.ready:
                async with self.engine.begin() as conn:
                    if conn.dialect.name == 'postgresql':
                        await conn.execute(text('SELECT pg_advisory_xact_lock(1280460115)'))
                    await conn.run_sync(Base.metadata.create_all)
                self.ready = True

    async def lock(self, session, guild):
        if self.engine.dialect.name == 'postgresql':
            await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int(guild)})

    async def settings(self, guild):
        await self.ensure()
        async with self.sessions() as s:
            row = await s.get(Settings, guild)
            return snapshot(row) if row else {'guild_id': guild, 'channel_id': None, 'panel_id': None,
                'announcement_channel_id': None, 'announcements_enabled': False,
                'timezone': 'America/New_York', 'announcement_hour': 9,
                'announcement_region': 'US', 'minimum_tier': 'Lite'}

    async def configure(self, guild, **changes):
        if 'timezone' in changes:
            try: ZoneInfo(changes['timezone'])
            except (ZoneInfoNotFoundError, ValueError): raise CatalogError('Use a timezone such as America/New_York.')
        if 'announcement_hour' in changes and not 0 <= changes['announcement_hour'] <= 23:
            raise CatalogError('Announcement hour must be 0ā€“23.')
        if 'minimum_tier' in changes and changes['minimum_tier'] not in ('Free', 'Lite', 'Premium', 'Premium+'):
            raise CatalogError('Unknown subscription tier.')
        allowed = {'channel_id','panel_id','announcement_channel_id','announcements_enabled','timezone',
                   'announcement_hour','announcement_region','minimum_tier'}
        if set(changes) - allowed: raise CatalogError('Unknown calendar setting.')
        await self.ensure()
        async with self.writes, self.sessions() as s, s.begin():
            await self.lock(s, guild)
            row = await s.get(Settings, guild)
            if not row: row = Settings(guild_id=guild); s.add(row)
            for key, value in changes.items(): setattr(row, key, value)
            row.updated_at = utcnow()
        return await self.settings(guild)

    async def preference(self, guild, user):
        await self.ensure()
        async with self.sessions() as s:
            row = await s.get(Preference, (guild, user))
            return {'games': json.loads(row.games_json) if row else None,
                    'announcements': json.loads(row.announcements_json) if row else []}

    async def save_preference(self, guild, user, *, games='UNCHANGED', announcements=None):
        await self.ensure()
        async with self.writes, self.sessions() as s, s.begin():
            await self.lock(s, guild)
            row = await s.get(Preference, (guild, user))
            if not row: row = Preference(guild_id=guild, user_id=user); s.add(row)
            if games != 'UNCHANGED': row.games_json = json.dumps(games)
            if announcements is not None: row.announcements_json = json.dumps(announcements)
            row.updated_at = utcnow()

    async def subscribers(self, guild, game):
        await self.ensure()
        async with self.sessions() as s:
            rows = (await s.scalars(select(Preference).where(Preference.guild_id == guild))).all()
            return [r.user_id for r in rows if game in json.loads(r.announcements_json)]

    async def entries(self, guild):
        await self.ensure()
        async with self.sessions() as s:
            releases = (await s.scalars(select(Release).where(Release.guild_id == guild, Release.status != 'ARCHIVED'))).all()
            sources = (await s.scalars(select(ReleaseSource).join(Release).where(Release.guild_id == guild,
                                      Release.status != 'ARCHIVED').order_by(ReleaseSource.id))).all()
            checks = {r.release_id: structured(r.result_json) for r in
                      (await s.scalars(select(OfficialCheck).where(OfficialCheck.guild_id == guild))).all()}
            images = {r.release_id: r.url for r in (await s.scalars(select(ImageOverride).where(ImageOverride.guild_id == guild))).all()}
            grouped = {}
            for source in sources: grouped.setdefault(source.release_id, []).append(snapshot(source))
            result = []
            for n, row in enumerate(releases):
                if n % 100 == 0: await asyncio.sleep(0)
                if non_tcg_reason(row.title): continue
                result.append(make_entry(snapshot(row), grouped.get(row.id, []), checks.get(row.id), images.get(row.id)))
            return result

    async def save_image(self, guild, rid, sid, url):
        url = public_source_url(url, required=True)
        await self.ensure()
        async with self.writes, self.sessions() as s, s.begin():
            await self.lock(s, guild)
            await self.catalog._release(s, guild, rid)
            source = await s.get(ReleaseSource, sid)
            if not source or source.release_id != rid: raise CatalogError('Source must belong to this release.')
            row = await s.get(ImageOverride, (guild, rid))
            if not row: row = ImageOverride(guild_id=guild, release_id=rid); s.add(row)
            row.url, row.source_id, row.updated_at = url, sid, utcnow()

    async def configured(self):
        await self.ensure()
        async with self.sessions() as s: return [snapshot(x) for x in (await s.scalars(select(Settings))).all()]

    async def claim(self, guild, entry, channel, day):
        key = hashlib.sha256(f'{guild}:{entry["id"]}:{day.isoformat()}'.encode()).hexdigest()
        await self.ensure()
        try:
            async with self.writes, self.sessions() as s, s.begin():
                await self.lock(s, guild)
                existing = await s.get(Delivery, key)
                if existing and existing.state != 'RETRY': return None
                # Recheck exact date/status at the send boundary.
                row = await self.catalog._release(s, guild, entry['id'])
                if non_tcg_reason(row.title): return None
                if row.status != 'CONFIRMED' or row.release_date != day or not row.confirmed_source_id:
                    return None
                if existing:
                    existing.state, existing.error, existing.updated_at = 'SENDING', None, utcnow()
                else:
                    s.add(Delivery(key=key,guild_id=guild,release_id=row.id,release_date=day,channel_id=channel))
            return key
        except IntegrityError: return None

    async def delivered(self, key, state, message=None, error=None):
        async with self.sessions() as s, s.begin():
            row = await s.get(Delivery, key)
            if row:
                row.state, row.message_id, row.error, row.updated_at = state, message, error, utcnow()

    async def delivery_rows(self, guild, limit=100):
        await self.ensure()
        async with self.sessions() as s:
            return [snapshot(r) for r in (await s.scalars(select(Delivery).where(Delivery.guild_id == guild)
                .order_by(Delivery.created_at.desc()).limit(limit))).all()]
