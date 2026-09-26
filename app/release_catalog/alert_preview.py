"""Private, read-only message previews built solely from saved observations."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from .service import CatalogError, ReleaseSource, snapshot
from .ingestion_store import RetailerLink
from .radar_diagnostics import evaluate_offer
from .extraction import scope
from .source_confidence import confidence


def observation_age(value, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        at = datetime.fromisoformat(value) if isinstance(value, str) else value
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        age = now - at
        return age.total_seconds() if age >= timedelta(0) else None
    except (TypeError, ValueError, AttributeError):
        return None


async def build_preview(radar, store, guild, release_id, kind='RELEASE', store_product_id=None):
    if kind not in ('RELEASE', 'PREORDER'):
        raise CatalogError('Choose RELEASE or PREORDER.')
    if kind == 'PREORDER' and not store_product_id:
        raise CatalogError('For a preorder preview, choose store_product_id from /release radar offers.')
    if kind == 'RELEASE' and store_product_id is not None:
        raise CatalogError('Choose PREORDER when supplying a retailer product ID.')
    data = await radar.detail(guild, release_id)
    row = data['release']
    if row['status'] == 'ARCHIVED':
        raise CatalogError('Archived releases cannot be previewed.')
    notes = []
    if confidence(row)['state'] != 'CONFIRMED':
        notes.append(confidence(row)['reason'])
    missing = [k for k in ('region', 'language', 'product_format') if scope(row[k]) == 'unknown']
    if missing:
        notes.append('Missing catalog evidence: ' + ', '.join(missing) + '.')
    if data['check'].get('date_review'):
        notes.append('Official/distributor date evidence requires review; do not resolve it from this preview.')
    evidence = data['check'].get('evidence', [])
    if not evidence:
        notes.append('No saved official publisher match. This does not disprove the listing.')
    if any(e.get('stale') for e in evidence):
        notes.append('Some official evidence is stale or had a fetch error.')
    async with store.sessions() as s:
        sources = (await s.scalars(select(ReleaseSource).where(ReleaseSource.release_id == release_id)
            .order_by((ReleaseSource.id == (row.get('confirmed_source_id') or -1)).desc(), ReleaseSource.id.desc()).limit(5))).all()
        data['preview_sources'] = [snapshot(src) for src in sources]
        if not any(src.url for src in sources):
            notes.append('No linked source among the displayed evidence records.')
        data['selected_retailer'] = None
        if kind == 'PREORDER':
            from app.models import Store, StoreProduct, Product
            triple = (await s.execute(select(StoreProduct, Product, Store).join(Product, Product.id == StoreProduct.product_id)
                .join(Store, Store.id == StoreProduct.store_id).where(StoreProduct.id == store_product_id))).one_or_none()
            if triple is None:
                raise CatalogError('Saved retailer product not found. Use /release radar offers for the product ID.')
            offer, product, shop = triple
            releases, sources = await store.catalog_rows(s, guild)
            found, reason = evaluate_offer(offer, product, shop, releases, sources)
            saved = await s.scalar(select(RetailerLink).where(RetailerLink.guild_id == guild, RetailerLink.store_product_id == offer.id))
            current_match = bool(found and found.id == release_id)
            saved_match = bool(saved and saved.state == 'MATCHED' and saved.release_id == release_id)
            if not current_match:
                notes.append('Retailer identity unresolved: ' + (reason or 'MATCHES_OTHER_RELEASE_OR_NO_MATCH') + '.')
            if not saved_match:
                notes.append('No saved MATCHED decision for this retailer/release. Use diagnose and recheck after resolving evidence.')
            if not shop.active:
                notes.append('Retailer monitoring is disabled.')
            if shop.health_status != 'HEALTHY':
                notes.append('Retailer health: ' + str(shop.health_status or 'UNKNOWN') + '.')
            age = observation_age(offer.last_seen_at)
            if age is None or age > 300:
                notes.append('Retailer observation is older than five minutes or has an invalid timestamp.')
            if offer.status != 'PREORDER_LIVE' or offer.in_stock is not True:
                notes.append('Saved observation does not report a purchasable preorder.')
            # A recent saved observation is still never presented as live verification.
            notes.append('No live availability check was made; this preview cannot establish that checkout is open now.')
            data['selected_retailer'] = {'offer': snapshot(offer), 'product': snapshot(product), 'store': snapshot(shop),
                'identity_supported': current_match and saved_match, 'reason': reason,
                'checked_at': snapshot(saved)['checked_at'] if saved else None}
    data.update(kind=kind, preview_notes=notes)
    return data


def preview_embeds(data):
    from .radar_commands import card, link
    from .commands import safe
    row = data['release']; preorder = data['kind'] == 'PREORDER'
    selected = data['selected_retailer']
    heading = 'Preorder listing • saved observation' if preorder else confidence(row)['label']
    draft = card('PRIVATE DRAFT • ' + heading, safe(row['title'], 220))
    draft.add_field(name='Product', value=safe(f"{row['game']} • {row['product_format']}\n{row['region']} / {row['language']}", 240), inline=False)
    draft.add_field(name='Listing confidence', value=safe(confidence(row)['reason'], 300), inline=False)
    exact = row.get('release_date') if row['status'] == 'CONFIRMED' else None
    draft.add_field(name='Catalog release date', value=(safe(exact, 40) + ' • exact date recorded in catalog' if exact else 'Exact product release date not confirmed.'), inline=False)
    windows = []
    for e in data['check'].get('evidence', [])[:3]:
        for w in e.get('windows', [])[:2]:
            windows.append(safe(f"{w.get('label', 'Unspecified')} • {w.get('precision', 'UNKNOWN')} • {e.get('match_scope', 'UNKNOWN')}", 160)
                + (' • STALE' if e.get('stale') else '') + '\n' + link(e.get('url')))
    draft.add_field(name='Publisher evidence', value=('\n'.join(windows)[:900] if windows else 'No saved official release window.') + '\nMonth/quarter and game-launch windows are broader than an exact product date.', inline=False)
    if data['check'].get('date_review'):
        draft.add_field(name='Date evidence needs review', value='Saved sources contain date differences; the draft does not settle them.', inline=False)
    if preorder:
        o, p, t = selected['offer'], selected['product'], selected['store']
        if not selected['identity_supported']:
            draft.add_field(name='Retailer match pending', value='A retailer offer has been selected for review, but its identity is not established for this release. Retailer price and purchase link are withheld from this draft.', inline=False)
        else:
            draft.add_field(name='Saved retailer listing', value=safe(t['name'], 100) + '\n' + safe(p['name'], 160) + '\n' + link(o['url']), inline=False)
            draft.add_field(name='Last observed price', value=safe(f"{o['price']} {o['currency']}" if o.get('price') is not None else 'Unknown', 90), inline=True)
            draft.add_field(name='Last observed availability', value=safe(f"{o['status']} • In stock: {o['in_stock']}\nObserved: {o.get('last_seen_at') or 'Unknown'} UTC", 220), inline=False)
            draft.add_field(name='Monitoring', value=safe(f"{'Enabled' if t['active'] else 'Disabled'} • {t.get('health_status') or 'UNKNOWN'}", 100) + '\nSaved observations may be outdated. Availability was not checked now.', inline=False)
    else:
        draft.add_field(name='Retailer availability', value=f"Saved retailer matches: {data['total']}. Publisher evidence does not establish retailer stock or an open preorder.", inline=False)
    source_lines = [safe(f"#{s['id']} • {s['kind']} • {s['label']}", 120) + '\n' + link(s.get('url')) for s in data['preview_sources'][:3]]
    draft.add_field(name='Saved sources', value='\n'.join(source_lines)[:1000] or 'No saved source.', inline=False)
    if row.get('confirmed_source_id'):
        draft.add_field(name='Catalog confirmation provenance', value=f"Source #{row['confirmed_source_id']} • " + ('Approved automatic source policy' if row.get('confirmation_mode') == 'AUTOMATIC_SOURCE_POLICY' else 'Admin-reviewed catalog confirmation'), inline=False)
    review = card(f"Preview review • #{row['id']}", 'Read-only administrator preview. Nothing was queued, published or changed.')
    notes = data['preview_notes'] or ['No additional issues detected by this limited preview; publishing remains disabled.']
    review.add_field(name='Evidence and availability review', value=safe('\n'.join('• ' + note for note in notes), 1024), inline=False)
    if selected:
        review.add_field(name='Selected retailer observation', value=safe(f"Product #{selected['offer']['id']} • {selected['store']['name']}\nCurrent + saved identity match: {selected['identity_supported']}\nSaved match checked: {selected['checked_at'] or 'Never'}", 300), inline=False)
    issues = sorted({str(issue) for e in data['check'].get('evidence', []) for issue in e.get('issues', [])})
    if issues:
        review.add_field(name='Publisher evidence flags', value=safe(', '.join(issues), 600), inline=False)
    review.add_field(name='Inspect supporting records', value=f"/release sources release_id:{row['id']}\n/release radar diagnose release_id:{row['id']}\n/release official check release_id:{row['id']}\nUp to three sources and three publisher evidence records appear in the draft.", inline=False)
    return [draft, review]
