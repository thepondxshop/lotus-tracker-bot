"""One Piece publisher-page leads. No stock, price, or confirmation writes."""
import asyncio
import json
import re
from datetime import timedelta
from urllib.parse import urljoin, urlsplit

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint, select, text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .service import Release, ReleaseSource, CatalogError, digest, identity, snapshot, utcnow
from .ingestion_store import aware
from .official import OfficialSource, OfficialPage, OfficialCheck
from .official_parser import approved_url, evaluate, primary_product_text, release_windows

VERSION = '1.6.3'
from .one_piece_products import product_path, product_identity


def product_url(url):
    try:
        url = approved_url('One Piece', url)
        p = urlsplit(url)
        if not product_path(url):
            return None
        return 'https://en.onepiece-cardgame.com' + p.path.lower()
    except (ValueError, TypeError):
        return None


def candidate(doc):
    url = product_url(doc.get('url', ''))
    details = product_identity(doc)
    if not url or not details:
        return None
    return dict(url=url, **details, game='One Piece', language='English', region='UNKNOWN',
                windows=release_windows(primary_product_text(doc)))


class Base(DeclarativeBase):
    pass


class DiscoverySettings(Base):
    __tablename__ = 'lotus_official_discovery_settings'
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    baseline_at: Mapped[object] = mapped_column(DateTime(timezone=True))


