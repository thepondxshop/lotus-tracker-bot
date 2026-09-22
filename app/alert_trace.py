"""Read-only product/event/delivery diagnostics. Never fetches or publishes."""
from urllib.parse import urlsplit, urlunsplit
from sqlalchemy import select
from app.models import Store, StoreProduct, ProductEventRecord, Alert


def product_key(url):
    try:
        p=urlsplit(url)
        if p.scheme not in ('https','http') or not p.hostname: return None
        return (p.hostname.lower().removeprefix('www.'),p.path.rstrip('/'))
    except (TypeError,ValueError): return None


def product_url_aliases(url):
    key=product_key(url)
    if not key: return []
    host,path=key
    return [urlunsplit((scheme,prefix+host,path+slash,'',''))
            for scheme in ('https','http') for prefix in ('','www.') for slash in ('','/')]


async def lookup_store_product(session, store_name, url):
    # Bounded indexed-store query; canonical comparison avoids affiliate/variant params.
    stores=(await session.scalars(select(Store).where(Store.name==store_name))).all()
    if len(stores)!=1: return None
    aliases=product_url_aliases(url)
    if not aliases: return None
    from sqlalchemy import or_
    conditions=[StoreProduct.url==x for x in aliases]
    conditions += [StoreProduct.url.startswith(x+'?',autoescape=True) for x in aliases]
    rows=(await session.scalars(select(StoreProduct).where(StoreProduct.store_id==stores[0].id,or_(*conditions)).limit(3))).all()
    return rows[0] if len(rows)==1 else None


async def trace_product(sessions,store_id,url,channel_ids):
    from sqlalchemy import or_
    if not product_key(url): raise ValueError('Use the full retailer product URL.')
    async with sessions() as s:
        store=await s.get(Store,store_id)
        if not store: raise ValueError('Store ID not found.')
        if product_key('https://'+store.domain)[0]!=product_key(url)[0]: raise ValueError('Product URL does not belong to that store.')
        sp=await lookup_store_product(s,store.name,url)
        aliases=product_url_aliases(url)
        conditions=[ProductEventRecord.product_url==x for x in aliases]
        conditions += [ProductEventRecord.product_url.startswith(x+'?',autoescape=True) for x in aliases]
        events=(await s.scalars(select(ProductEventRecord).where(ProductEventRecord.store_name==store.name,or_(*conditions)).order_by(ProductEventRecord.id.desc()).limit(5))).all()
        deliveries=[]
        if sp and channel_ids:
            deliveries=(await s.scalars(select(Alert).where(Alert.store_id==store_id,Alert.product_id==sp.product_id,
                Alert.discord_channel_id.in_(channel_ids)).order_by(Alert.id.desc()).limit(5))).all()
        return {'store':store.name,'active':store.active,'health':store.health_status,
                'last_store_error':store.last_error,
                'product':None if not sp else {'id':sp.id,'in_stock':sp.in_stock,'status':sp.status,'last_seen':str(sp.last_seen_at),'variant_id':sp.variant_id},
                'events':[{'type':x.event_type,'at':str(x.created_at),'in_stock':x.in_stock} for x in events],
                'deliveries':[{'type':x.alert_type,'at':str(x.created_at),'channel':x.discord_channel_id,'message':x.discord_message_id} for x in deliveries]}
