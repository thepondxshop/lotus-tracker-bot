"""Release Radar 1.5.0-preview: read existing evidence and matches, never publish."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, case
from .service import Release, ReleaseSource, CatalogError, snapshot, positive_id
from .official import OfficialCheck
from .ingestion_store import RetailerLink
from .source_confidence import attach

VERSION = '1.5.0-preview'
PAGE_SIZE = 5
RETAILER_PAGE_SIZE = 3


def evidence_summary(check, now=None):
    """Recompute age on display; a previously fresh saved check can age."""
    now = now or datetime.now(timezone.utc)
    result = dict(check or {'state': 'PENDING', 'evidence': []})
    evidence = []
    for original in result.get('evidence', []):
        row = dict(original)
        try:
            fetched = datetime.fromisoformat(row['fetched_at'])
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            old = fetched < now - timedelta(days=2)
        except (KeyError, TypeError, ValueError):
            old = True
        row['stale'] = bool(row.get('stale') or row.get('last_fetch_error') or old)
        evidence.append(row)
    result['evidence'] = evidence
    result['date_review'] = any(
        e.get('state') == 'DATE_REVIEW' or any(
            key in issue for key in ('DATE_CONFLICT', 'DATE_DIFFERS', 'SOURCES_DISAGREE', 'MULTIPLE_RELEASE_WINDOWS')
        ) for e in evidence for issue in (e.get('issues') or [''])
    )
    return result


class ReleaseRadar:
    def __init__(self, verifier):
        self.verifier = verifier
        self.catalog = verifier.catalog

    async def page(self, guild, game=None, page=1):
        positive_id(guild, 'Server ID')
        self.catalog._page(page)
        await self.verifier.ensure()
        conditions = [Release.guild_id == guild, Release.status != 'ARCHIVED']
        if game:
            conditions.append(func.lower(Release.game) == game.lower())
        today = datetime.now(timezone.utc).date()
        async with self.catalog.sessions() as session:
            total = await session.scalar(select(func.count()).select_from(Release).where(*conditions))
            pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(page, pages)
            # Future exact dates first, then undated leads, then past dated records.
            order = case((Release.release_date >= today, 0), (Release.release_date.is_(None), 1), else_=2)
            rows = (await session.scalars(select(Release).where(*conditions).order_by(
                order, Release.release_date, Release.id.desc()
            ).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE))).all()
            ids = [r.id for r in rows]
            checks = {r.release_id: r for r in (await session.scalars(select(OfficialCheck).where(
                OfficialCheck.guild_id == guild, OfficialCheck.release_id.in_(ids)
            ))).all()} if ids else {}
            kinds = {}
            if ids:
                for rid, kind in (await session.execute(select(ReleaseSource.release_id, ReleaseSource.kind).where(
                    ReleaseSource.release_id.in_(ids)
                ).distinct())).all():
                    kinds.setdefault(rid, set()).add(kind)
            counts = {}
            if ids:
                from app.models import StoreProduct, Store
                counts = dict((await session.execute(select(RetailerLink.release_id, func.count()).join(
                    StoreProduct, StoreProduct.id == RetailerLink.store_product_id
                ).join(Store, Store.id == StoreProduct.store_id).where(
                    RetailerLink.guild_id == guild, RetailerLink.release_id.in_(ids), RetailerLink.state == 'MATCHED'
                ).group_by(RetailerLink.release_id))).all())
            items = []
            classified = {r['id']: r for r in await attach(session, rows)}
            for row in rows:
                check = checks.get(row.id)
                items.append({'release': classified[row.id], 'kinds': sorted(kinds.get(row.id, [])),
                              'check': evidence_summary(json.loads(check.result_json) if check else None),
                              'checked_at': snapshot(check)['checked_at'] if check else None,
                              'retailer_count': counts.get(row.id, 0)})
            return {'items': items, 'page': page, 'pages': pages, 'total': total,
                    'has_more': page < pages, 'game': game}

    async def detail(self, guild, release_id, page=1):
        positive_id(guild, 'Server ID')
        self.catalog._page(page)
        await self.verifier.ensure()
        from app.models import StoreProduct, Store
        async with self.catalog.sessions() as session:
            row = await self.catalog._release(session, guild, release_id)
            check = await session.scalar(select(OfficialCheck).where(
                OfficialCheck.guild_id == guild, OfficialCheck.release_id == release_id))
            kinds = (await session.scalars(select(ReleaseSource.kind).where(
                ReleaseSource.release_id == release_id).distinct())).all()
            query = select(RetailerLink, StoreProduct, Store).join(
                StoreProduct, StoreProduct.id == RetailerLink.store_product_id
            ).join(Store, Store.id == StoreProduct.store_id).where(
                RetailerLink.guild_id == guild, RetailerLink.release_id == release_id,
                RetailerLink.state == 'MATCHED')
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            pages = max(1, (total + RETAILER_PAGE_SIZE - 1) // RETAILER_PAGE_SIZE)
            page = min(page, pages)
            retailers = []
            for link, product, store in (await session.execute(query.order_by(Store.name, StoreProduct.id).offset(
                (page - 1) * RETAILER_PAGE_SIZE).limit(RETAILER_PAGE_SIZE))).all():
                retailers.append({'link': snapshot(link), 'product': snapshot(product), 'store': snapshot(store)})
            return {'release': (await attach(session, [row]))[0], 'kinds': kinds,
                    'check': evidence_summary(json.loads(check.result_json) if check else None),
                    'checked_at': snapshot(check)['checked_at'] if check else None,
                    'retailers': retailers, 'total': total, 'page': page, 'pages': pages, 'has_more': page < pages}
