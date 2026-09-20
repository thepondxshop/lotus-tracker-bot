"""A separate bounded worker; never publishes events or changes stock monitors."""
import asyncio
import json
import logging
import time
from urllib.parse import parse_qsl,urlsplit,urlencode,urlunsplit
from . import VERSION
from .extraction import Candidate,canonical_url,extract,is_product,same_site,url_key
from .public_http import PublicHTTP,FetchError
from .service import CatalogError,utcnow
from .distributors import listing_allowed, ADAPTER_VERSION, article_url, phd_sku_fragment, hostname, product_url

def selected_products(doc, requested, fetched):
    if hostname(fetched)=='phdgames.com' and product_url(fetched):
        rows=[p for p in doc.products if p.extractor=='PHD_PUBLIC_ANNOUNCEMENT'
              and url_key(article_url(p.url))==url_key(article_url(fetched))]
        if phd_sku_fragment(requested):
            rows=[p for p in rows if phd_sku_fragment(p.url)==phd_sku_fragment(requested)]
        return rows
    return [p for p in doc.products if url_key(p.url)==url_key(fetched)] if len(doc.products)>1 else doc.products

LOG=logging.getLogger(__name__)

def capture_diagnostics(stats,doc):
    """Bounded latest-scan details, deduplicated across cached article reads."""
    rows=stats.setdefault('diagnostics',[])
    for detail in doc.diagnostics:
        if detail in rows: continue
        if len(rows)>=20:
            stats['diagnostics_truncated']=True
            break
        rows.append(detail)
        LOG.info('LOTUS RELEASE PARSE DIAGNOSTIC | %s',json.dumps(detail,ensure_ascii=True))
STOP_ERRORS={'RATE_LIMITED','ACCESS_DENIED','CROSS_SITE_REDIRECT','ACCESS_CHALLENGE','LOGIN_REQUIRED'}
def listing_key(url):
    """Deduplicate GTS page aliases without changing the URL we request."""
    value=canonical_url(url)
    p=urlsplit(value)
    if (p.hostname or '').removeprefix('www.')!='gtsdistribution.com':
        return value
    params=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
            if v and not (k.lower()=='page' and v=='1')]
    return urlunsplit((p.scheme,'gtsdistribution.com',p.path,urlencode(sorted(params)),''))

def record_games(stats,products,seen):
    for product in products:
        key=url_key(product.url)
        if key not in seen:
            seen.add(key)
            stats['products_seen']+=1
            counts=stats['games_seen']
            counts[product.game]=counts.get(product.game,0)+1

def allowed_listing(seed,link):
    if not same_site(seed,link) or is_product(seed): return False
    distributor_policy=listing_allowed(seed,link)
    if distributor_policy is not None: return distributor_policy
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
        return {'version':VERSION,'distributor_adapters':ADAPTER_VERSION,'worker':self.state,'last_tick':self.last_tick,'last_error':self.last_error,'sources':len(sources),'enabled_sources':sum(w['enabled'] for w in sources),'scan_in_progress':self.lock.locked()}
    async def scan(self,guild,wid):
        if self.lock.locked(): raise CatalogError('Another source scan is running. This watch remains scheduled; try again shortly.')
        async with self.lock:
            w,token=await self.store.claim(guild,wid);seed=canonical_url(w['url']);settings=json.loads(w['scope_json'])
            started=utcnow()
            cursor=json.loads(w['cursor_json']);queue=[];queued=set()
            for link in cursor.get('queue',[]):
                if not allowed_listing(seed,link): continue
                key=listing_key(link)
                if key==listing_key(seed) or key in queued: continue
                if len(queue)>=200: break
                queue.append(link);queued.add(key)
            seen={listing_key(x) for x in cursor.get('seen',[])} if queue else set()
            seen.add(listing_key(seed))
            stats={'pages_ok':0,'products_seen':0,'created':0,'linked':0,'unchanged':0,'review':0,'errors':0,'games_seen':{}}
            game_products=set()
            error=None;supported=False;done=set();inflight=None
            try:
                async with asyncio.timeout(self.budget),self.http_factory() as http:
                    todo=[seed];visited=set();article_cache={}
                    while todo and len(visited)<self.listing_limit:
                        url=todo.pop(0);inflight=url;visited.add(listing_key(url))
                        try:
                            page=await http.get(article_url(url) if phd_sku_fragment(url) else url,seed);stats['pages_ok']+=1
                            doc=extract(page.url,page.text,settings,page.content_type)
                            capture_diagnostics(stats,doc)
                            supported=supported or doc.supported or bool(doc.product_links)
                            if doc.issues: error=doc.issues[0];stats['errors']+=1
                            if error in STOP_ERRORS: break
                            products=doc.products
                            if is_product(seed): products=selected_products(doc,seed,page.url)
                            record_games(stats,products,game_products)
                            stats['unchanged']+=await self.store.stage(w,token,products)
                            if not is_product(seed):
                                await self.store.queue(w,token,doc.product_links)
                                for link in doc.listing_links:
                                    if listing_key(link) not in seen and allowed_listing(seed,link):
                                        if len(queue)>=200 or len(seen)>=2000: error='PAGINATION_LIMIT';continue
                                        seen.add(listing_key(link));queue.append(link)
                        except FetchError as exc:
                            error=exc.code;stats['errors']+=1
                            if url!=seed: queue.append(url)
                            if error in STOP_ERRORS: break
                        inflight=None
                        if is_product(seed): break
                        if queue and len(visited)<self.listing_limit:
                            url=queue.pop(0)
                            if listing_key(url) in visited: queue.append(url);break
                            todo.append(url)
                    if error not in STOP_ERRORS:
                        fetches=0
                        for item in await self.store.pending(wid,started):
                            if item['pending_json'] and item['pending_policy']==w['revision']:
                                candidates=[Candidate(**json.loads(item['pending_json']))]
                            else:
                                if is_product(seed): continue
                                request_url=article_url(item['url']) if phd_sku_fragment(item['url']) else item['url']
                                cached=article_cache.get(request_url)
                                if not cached and fetches>=20: continue
                                try:
                                    if cached:
                                        page,doc=cached
                                    else:
                                        fetches+=1
                                        page=await http.get(request_url,seed);stats['pages_ok']+=1
                                        doc=extract(page.url,page.text,settings,page.content_type)
                                        if hostname(page.url)=='phdgames.com' and product_url(page.url):
                                            article_cache[request_url]=(page,doc)
                                    capture_diagnostics(stats,doc)
                                    if doc.issues:
                                        error=doc.issues[0];stats['errors']+=1
                                    candidates=selected_products(doc,item['url'],page.url)
                                    if not candidates:
                                        await self.store.fetched(w,token,item['url'],doc.issues[0] if doc.issues else 'NO_SUPPORTED_PRODUCT')
                                        if error in STOP_ERRORS: break
                                        continue
                                except FetchError as exc:
                                    await self.store.fetched(w,token,item['url'],exc.code);error=exc.code;stats['errors']+=1
                                    if error in STOP_ERRORS: break
                                    continue
                            record_games(stats,candidates,game_products)
                            for c in candidates:
                                if url_key(c.url) in done: continue
                                result=await self.store.apply(w,token,c);done.add(url_key(c.url));stats[result['state'].lower()]+=1
                                if result['issues'] and result['state']!='REVIEW': stats['review']+=1
                            if len(candidates)==1: await self.store.fetched(w,token,item['url'],alias=candidates[0].url)
                            elif candidates: await self.store.fetched(w,token,item['url'])
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
