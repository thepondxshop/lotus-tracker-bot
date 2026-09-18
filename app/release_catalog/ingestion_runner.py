"""A separate bounded worker; never publishes events or changes stock monitors."""
import asyncio
import json
import logging
import time
from urllib.parse import parse_qsl,urlsplit
from . import VERSION
from .extraction import Candidate,canonical_url,extract,is_product,same_site,url_key
from .public_http import PublicHTTP,FetchError
from .service import CatalogError,utcnow

LOG=logging.getLogger(__name__)
STOP_ERRORS={'RATE_LIMITED','ACCESS_DENIED','CROSS_SITE_REDIRECT'}
def allowed_listing(seed,link):
    if not same_site(seed,link) or is_product(seed): return False
    a,b=urlsplit(seed),urlsplit(link)
    if a.path.lower().endswith(('.xml','.rss','.atom')): return b.path.lower().endswith(('.xml','.rss','.atom'))
    filters=lambda query:{k.lower():v for k,v in parse_qsl(query) if v and k.lower() not in ('page','p','offset','start')}
    return a.path.rstrip('/')==b.path.rstrip('/') and filters(a.query)==filters(b.query)

class IngestionRunner:
    def __init__(self,store,http_factory=PublicHTTP,budget=180,listing_limit=8):
        self.store=store;self.http_factory=http_factory;self.budget=budget;self.listing_limit=listing_limit
        self.lock=asyncio.Lock();self.task=None;self.state='NOT_STARTED';self.last_tick=None;self.last_error=None
    def start(self,bot):
        if self.task is None or self.task.done():
            self.state='STARTING';self.task=asyncio.create_task(self.run(bot),name='lotus-release-ingestion')
            print(f'LOTUS RELEASE INGESTION | Version={VERSION} | Task=CREATED | Alerts=OFF',flush=True)
        return self.task
    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
        self.state='STOPPED'
    async def status(self,guild):
        sources=await self.store.watches(guild)
        return {'version':VERSION,'worker':self.state,'last_tick':self.last_tick,'last_error':self.last_error,'sources':len(sources),'enabled_sources':sum(w['enabled'] for w in sources),'scan_in_progress':self.lock.locked()}
    async def scan(self,guild,wid):
        if self.lock.locked(): raise CatalogError('Another source scan is running. This watch remains scheduled; try again shortly.')
        async with self.lock:
            w,token=await self.store.claim(guild,wid);seed=canonical_url(w['url']);settings=json.loads(w['scope_json'])
            started=utcnow()
            cursor=json.loads(w['cursor_json']);queue=[x for x in cursor.get('queue',[]) if allowed_listing(seed,x)][:200]
            seen=set(cursor.get('seen',[])) if queue else set();seen.add(seed)
            stats={'pages_ok':0,'products_seen':0,'created':0,'linked':0,'unchanged':0,'review':0,'errors':0}
            error=None;supported=False;done=set();inflight=None
            try:
                async with asyncio.timeout(self.budget),self.http_factory() as http:
                    todo=[seed];visited=set()
                    while todo and len(visited)<self.listing_limit:
                        url=todo.pop(0);inflight=url;visited.add(url)
                        try:
                            page=await http.get(url,seed);stats['pages_ok']+=1
                            doc=extract(page.url,page.text,settings,page.content_type)
                            supported=supported or doc.supported or bool(doc.product_links)
                            if doc.issues: error=doc.issues[0];stats['errors']+=1
                            products=doc.products
                            if is_product(seed) and len(products)>1: products=[p for p in products if url_key(p.url)==url_key(page.url)]
                            stats['products_seen']+=len(products)
                            stats['unchanged']+=await self.store.stage(w,token,products)
                            if not is_product(seed):
                                await self.store.queue(w,token,doc.product_links)
                                for link in doc.listing_links:
                                    if link not in seen and allowed_listing(seed,link):
                                        if len(queue)>=200 or len(seen)>=2000: error='PAGINATION_LIMIT';continue
                                        seen.add(link);queue.append(link)
                        except FetchError as exc:
                            error=exc.code;stats['errors']+=1
                            if url!=seed: queue.append(url)
                            if error in STOP_ERRORS: break
                        inflight=None
                        if is_product(seed): break
                        if queue and len(visited)<self.listing_limit:
                            url=queue.pop(0)
                            if url in visited: queue.append(url);break
                            todo.append(url)
                    if error not in STOP_ERRORS:
                        fetches=0
                        for item in await self.store.pending(wid,started):
                            if item['pending_json'] and item['pending_policy']==w['revision']:
                                candidates=[Candidate(**json.loads(item['pending_json']))]
                            else:
                                if is_product(seed) or fetches>=20: continue
                                fetches+=1
                                try:
                                    page=await http.get(item['url'],seed);stats['pages_ok']+=1
                                    doc=extract(page.url,page.text,settings,page.content_type)
                                    candidates=doc.products
                                    if len(candidates)>1: candidates=[p for p in candidates if url_key(p.url)==url_key(page.url)]
                                    if not candidates:
                                        await self.store.fetched(w,token,item['url'],doc.issues[0] if doc.issues else 'NO_SUPPORTED_PRODUCT');continue
                                except FetchError as exc:
                                    await self.store.fetched(w,token,item['url'],exc.code);error=exc.code;stats['errors']+=1
                                    if error in STOP_ERRORS: break
                                    continue
                            for c in candidates:
                                if url_key(c.url) in done: continue
                                result=await self.store.apply(w,token,c);done.add(url_key(c.url));stats[result['state'].lower()]+=1
                                if result['issues'] and result['state']!='REVIEW': stats['review']+=1
                            if len(candidates)==1: await self.store.fetched(w,token,item['url'],alias=candidates[0].url)
                    if not supported and not error: error='NO_SUPPORTED_PRODUCT_DATA'
            except TimeoutError: error='SCAN_BUDGET_REACHED'
            except asyncio.CancelledError: error='SCAN_CANCELLED';raise
            except Exception as exc:
                error=str(exc) if isinstance(exc,CatalogError) and str(exc).isupper() else 'SCAN_ERROR_'+type(exc).__name__;stats['errors']+=1
                LOG.error('LOTUS RELEASE INGESTION ERROR | WatchID=%s | Type=%s',wid,type(exc).__name__)
            finally:
                if inflight and inflight!=seed and inflight not in queue: queue.insert(0,inflight)
                await self.store.finish(w,token,stats,{'queue':queue[:200],'seen':sorted(seen)[:2000]},error)
            LOG.info('LOTUS RELEASE INGESTION RESULT | Version=%s | WatchID=%s | Created=%s | Linked=%s | Review=%s | Error=%s',VERSION,wid,stats['created'],stats['linked'],stats['review'],error or 'NONE')
            return {'watch_id':wid,'stats':stats,'error':error,'remaining_pages':len(queue)}
    async def run(self,bot):
        next_bridge=0.0;index=0
        try:
            await bot.wait_until_ready()
            while not bot.is_closed():
                try:
                    await self.store.ensure_schema();self.state='RUNNING';self.last_error=None;self.last_tick=utcnow().isoformat()
                    for w in await self.store.due():
                        if self.lock.locked(): break
                        try: await self.scan(w['guild_id'],w['id'])
                        except CatalogError: continue
                    if time.monotonic()>=next_bridge:
                        guilds=await self.store.active_guilds()
                        if guilds:
                            await self.store.match_retailers(guilds[index%len(guilds)]);index+=1
                        next_bridge=time.monotonic()+60
                except Exception as exc:
                    self.state='ERROR';self.last_error=type(exc).__name__
                    LOG.error('LOTUS RELEASE INGESTION WORKER ERROR | Type=%s',self.last_error)
                await asyncio.sleep(30)
        finally: self.state='STOPPED'

def start_release_ingestion(bot):
    runner=getattr(bot,'release_ingestion',None)
    if runner: return runner.start(bot)
async def stop_release_ingestion(bot):
    runner=getattr(bot,'release_ingestion',None)
    if runner: await runner.stop()
