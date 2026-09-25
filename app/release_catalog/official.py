"""Independent publisher verifier. Additive tables; no stock/queue/calendar writes."""
import asyncio
import json
import logging
from datetime import timedelta
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint, select, or_, text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from .service import Release, ReleaseSource, CatalogError, digest, snapshot, utcnow
from .ingestion_store import aware, Watch, Item
from .public_http import PublicHTTP, FetchError
from .official_parser import PRESETS, VERSION, approved_url, parse_page, discovery_links, evaluate

LOG=logging.getLogger(__name__)

class Base(DeclarativeBase): pass

class OfficialSource(Base):
    __tablename__='lotus_official_sources'
    __table_args__=(UniqueConstraint('guild_id','game','url_key',name='uq_lotus_official_source'),)
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    guild_id: Mapped[int]=mapped_column(BigInteger,index=True)
    game: Mapped[str]=mapped_column(String(80))
    url: Mapped[str]=mapped_column(Text)
    url_key: Mapped[str]=mapped_column(String(64))
    language: Mapped[str]=mapped_column(String(40))
    region: Mapped[str]=mapped_column(String(40))
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    next_due: Mapped[object]=mapped_column(DateTime(timezone=True),default=utcnow)
    lease_until: Mapped[object|None]=mapped_column(DateTime(timezone=True))
    queue_json: Mapped[str]=mapped_column(Text,default='[]')
    last_json: Mapped[str]=mapped_column(Text,default='{}')

class OfficialPage(Base):
    __tablename__='lotus_official_pages'
    __table_args__=(UniqueConstraint('source_id','url_key',name='uq_lotus_official_page'),)
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    source_id: Mapped[int]=mapped_column(Integer,index=True)
    url_key: Mapped[str]=mapped_column(String(64))
    data_json: Mapped[str]=mapped_column(Text)
    checked_at: Mapped[object]=mapped_column(DateTime(timezone=True))
    last_error: Mapped[str|None]=mapped_column(String(80))

class OfficialCheck(Base):
    __tablename__='lotus_official_checks'
    release_id: Mapped[int]=mapped_column(Integer,primary_key=True)
    guild_id: Mapped[int]=mapped_column(BigInteger,index=True)
    result_json: Mapped[str]=mapped_column(Text)
    checked_at: Mapped[object]=mapped_column(DateTime(timezone=True))

