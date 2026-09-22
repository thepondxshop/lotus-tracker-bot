"""Bounded, read-only retailer diagnosis and audited UNKNOWN format cleanup."""
import json
import re
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .service import Release, CatalogError, identity, snapshot, positive_id, utcnow
from .ingestion_store import RetailerLink, match
from .extraction import Candidate, CODE, canonical_url, code, languages, norm, product_format, scope

VERSION = '1.5.2-preview'


def related(row, product, offer):
    """Identity evidence only; sharing a game is not a candidate match."""
    codes = {code(m[0]) for m in CODE.finditer(product.name)}
    target_codes = {code(m[0]) for m in CODE.finditer(row.title)}
    if code(row.set_code):
        target_codes.add(code(row.set_code))
    sku = bool(offer.sku and re.search(
        rf'(?i)\bSKU["\s]*:\s*["\s]*{re.escape(offer.sku)}(?![A-Z0-9])', row.reported_details))
    return bool(norm(row.title) == norm(product.name) or codes & target_codes or sku)


def evaluate_offer(offer, product, shop, releases, sources):
    """Mirror the existing batch match guards; never persist diagnostic guesses."""
    codes = {code(m[0]) for m in CODE.finditer(product.name)}
    langs = languages(product.name)
    fmt, typed = product_format(product.name), product_format(product.product_type or '')
    try:
        url = canonical_url(offer.url)
    except CatalogError:
        return None, 'INVALID_RETAILER_URL'
    c = Candidate(url, product.name, product.game, sku=offer.sku,
                  set_code=next(iter(codes)) if len(codes)==1 else None,
                  product_format=fmt if fmt!='UNKNOWN' else typed,
                  region=product.region or shop.region or 'UNKNOWN',
                  language=product.language or (next(iter(langs)) if len(langs)==1 else 'UNKNOWN'))
    row, issue = match(c, releases, sources, True)
    if len(codes)>1 or len(langs)>1:
        row, issue = None, 'MULTIPLE_EDITIONS'
    if fmt!='UNKNOWN' and typed!='UNKNOWN' and fmt!=typed:
        row, issue = None, 'RETAILER_FORMAT_CONFLICT'
    if len(langs)==1 and scope(c.language)!=scope(next(iter(langs))):
        row, issue = None, 'RETAILER_LANGUAGE_CONFLICT'
    return row, issue


