"""Local retailer review and audited rechecks; never fetch or publish alerts."""
import json
from sqlalchemy import select, func, or_
from .service import CatalogError, positive_id, utcnow
from .ingestion_store import RetailerLink
from .radar_diagnostics import related, evaluate_offer
from .extraction import scope

LIMIT = 1000


def missing(row):
    return [key for key in ('region', 'language', 'product_format')
            if scope(getattr(row, key)) == 'unknown']


class RetailerReview:
    def __init__(self, store):
        self.store, self.catalog = store, store.catalog

    async def pending(self, guild, game=None, page=1):
        from app.models import Store, StoreProduct, Product
        positive_id(guild, 'Server ID'); self.catalog._page(page)
        await self.store.ensure_schema()
        async with self.store.sessions() as s:
            releases, sources = await self.store.catalog_rows(s, guild)
            releases = [r for r in releases if r.status != 'ARCHIVED']
            query = select(StoreProduct, Product, Store).join(Product, Product.id == StoreProduct.product_id).join(Store, Store.id == StoreProduct.store_id).where(Store.active.is_(True))
            if game:
                query = query.where(func.lower(Product.game) == game.lower())
            rows = (await s.execute(query.order_by(StoreProduct.id.desc()).limit(LIMIT + 1))).all()
            limited = len(rows) > LIMIT
            rows = rows[:LIMIT]
            ids = [o.id for o, p, t in rows]
            links = {l.store_product_id: l for l in (await s.scalars(select(RetailerLink).where(RetailerLink.guild_id == guild, RetailerLink.store_product_id.in_(ids)))).all()} if ids else {}
            items = []
            for offer, product, shop in rows:
                candidates = [r for r in releases if r.game.lower() == product.game.lower() and related(r, product, offer)]
                if not candidates:
                    continue
                found, reason = evaluate_offer(offer, product, shop, releases, sources)
                saved = links.get(offer.id)
                if found and saved and saved.state == 'MATCHED' and saved.release_id == found.id:
                    continue
                items.append({'offer_id': offer.id, 'title': product.name, 'store': shop.name,
                    'url': offer.url, 'reason': reason or ('READY_TO_SAVE' if found else 'NO_COMPATIBLE_RELEASE'),
                    'candidates': [{'id': r.id, 'missing': missing(r)} for r in candidates],
                    'saved': saved.state if saved else 'NO_SAVED_DECISION',
                    'checked_at': saved.checked_at.isoformat() if saved else None})
            pages = max(1, (len(items) + 3) // 4); page = min(page, pages)
            return {'items': items[(page-1)*4:page*4], 'page': page, 'pages': pages,
                    'total': len(items), 'has_more': page < pages, 'examined': len(rows), 'limited': limited}

    async def recheck(self, guild, actor, release_id):
        from app.models import Store, StoreProduct, Product
        positive_id(guild, 'Server ID'); positive_id(actor, 'Administrator ID')
        await self.store.ensure_schema()
        async with self.store.writes, self.store.sessions() as s, s.begin():
            await self.store.guild_lock(s, guild)
            target = await self.catalog._release(s, guild, release_id, lock=True)
            if target.status == 'ARCHIVED':
                raise CatalogError('Archived releases cannot be rechecked.')
            releases, sources = await self.store.catalog_rows(s, guild)
            linked = select(RetailerLink.store_product_id).where(RetailerLink.guild_id == guild, RetailerLink.release_id == release_id)
            rows = (await s.execute(select(StoreProduct, Product, Store).join(Product, Product.id == StoreProduct.product_id).join(Store, Store.id == StoreProduct.store_id).where(or_(func.lower(Product.game) == target.game.lower(), StoreProduct.id.in_(linked))).order_by(StoreProduct.id).limit(LIMIT + 1))).all()
            if len(rows) > LIMIT:
                raise CatalogError('This recheck exceeds 1,000 saved offers. No decisions changed; use the background matcher for this game.')
            links = {l.store_product_id: l for l in (await s.scalars(select(RetailerLink).where(RetailerLink.guild_id == guild, RetailerLink.store_product_id.in_([o.id for o,p,t in rows])))).all()}
            stats = {'release_id': release_id, 'examined': len(rows), 'checked': 0, 'matched': 0, 'review': 0, 'unmatched': 0, 'disabled': 0}
            changes = []
            for offer, product, shop in rows:
                saved = links.get(offer.id)
                if not related(target, product, offer) and not (saved and saved.release_id == release_id):
                    continue
                if not shop.active:
                    stats['disabled'] += 1
                    continue
                found, reason = evaluate_offer(offer, product, shop, releases, sources)
                state = 'MATCHED' if found and found.status != 'ARCHIVED' else ('REVIEW' if reason else 'UNMATCHED')
                before = {'state': saved.state, 'release_id': saved.release_id} if saved else None
                if saved is None:
                    saved = RetailerLink(guild_id=guild, store_product_id=offer.id)
                    s.add(saved)
                saved.state = state
                saved.release_id = found.id if state == 'MATCHED' else None
                saved.checked_at = utcnow()
                saved.details_json = json.dumps({'title': product.name, 'store': shop.name, 'url': offer.url,
                    'reason': reason, 'stock_state_used': False, 'reviewed_for_release_id': release_id})
                changes.append({'offer_id': offer.id, 'before': before, 'state': state, 'release_id': saved.release_id, 'reason': reason})
                stats['checked'] += 1; stats[state.lower()] += 1
            self.catalog._audit(s, target, actor, 'RETAILER_RECHECK', {'review_note': 'Reevaluated saved offers with existing matching rules; no live stock check or alert.', 'stats': stats, 'decisions': changes})
            return stats