class OfficialVerifier:
    def __init__(self,store,http_factory=PublicHTTP):
        self.store=store;self.catalog=store.catalog;self.sessions=store.sessions
        self.version=VERSION;self.http_factory=http_factory;self.ready=False;self.schema_lock=asyncio.Lock()
        self.lock=asyncio.Lock();self.task=None;self.state='NOT_STARTED';self.last_error=None;self.signatures={}
        from .official_discovery import OfficialDiscovery
        self.discovery=OfficialDiscovery(self)
    async def ensure(self):
        await self.store.ensure_schema()
        async with self.schema_lock:
            if not self.ready:
                async with self.store.engine.begin() as conn:
                    if conn.dialect.name=='postgresql': await conn.execute(text('SELECT pg_advisory_xact_lock(1280460102)'))
                    await conn.run_sync(Base.metadata.create_all)
                self.ready=True
    async def defaults(self,guild):
        await self.ensure()
        async with self.sessions() as s,s.begin():
            await self.store.guild_lock(s,guild)
            existing={(r.game,r.url_key) for r in (await s.scalars(select(OfficialSource).where(OfficialSource.guild_id==guild))).all()}
            for game,(url,language,region) in PRESETS.items():
                url=approved_url(game,url)
                if (game,digest(url)) not in existing:
                    s.add(OfficialSource(guild_id=guild,game=game,url=url,url_key=digest(url),language=language,region=region))
    async def sources(self,guild):
        await self.defaults(guild)
        async with self.sessions() as s:
            return [snapshot(r) for r in (await s.scalars(select(OfficialSource).where(OfficialSource.guild_id==guild).order_by(OfficialSource.id))).all()]
    async def add(self,guild,game,url,language='UNKNOWN',region='UNKNOWN'):
        try: url=approved_url(game,url)
        except ValueError as e: raise CatalogError(str(e)) from None
        if len(language)>40 or len(region)>40: raise CatalogError('Region and language must be at most 40 characters.')
        await self.defaults(guild)
        async with self.sessions() as s,s.begin():
            await self.store.guild_lock(s,guild)
            row=await s.scalar(select(OfficialSource).where(OfficialSource.guild_id==guild,OfficialSource.game==game,OfficialSource.url_key==digest(url)))
            if not row:
                count=await s.scalar(select(func.count()).select_from(OfficialSource).where(OfficialSource.guild_id==guild))
                if count>=30: raise CatalogError('Maximum 30 official sources per server.')
                row=OfficialSource(guild_id=guild,game=game,url=url,url_key=digest(url),language=language,region=region)
                s.add(row);await s.flush()
            return snapshot(row)
    async def settings(self,guild,source_id,enabled):
        await self.ensure()
        async with self.sessions() as s,s.begin():
            row=await s.scalar(select(OfficialSource).where(OfficialSource.id==source_id,OfficialSource.guild_id==guild).with_for_update())
            if not row: raise CatalogError('Official source not found in this server.')
            row.enabled=enabled
            return snapshot(row)
    async def releases(self,guild,game):
        async with self.sessions() as s:
            return [snapshot(r) for r in (await s.scalars(select(Release).where(Release.guild_id==guild,func.lower(Release.game)==game.lower(),Release.status!='ARCHIVED').order_by(Release.id).limit(5000))).all()]
    async def reconcile(self,guild,game):
        """Reuses saved official pages for newly discovered catalog records."""
        releases=await self.releases(guild,game)
        async with self.sessions() as s,s.begin():
            await self.store.guild_lock(s,guild)
            sources=(await s.scalars(select(OfficialSource).where(OfficialSource.guild_id==guild,OfficialSource.game==game,OfficialSource.enabled.is_(True)))).all()
            pages=(await s.execute(select(OfficialPage,OfficialSource).join(OfficialSource,OfficialPage.source_id==OfficialSource.id).where(OfficialSource.guild_id==guild,OfficialSource.game==game,OfficialSource.enabled.is_(True)))).all()
            ids=[r['id'] for r in releases]
            items=(await s.scalars(select(Item).join(Watch,Item.watch_id==Watch.id).where(Item.release_id.in_(ids),Watch.guild_id==guild))).all() if ids else []
            items_by_release={}
            for item in items: items_by_release.setdefault(item.release_id,[]).append(item)
            checks={x.release_id:x for x in (await s.scalars(select(OfficialCheck).where(OfficialCheck.guild_id==guild))).all()}
            fingerprints=set((await s.execute(select(ReleaseSource.release_id,ReleaseSource.fingerprint).where(ReleaseSource.release_id.in_(ids)))).all()) if ids else set()
            parsed_pages=[(page,source,json.loads(page.data_json)) for page,source in pages]
            for index, release in enumerate(releases):
                if index % 20 == 0: await asyncio.sleep(0)
                evidence=[]
                for page,source,doc in parsed_pages:
                    result=evaluate(release,doc,source.language,source.region)
                    if result:
                        result['fetched_at']=aware(page.checked_at).isoformat()
                        result['last_fetch_error']=page.last_error
                        result['stale']=bool(page.last_error) or aware(page.checked_at)<utcnow()-timedelta(days=2)
                        result['source_id']=source.id
                        evidence.append(result)
                # Distributor dates stay separate; compare only same catalog release evidence.
                items=items_by_release.get(release['id'],[])
                distributor_dates=sorted({json.loads(i.payload_json).get('release_date') for i in items if json.loads(i.payload_json).get('release_date')})
                for e in evidence:
                    if len(e['windows'])==1 and distributor_dates:
                        w=e['windows'][0]
                        if any(not w['start']<=d<=w['end'] for d in distributor_dates):
                            e['issues'].append('DISTRIBUTOR_DATE_DIFFERS_REVIEW_SCOPE')
                            e['state']='DATE_REVIEW'
                intervals={(w['start'],w['end']) for e in evidence if not e['stale'] for w in e['windows']}
                if len(intervals)>1 and max(x[0] for x in intervals)>min(x[1] for x in intervals):
                    for e in evidence:
                        e['issues'].append('OFFICIAL_SOURCES_DISAGREE');e['state']='DATE_REVIEW'
                checked_sources=[{'id':x.id,'url':x.url,'last':json.loads(x.last_json)} for x in sources]
                state='EVIDENCE_FOUND' if evidence else ('PENDING' if not pages else 'AWAITING_OFFICIAL_MATCH')
                data={'state':state,'evidence':evidence[:20],'sources':checked_sources,'distributor_dates':distributor_dates,
                      'note':'No match is not a denial. Publisher evidence does not establish retail stock or preorder availability.'}
                row=checks.get(release['id'])
                if row is None: row=OfficialCheck(release_id=release['id'],guild_id=guild);s.add(row)
                row.result_json=json.dumps(data);row.checked_at=utcnow()
                for e in evidence:
                    # Immutable source snapshots: later edits do not erase the old date.
                    saved={k:v for k,v in e.items() if k not in ('fetched_at','stale','last_fetch_error','source_id')}
                    fp=digest('OFFICIAL_VERIFIER',saved)
                    if (release['id'],fp) not in fingerprints:
                        fingerprints.add((release['id'],fp))
                        s.add(ReleaseSource(release_id=release['id'],kind='PUBLISHER',label='Official verification evidence',url=e['url'],
                            note=json.dumps(saved,ensure_ascii=False),fingerprint=fp,recorded_by=release['created_by'],recorded_at=utcnow()))
        return len(releases)
    async def result(self,guild,release_id):
        await self.ensure()
        async with self.sessions() as s:
            release=await s.scalar(select(Release).where(Release.id==release_id,Release.guild_id==guild))
            if not release: raise CatalogError('Release not found in this server.')
            row=await s.get(OfficialCheck,release_id)
            return {'release':snapshot(release),'check':json.loads(row.result_json) if row else {'state':'PENDING','evidence':[]},'checked_at':aware(row.checked_at).isoformat() if row else None}
    async def scan(self,guild,source_id):
        await self.ensure()
        if self.lock.locked(): raise CatalogError('An official scan is running; scheduled checks will continue automatically.')
        async with self.lock:
            async with self.sessions() as s,s.begin():
                row=await s.scalar(select(OfficialSource).where(OfficialSource.id==source_id,OfficialSource.guild_id==guild).with_for_update())
                if not row or not row.enabled: raise CatalogError('Official source is missing or paused.')
                if row.lease_until and aware(row.lease_until)>utcnow(): raise CatalogError('Official source is already scanning.')
                last=json.loads(row.last_json)
                if last.get('retry_at') and utcnow().isoformat()<last['retry_at']: raise CatalogError('Official source cooldown is active; try after '+last['retry_at'])
                row.lease_until=utcnow()+timedelta(minutes=4);source=snapshot(row)
            releases=await self.releases(guild,source['game'])
            queue=json.loads(source['queue_json']);new_cycle=not queue;urls=[source['url']];seen=set();pages_ok=0;error=None
            async with self.sessions() as s:
                known=set((await s.scalars(select(OfficialPage.url_key).where(OfficialPage.source_id==source_id))).all())
            try:
                async with asyncio.timeout(120),self.http_factory() as http:
                    while urls and len(seen)<8:
                        url=urls.pop(0)
                        if url in seen: break
                        seen.add(url)
                        try:
                            page=await http.get(url,source['url'])
                            approved_url(source['game'],page.url)
                            doc=parse_page(page.url,page.text)
                            if len(doc['text'])<80: raise FetchError('NO_PUBLIC_TEXT')
                            if any(x in doc['title'].lower() for x in ('access denied','just a moment','captcha')): raise FetchError('ACCESS_CHALLENGE')
                            async with self.sessions() as s,s.begin():
                                saved=await s.scalar(select(OfficialPage).where(OfficialPage.source_id==source_id,OfficialPage.url_key==digest(url)))
                                if not saved:
                                    if len(known)>=500: raise FetchError('PAGE_CACHE_LIMIT')
                                    saved=OfficialPage(source_id=source_id,url_key=digest(url));s.add(saved);known.add(digest(url))
                                saved.data_json=json.dumps(doc);saved.checked_at=utcnow();saved.last_error=None
                                await s.flush()
                                page_id=saved.id
                            pages_ok+=1
                            # Persist a new lead before continuing the crawl.
                            # On failure the saved page is replayed by catch_up.
                            if source['game']=='One Piece':
                                await self.discovery.observe(guild,page_id)
                            new_links=[]
                            for link in discovery_links(source['game'],doc,releases):
                                if link not in seen and link not in queue:
                                    # New pages first; existing pages rotate after the outstanding queue.
                                    if digest(link) not in known: new_links.append(link)
                                    elif new_cycle and url==source['url']: queue.append(link)
                            queue=(new_links+queue)[:500]
                        except FetchError as exc:
                            error=exc.code
                            async with self.sessions() as s,s.begin():
                                saved=await s.scalar(select(OfficialPage).where(OfficialPage.source_id==source_id,OfficialPage.url_key==digest(url)))
                                if saved: saved.last_error=error
                            if url!=source['url']: queue.append(url)
                            if error in ('RATE_LIMITED','ACCESS_DENIED','ACCESS_CHALLENGE'): break
                        if queue: urls.append(queue.pop(0))
            except asyncio.CancelledError:
                error='CANCELLED';raise
            except Exception as exc:
                error='SCAN_TIMEOUT' if isinstance(exc,TimeoutError) else type(exc).__name__
            finally:
                # Persist an unprocessed URL popped at the page limit, and the remaining queue.
                queue=urls+queue
                delay=60 if error else (15 if queue else 360)
                if (not error and source['game']=='One Piece'
                        and source['url'].rstrip('/')==PRESETS['One Piece'][0].rstrip('/')
                        and (await self.discovery.status(guild))['enabled']):
                    delay=5
                last={'at':utcnow().isoformat(),'pages_ok':pages_ok,'error':error,'remaining':len(queue),
                      'retry_at':(utcnow()+timedelta(minutes=60 if error else 5)).isoformat()}
                async with self.sessions() as s,s.begin():
                    row=await s.get(OfficialSource,source_id)
                    row.last_json=json.dumps(last);row.queue_json=json.dumps(list(dict.fromkeys(queue))[:500])
                    row.next_due=utcnow()+timedelta(minutes=delay);row.lease_until=None
            await self.reconcile(guild,source['game'])
            LOG.info('LOTUS OFFICIAL SCAN | Source=%s | Pages=%s | Error=%s',source_id,pages_ok,error)
            return last
    async def run(self,bot):
        try:
            await bot.wait_until_ready()
            while not bot.is_closed():
                try:
                    await self.ensure();await self.discovery.ensure();self.state='RUNNING';self.last_error=None
                    async with self.sessions() as s:
                        guilds=list((await s.scalars(select(Release.guild_id).where(Release.status!='ARCHIVED').distinct())).all())
                        from .official_discovery import DiscoverySettings
                        guilds=sorted(set(guilds)|set((await s.scalars(select(DiscoverySettings.guild_id)
                            .where(DiscoverySettings.enabled.is_(True)))).all()))
                    due=[];reconciled=set()
                    for guild in guilds:
                        await self.discovery.catch_up(guild)
                        discovery_on=(await self.discovery.status(guild))['enabled']
                        for source in await self.sources(guild):
                            releases=await self.releases(guild,source['game'])
                            if (not releases and not (discovery_on and source['game']=='One Piece')) or not source['enabled']: continue
                            key=(guild,source['game'])
                            signature=digest([(r['id'],r['updated_at']) for r in releases])
                            changed=self.signatures.get(key)!=signature
                            if changed and key not in reconciled:
                                await self.reconcile(guild,source['game']);reconciled.add(key)
                            last=json.loads(source['last_json'])
                            retry_ready=not last.get('retry_at') or last['retry_at']<=utcnow().isoformat()
                            if source['next_due']<=utcnow().isoformat() or (changed and retry_ready): due.append(source)
                            # Mark after a successful source scan so a busy queue cannot lose new work.
                            if not changed: self.signatures[key]=signature
                    for source in sorted(due,key=lambda x:x['next_due'])[:2]:
                        try:
                            await self.scan(source['guild_id'],source['id'])
                            rows=await self.releases(source['guild_id'],source['game'])
                            self.signatures[(source['guild_id'],source['game'])]=digest([(r['id'],r['updated_at']) for r in rows])
                        except CatalogError: pass
                except asyncio.CancelledError: raise
                except Exception as exc:
                    self.state='ERROR';self.last_error=type(exc).__name__
                    LOG.error('LOTUS OFFICIAL WORKER ERROR | Type=%s',self.last_error)
                await asyncio.sleep(30)
        finally: self.state='STOPPED'
    def start(self,bot):
        if self.task is None or self.task.done():
            self.task=asyncio.create_task(self.run(bot),name='lotus-official-verification')
            print(f'LOTUS OFFICIAL VERIFIER | Version={VERSION} | Task=CREATED | StockAlerts=UNCHANGED',flush=True)
    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