class RadarDiagnostics:
    def __init__(self, store):
        self.store, self.catalog = store, store.catalog

    async def formats(self, guild, actor, game=None, apply=False):
        positive_id(guild, 'Server ID'); positive_id(actor, 'Administrator ID')
        await self.store.ensure_schema()
        # Same guild lock as ingestion; uniqueness guard also protects competing writers.
        async with self.store.writes, self.store.sessions() as s, s.begin():
            if apply:
                await self.store.guild_lock(s, guild)
            conditions=[Release.guild_id==guild, Release.product_format=='UNKNOWN', Release.status!='ARCHIVED']
            if game:
                conditions.append(func.lower(Release.game)==game.lower())
            query=select(Release).where(*conditions).order_by(Release.id)
            if apply:
                query=query.with_for_update()
            rows=(await s.scalars(query)).all()
            changes=[]; unresolved=0; supported=0
            for row in rows:
                fmt=product_format(row.title)
                if fmt=='UNKNOWN':
                    unresolved+=1; continue
                key=identity(row.game,row.title,row.region,row.language,fmt)
                duplicate=await s.scalar(select(Release.id).where(
                    Release.guild_id==guild,Release.identity_key==key,Release.id!=row.id))
                status='IDENTITY_CONFLICT' if duplicate else 'PROPOSED'
                if apply and not duplicate:
                    before=snapshot(row)
                    try:
                        async with s.begin_nested():
                            row.product_format=fmt; row.identity_key=key; row.updated_at=utcnow()
                            self.catalog._audit(s,row,actor,'FORMAT_CLEANUP',{
                                'before':before,'after':snapshot(row),
                                'reason':'Title-based UNKNOWN format cleanup; no date or edition inference',
                                'parser_version':VERSION})
                            await s.flush()
                        status='UPDATED'
                    except IntegrityError:
                        # Refresh after rollback; never leave expired ORM fields to implicit IO.
                        await s.refresh(row)
                        status='IDENTITY_CONFLICT'
                changes.append({'id':row.id,'title':row.title,'format':fmt,'state':status})
                if status in ('PROPOSED','UPDATED'):
                    supported+=1
                if supported>=50:
                    break
            return {'items':changes,'apply':apply,'unknown_total':len(rows),'unresolved_examined':unresolved,
                    'limited':supported==50}

    async def diagnose(self,guild,release_id,page=1):
        from app.models import Store, StoreProduct, Product
        positive_id(guild,'Server ID');self.catalog._page(page)
        await self.store.ensure_schema()
        async with self.store.sessions() as s:
            target=await self.catalog._release(s,guild,release_id)
            releases,sources=await self.store.catalog_rows(s,guild)
            # Bounded local inventory inspection. Explicitly report its limit and do not
            # infer absence from a partial search. No retailer HTTP or queue work.
            rows=(await s.execute(select(StoreProduct,Product,Store).join(Product,Product.id==StoreProduct.product_id)
                .join(Store,Store.id==StoreProduct.store_id).where(func.lower(Product.game)==target.game.lower())
                .order_by(StoreProduct.id.desc()).limit(1001))).all()
            limited=len(rows)>1000;rows=rows[:1000]
            candidates=[(o,p,t) for o,p,t in rows if related(target,p,o)]
            ids=[o.id for o,p,t in candidates]
            links={l.store_product_id:l for l in (await s.scalars(select(RetailerLink).where(
                RetailerLink.guild_id==guild,RetailerLink.store_product_id.in_(ids)))).all()} if ids else {}
            items=[]
            for offer,product,shop in candidates:
                found,reason=evaluate_offer(offer,product,shop,releases,sources)
                saved=links.get(offer.id)
                if not shop.active:
                    current='STORE_DISABLED'
                elif found and found.id==release_id:
                    current='MATCH_ELIGIBLE_NOW'
                elif found:
                    current='MATCHES_OTHER_RELEASE'
                else:
                    current=reason or 'NO_COMPATIBLE_RELEASE (check format, region, language and identity)'
                items.append({'store':shop.name,'title':product.name,'url':offer.url,'product_id':offer.id,
                              'current':current,'other_release':found.id if found and found.id!=release_id else None,
                              'saved_state':saved.state if saved else 'NO_SAVED_DECISION',
                              'saved_reason':json.loads(saved.details_json).get('reason') if saved else None,
                              'checked_at':snapshot(saved)['checked_at'] if saved else None})
            pages=max(1,(len(items)+3)//4); page=min(page,pages)
            return {'release':snapshot(target),'items':items[(page-1)*4:page*4], 'total':len(items),
                    'page':page,'pages':pages,'has_more':page<pages,'examined':len(rows),'limited':limited}


    async def unknowns(self, guild, game=None, page=1):
        positive_id(guild, 'Server ID'); self.catalog._page(page)
        await self.store.ensure_schema()
        async with self.store.sessions() as s:
            conditions = [Release.guild_id == guild, Release.status != 'ARCHIVED', Release.product_format == 'UNKNOWN']
            if game:
                conditions.append(func.lower(Release.game) == game.lower())
            total = await s.scalar(select(func.count()).select_from(Release).where(*conditions))
            pages = max(1, (total + 3) // 4); page = min(page, pages)
            rows = (await s.scalars(select(Release).where(*conditions).order_by(Release.id)
                                   .offset((page-1)*4).limit(4))).all()
            return {'items': [{'release': snapshot(r), 'suggested': product_format(r.title)} for r in rows],
                    'total': total, 'page': page, 'pages': pages, 'has_more': page < pages, 'game': game}

    async def offers(self, guild, release_id, page=1):
        """Inspect all saved same-game offers, including non-candidates and disabled stores.

        Offer inventory is shared by the existing monitor; release and saved decisions
        are scoped to the current guild. This is an admin-only inspection, not a match.
        """
        from app.models import Store, StoreProduct, Product
        positive_id(guild, 'Server ID'); self.catalog._page(page)
        await self.store.ensure_schema()
        async with self.store.sessions() as s:
            target = await self.catalog._release(s, guild, release_id)
            query = select(StoreProduct, Product, Store).join(Product, Product.id == StoreProduct.product_id).join(
                Store, Store.id == StoreProduct.store_id).where(func.lower(Product.game) == target.game.lower())
            total = await s.scalar(select(func.count()).select_from(query.subquery()))
            pages = max(1, (total + 2) // 3); page = min(page, pages)
            rows = (await s.execute(query.order_by(StoreProduct.id).offset((page-1)*3).limit(3))).all()
            ids = [o.id for o,p,t in rows]
            links = {l.store_product_id:l for l in (await s.scalars(select(RetailerLink).where(
                RetailerLink.guild_id == guild, RetailerLink.store_product_id.in_(ids)))).all()} if ids else {}
            items = []
            for offer, product, shop in rows:
                decision = links.get(offer.id)
                items.append({'offer': snapshot(offer), 'product': snapshot(product), 'store': snapshot(shop),
                              'identity_candidate': related(target, product, offer),
                              'title_format': product_format(product.name),
                              'type_format': product_format(product.product_type or ''),
                              'saved': snapshot(decision) if decision else None})
            return {'release': snapshot(target), 'items': items, 'total': total,
                    'page': page, 'pages': pages, 'has_more': page < pages}
