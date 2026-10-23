"""Reviewed October 22 Riot schedule; drawing dates are never release dates."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from app.riot_public import fetch, next_page, plain

SOURCE = 'https://playriftbound.com/en-us/news/announcements/riftbounds-2026-drawings/'
CDN = 'https://cmsassets.rgpub.io/sanity/images/dsfx7636/news_live/'
PRODUCTS = [
    dict(title='Riftbound x K/DA Couture Collection', price='150.00',
         image=CDN+'ddcf8b5b7b587cf960ef53d5420928b856884c5c-2234x1257.jpg',
         opens='2026-10-27T09:00:00', closes='2026-10-30T09:00:00', emails='2026-11-03',
         release=None, note='Drawing for an opportunity to purchase. Also sold at Convergence Fest December 11–13; not a general retail release.'),
    dict(title='T1 2025 Worlds Champion Player Bundle', price='70.00',
         image=CDN+'74f003439be52d41236c41b5cc06550cb6257bc5-1327x1220.jpg',
         opens='2026-11-13T09:00:00', closes='2026-11-16T09:00:00', emails='2026-11-17',
         release=None, note='Drawing for an opportunity to purchase. Event sales during November; fulfillment begins mid-December. Not the Signature Edition.'),
    dict(title='Riftbound x Worlds 2026 Edition', price='80.00',
         image=CDN+'c81340b874ad8ff22fe2d23481479649e8e09db3-2560x1440.jpg',
         opens='2026-11-13T09:00:00', closes='2026-11-16T09:00:00', emails='2026-11-17',
         release=None, note='Drawing for an opportunity to purchase. Event sales during November; online fulfillment begins mid-December.'),
    dict(title='Gift of the Rift Bundle', price='109.00',
         image=CDN+'cce8b4c4764176c8e352bb0c74558b1f5a4a2af8-3840x2160.jpg',
         opens=None, closes=None, emails=None, release='2026-12-04',
         note='Retail release through local game stores and other retailers. English edition has the Akali promo; Chinese edition has Kennen. Stock is not verified.'),
]

def epoch(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('America/Los_Angeles')).timestamp())

def schedule_text(p):
    if p['opens']:
        return (f"Drawing opens: <t:{epoch(p['opens'])}:F>\nDrawing closes: <t:{epoch(p['closes'])}:F>\n"
                f"First selection emails: {p['emails']} (time unspecified)\n" + p['note'])
    return f"Retail release: {p['release']}\n" + p['note']

def embeds():
    import discord
    result=[]
    for p in PRODUCTS:
        e=discord.Embed(title=p['title'],url=SOURCE,description=schedule_text(p),colour=0x9172ce)
        e.add_field(name='Published US price',value='$'+p['price']+' • shipping/handling may apply')
        e.set_image(url=p['image'])
        e.set_footer(text='Riot schedule reviewed October 22, 2026 • Registration is not stock • Recheck source for updates')
        result.append(e)
    return result

async def import_catalog(runtime, guild_id, actor_id):
    """Explicit admin import, repeatable without duplicate products or sources."""
    import aiohttp
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),trust_env=True) as session:
        page=next_page(await fetch(session,SOURCE))
    body=' '.join(plain(b.get('richText',{}).get('body')) for b in page.get('blades',[]) if b.get('type')=='articleRichText')
    # Refuse the reviewed snapshot if key schedule facts no longer occur.
    required=[p['title'] for p in PRODUCTS]+['October 27, 9:00 AM PT','October 30, 9:00 AM PT',
        'November 13, 9:00 AM PT','November 16, 9:00 AM PT','December 4']
    if any(v not in body for v in required):
        raise ValueError('RIOT_SCHEDULE_CHANGED_REVIEW_REQUIRED')
    result=[]
    catalog=runtime.store.catalog
    for p in PRODUCTS:
        data=await catalog.add(guild_id,actor_id,game='Riftbound',title=p['title'],
            details=schedule_text(p),source_label='Riot October 22 product announcement',source_url=SOURCE,
            region='US',language='English',product_format='SET')
        rid=data['release']['id']
        source=await catalog.add_source(guild_id,actor_id,rid,kind='PUBLISHER',
            label='Riot reviewed product schedule October 22',url=SOURCE,
            note=json.dumps(dict(product=p['title'],image_url=p['image'],schedule=p,
                                 release_date=p['release'],stock_verified=False)))
        sid=source['source']['id']
        # Only the retail product has a general release date. Drawing products
        # are confirmed identities with undated calendar entries and schedule notes.
        await catalog.confirm(guild_id,actor_id,rid,source_id=sid,reviewed=True,
            review_note='Admin imported reviewed Riot October 22 schedule; registration is not a retail release.',
            release_date=p['release'])
        await runtime.store.save_image(guild_id,rid,sid,p['image'])
        result.append(dict(id=rid,title=p['title'],release_date=p['release']))
    runtime.cache.pop(guild_id,None)
    return result
