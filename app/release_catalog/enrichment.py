"""Admin-attested source enrichment; no confirmation/date/stock writes."""
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .service import ReleaseSource, CatalogError, clean, identity, snapshot, utcnow, positive_id

async def enrich(store,guild,actor,release_id,source_id,reviewed,note,**fields):
    if reviewed is not True:
        raise CatalogError('Review the source and use reviewed:True only for fields it explicitly supports.')
    positive_id(actor,'Administrator ID');positive_id(source_id,'Source ID')
    note=clean(note,'Evidence note',1000)
    allowed={'region','language','cards_per_pack','packs_per_box','boxes_per_case'}
    changes={k:v for k,v in fields.items() if v is not None}
    if not changes or set(changes)-allowed:raise CatalogError('Supply at least one supported edition or packaging field.')
    for key,value in changes.items():
        if key in ('region','language'):changes[key]=clean(value,key,40)
        elif type(value) is not int or not 1<=value<=10000:raise CatalogError('Packaging counts must be integers from 1 to 10000.')
    await store.ensure_schema()
    try:
        async with store.writes,store.sessions() as s,s.begin():
            await store.guild_lock(s,guild)
            row=await store.catalog._release(s,guild,release_id,lock=True)
            if row.status=='ARCHIVED':raise CatalogError('Archived release: no enrichment applied.')
            source=await s.scalar(select(ReleaseSource).where(ReleaseSource.id==source_id,ReleaseSource.release_id==row.id))
            if not source or source.kind not in ('PUBLISHER','DISTRIBUTOR') or not source.url:
                raise CatalogError('Use a publisher/distributor evidence ID attached to this release.')
            if row.status=='CONFIRMED' and any(k in changes and changes[k]!=getattr(row,k) for k in ('region','language')):
                raise CatalogError('Confirmed edition changes require the existing confirmation review workflow.')
            before=snapshot(row)
            for key,value in changes.items():setattr(row,key if key in ('region','language') else 'reported_'+key,value)
            row.identity_key=identity(row.game,row.title,row.region,row.language,row.product_format)
            row.updated_at=utcnow()
            # Immutable evidence records the administrator's attestation, not an
            # automated claim that the web page was fetched or independently verified.
            evidence=store.catalog._source(row,actor,source.kind,'Admin-reviewed catalog enrichment',source.url,
                json.dumps({'catalog_enrichment_v1':changes,'parent_source_id':source.id,'review_note':note}))
            existing=await s.scalar(select(ReleaseSource).where(ReleaseSource.release_id==row.id,ReleaseSource.fingerprint==evidence.fingerprint))
            if existing is None:s.add(evidence)
            await s.flush()
            store.catalog._audit(s,row,actor,'EVIDENCE_ENRICHED',{'before':before,'after':snapshot(row),'source_id':source.id,'review_note':note,'fields':changes})
            return snapshot(row)
    except IntegrityError:
        raise CatalogError('This correction conflicts with another catalog identity. No changes were saved.') from None