class DiscoveryPage(Base):
    __tablename__ = 'lotus_official_discovery_pages'
    __table_args__ = (UniqueConstraint('guild_id', 'url_key', name='uq_lotus_official_discovery_url'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    url_key: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(30))
    release_id: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    checked_at: Mapped[object] = mapped_column(DateTime(timezone=True))


class OfficialDiscovery:
    def __init__(self, verifier):
        self.verifier = verifier
        self.store = verifier.store
        self.sessions = verifier.sessions
        self.ready = False
        self.schema_lock = asyncio.Lock()
        self.started_at = utcnow()
        self.prepared_guilds = set()

    async def ensure(self):
        await self.verifier.ensure()
        async with self.schema_lock:
            if not self.ready:
                async with self.store.engine.begin() as conn:
                    if conn.dialect.name == 'postgresql':
                        await conn.execute(text('SELECT pg_advisory_xact_lock(1280460107)'))
                    await conn.run_sync(Base.metadata.create_all)
                self.ready = True

    async def prepare(self, guild):
        """Baseline cached newly supported pages once, before a scan overwrites them."""
        await self.ensure()
        if guild in self.prepared_guilds:
            return
        marker = 'https://en.onepiece-cardgame.com/products/#coverage-1.6.3'
        async with self.sessions() as s, s.begin():
            await self.store.guild_lock(s, guild)
            cfg = await s.get(DiscoverySettings, guild)
            if not cfg:
                return
            done = await s.scalar(select(DiscoveryPage.id).where(
                DiscoveryPage.guild_id == guild, DiscoveryPage.url_key == digest(marker)))
            if not done:
                known = set((await s.scalars(select(DiscoveryPage.url_key).where(DiscoveryPage.guild_id == guild))).all())
                pages = (await s.scalars(select(OfficialPage).join(OfficialSource,
                    OfficialSource.id == OfficialPage.source_id).where(OfficialSource.guild_id == guild,
                    OfficialSource.game == 'One Piece', OfficialPage.checked_at < self.started_at))).all()
                urls = set()
                for page in pages:
                    doc = json.loads(page.data_json)
                    urls.add(product_url(doc.get('url', '')))
                    for href, _ in doc.get('links', []):
                        urls.add(product_url(urljoin(doc.get('url', ''), href)))
                for url in urls - {None}:
                    if digest(url) in known or re.fullmatch(r'/products/(?:op|eb|prb)\d+\.html', urlsplit(url).path):
                        continue
                    s.add(DiscoveryPage(guild_id=guild, url_key=digest(url), url=url,
                        state='BASELINED', checked_at=self.started_at))
                s.add(DiscoveryPage(guild_id=guild, url_key=digest(marker), url=marker,
                    state='COVERAGE_BASELINE', checked_at=self.started_at))
        self.prepared_guilds.add(guild)

    async def configure(self, guild, actor, enabled):
        await self.ensure()
        await self.verifier.defaults(guild)
        async with self.sessions() as s, s.begin():
            await self.store.guild_lock(s, guild)
            cfg = await s.get(DiscoverySettings, guild)
            first = cfg is None
            if first:
                cfg = DiscoverySettings(guild_id=guild, actor_id=actor, enabled=enabled, baseline_at=utcnow())
                s.add(cfg)
                # Known pages AND known product links are old discoveries.
                pages = (await s.scalars(select(OfficialPage).join(OfficialSource,
                    OfficialSource.id == OfficialPage.source_id).where(
                    OfficialSource.guild_id == guild, OfficialSource.game == 'One Piece'))).all()
                urls = set()
                for page in pages:
                    doc = json.loads(page.data_json)
                    urls.add(product_url(doc.get('url', '')))
                    for href, _ in doc.get('links', []):
                        urls.add(product_url(urljoin(doc.get('url', ''), href)))
                for url in urls - {None}:
                    s.add(DiscoveryPage(guild_id=guild, url_key=digest(url), url=url,
                        state='BASELINED', checked_at=utcnow()))
            cfg.enabled, cfg.actor_id = enabled, actor
            if enabled:
                index = await s.scalar(select(OfficialSource).where(OfficialSource.guild_id == guild,
                    OfficialSource.url == 'https://en.onepiece-cardgame.com/products/'))
                if index:
                    index.next_due = utcnow()
            return {'enabled': enabled, 'first_setup': first}

    async def status(self, guild):
        await self.ensure()
        async with self.sessions() as s:
            cfg = await s.get(DiscoverySettings, guild)
            counts = dict((await s.execute(select(DiscoveryPage.state, func.count()).where(
                DiscoveryPage.guild_id == guild, DiscoveryPage.state != 'COVERAGE_BASELINE').group_by(DiscoveryPage.state))).all())
            return {'enabled': bool(cfg and cfg.enabled), 'counts': counts}

    async def observe(self, guild, page_id, *, explicit=False, actor=None):
        await self.prepare(guild)
        async with self.sessions() as s, s.begin():
            await self.store.guild_lock(s, guild)
            cfg = await s.get(DiscoverySettings, guild)
            if not cfg or not cfg.enabled:
                if explicit:
                    raise CatalogError('Enable /release official discovery first.')
                return {'state': 'PAUSED'}
            result = (await s.execute(select(OfficialPage, OfficialSource).join(OfficialSource,
                OfficialPage.source_id == OfficialSource.id).where(OfficialPage.id == page_id,
                OfficialSource.guild_id == guild, OfficialSource.enabled.is_(True)))).first()
            if not result:
                raise CatalogError('Saved official page is missing or its source is paused.')
            page, source = result
            if page.last_error or aware(page.checked_at) < utcnow()-timedelta(days=1):
                if explicit:
                    raise CatalogError('Scan this official source successfully before importing its page.')
                return {'state': 'STALE'}
            doc = json.loads(page.data_json)
            item = candidate(doc) if source.game == 'One Piece' else None
            if not item:
                if explicit:
                    raise CatalogError('This page is not a supported individual One Piece product.')
                return {'state': 'UNSUPPORTED'}
            saved = await s.scalar(select(DiscoveryPage).where(
                DiscoveryPage.guild_id == guild, DiscoveryPage.url_key == digest(item['url'])))
            if saved and saved.state == 'BASELINED' and not explicit:
                saved.checked_at = page.checked_at
                return {'state': 'BASELINED'}
            # An archived product newly encountered during a crawl is not news.
            if not explicit and item['windows'] and all(w['end'] < utcnow().date().isoformat() for w in item['windows']):
                if saved is None:
                    saved = DiscoveryPage(guild_id=guild, url_key=digest(item['url']), url=item['url'], state='PAST', checked_at=page.checked_at)
                    s.add(saved)
                saved.checked_at = page.checked_at
                return {'state': 'PAST', 'release_id': saved.release_id}
            if saved is None:
                saved = DiscoveryPage(guild_id=guild, url_key=digest(item['url']), url=item['url'], state='NEW', checked_at=page.checked_at)
                s.add(saved)
            key = identity(item['game'], item['title'], item['region'], item['language'], item['product_format'])
            row = await s.get(Release, saved.release_id) if saved.release_id else await s.scalar(
                select(Release).where(Release.guild_id == guild, Release.identity_key == key))
            created = row is None
            actor_id = actor if explicit else cfg.actor_id
            if row is None:
                row = Release(guild_id=guild, identity_key=key, game=item['game'], title=item['title'],
                    set_code=item['set_code'], region=item['region'], language=item['language'],
                    product_format=item['product_format'], status='RUMORED', reported_details=json.dumps(item),
                    created_by=actor_id, created_at=utcnow(), updated_at=utcnow())
                s.add(row)
                await s.flush()
            # Never overwrite admin corrections or revive archived records.
            saved.release_id, saved.checked_at = row.id, page.checked_at
            saved.state = 'ARCHIVED' if row.status == 'ARCHIVED' else ('CREATED' if created else 'LINKED')
            if row.status == 'ARCHIVED':
                return {'state': 'ARCHIVED', 'release_id': row.id}
            fp = digest(item)
            if saved.fingerprint != fp:
                note = json.dumps({'origin': 'OFFICIAL_PAGE_DISCOVERY', **item}, ensure_ascii=False)
                evidence = self.store.catalog._source(row, actor_id, 'PUBLISHER', 'Official One Piece product page', item['url'], note)
                exists = await s.scalar(select(ReleaseSource.id).where(ReleaseSource.release_id == row.id,
                    ReleaseSource.fingerprint == evidence.fingerprint))
                if not exists:
                    s.add(evidence)
                    self.store.catalog._audit(s, row, actor_id, 'OFFICIAL_PAGE_DISCOVERED' if created else 'OFFICIAL_PAGE_UPDATED',
                        {'url': item['url'], 'page_id': page.id, 'automatic': not explicit, 'facts': item})
                saved.fingerprint = fp
                row.updated_at = utcnow()
            # Save windows in the same transaction so the first public notice
            # already includes publisher evidence, not just a pending check.
            checked = evaluate(snapshot(row), doc, 'English', 'UNKNOWN')
            if checked:
                checked.update(fetched_at=aware(page.checked_at).isoformat(), stale=False,
                               source_id=source.id, last_fetch_error=None)
                if row.identity_key != key:
                    checked['issues'].append('PUBLISHER_IDENTITY_CHANGED_REVIEW')
                check = await s.get(OfficialCheck, row.id)
                if not check:
                    check = OfficialCheck(release_id=row.id, guild_id=guild)
                    s.add(check)
                # Preserve other publisher evidence until the normal verifier reconciles.
                prior = json.loads(check.result_json) if check.result_json else {}
                entries = [e for e in prior.get('evidence', []) if e['url'] != item['url']]
                check.result_json = json.dumps({**prior, 'state': 'EVIDENCE_FOUND', 'evidence': [checked]+entries[:19]})
                check.checked_at = utcnow()
            return {'state': 'CREATED' if created else 'LINKED', 'release_id': row.id}

    async def import_source(self, guild, actor, source_id):
        await self.ensure()
        async with self.sessions() as s:
            source = await s.scalar(select(OfficialSource).where(OfficialSource.id == source_id,
                OfficialSource.guild_id == guild, OfficialSource.enabled.is_(True)))
            if not source or not product_url(source.url):
                raise CatalogError('Use the source ID for a specific One Piece product page, not the product index.')
            page = await s.scalar(select(OfficialPage).where(OfficialPage.source_id == source.id,
                OfficialPage.url_key == digest(source.url)))
            if not page:
                raise CatalogError('Run /release official scan for this source first.')
            pid = page.id
        return await self.observe(guild, pid, explicit=True, actor=actor)

    async def catch_up(self, guild):
        """Replay saved pages after a pause/restart without another HTTP request."""
        await self.ensure()
        async with self.sessions() as s:
            cfg = await s.get(DiscoverySettings, guild)
            if not cfg or not cfg.enabled:
                return
            pages = (await s.execute(select(OfficialPage, OfficialSource).join(OfficialSource,
                OfficialPage.source_id == OfficialSource.id).where(OfficialSource.guild_id == guild,
                OfficialSource.game == 'One Piece', OfficialSource.enabled.is_(True),
                OfficialPage.last_error.is_(None), OfficialPage.checked_at >= utcnow()-timedelta(days=1))
                .order_by(OfficialPage.checked_at, OfficialPage.id))).all()
            seen = {p.url_key: aware(p.checked_at) for p in (await s.scalars(select(DiscoveryPage)
                .where(DiscoveryPage.guild_id == guild))).all()}
            pending = []
            for page, source in pages:
                doc = json.loads(page.data_json)
                item = candidate(doc)
                if item and (digest(item['url']) not in seen or seen[digest(item['url'])] < aware(page.checked_at)):
                    pending.append(page.id)
        for pid in pending[:20]:
            await self.observe(guild, pid)
