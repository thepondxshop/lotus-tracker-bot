"""Discord calendar presentation. Rendering uses stored data, with no retailer HTTP."""
import calendar
import io
import textwrap
from datetime import date
import discord
from .calendar_store import VERSION


def safe(value, limit=1000):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value or '')))[:limit]


def font(size):
    from PIL import ImageFont
    try: return ImageFont.truetype('DejaVuSans.ttf', size)
    except OSError: return ImageFont.load_default(size=size)


def month_png(year, month, entries, games=None):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1120, 960), '#111827')
    d = ImageDraw.Draw(image)
    filtered = [e for e in entries if games is None or e['game'] in games]
    exact = {}
    pending = []
    for e in filtered:
        p = e.get('period')
        if not p: continue
        anchor = date.fromisoformat(p['anchor'])
        if (anchor.year, anchor.month) != (year, month): continue
        if p['tba']: pending.append(e)
        else: exact.setdefault(anchor.day, []).append(e)
    d.text((32, 26), 'LOTUS  /  RELEASE CALENDAR', font=font(19), fill='#93c5fd')
    d.text((32, 62), f'{calendar.month_name[month]} {year}', font=font(38), fill='white')
    label = 'All games' if games is None else ', '.join(games) or 'No games selected'
    d.text((32, 111), textwrap.shorten(label, width=100, placeholder='...'), font=font(17), fill='#cbd5e1')
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    for i, label in enumerate(('SUN','MON','TUE','WED','THU','FRI','SAT')):
        d.text((40+i*152, 158), label, font=font(17), fill='#94a3b8')
    for week, days in enumerate(weeks):
        for col, day in enumerate(days):
            x, y = 28+col*152, 188+week*100
            d.rounded_rectangle((x,y,x+144,y+92),radius=10,fill='#1e293b')
            if not day: continue
            d.text((x+10,y+7),str(day),font=font(22),fill='white')
            rows = exact.get(day, [])
            if rows:
                d.text((x+10,y+39),f'{len(rows)} release'+('s' if len(rows)>1 else ''),font=font(15),fill='#86efac')
                title = rows[0].get('set_code') or rows[0]['title']
                d.text((x+10,y+62), textwrap.shorten(title,width=17,placeholder='...'),font=font(13),fill='#cbd5e1')
    # Always outside the numbered day cells: TBA is never a day-31 release.
    y = 814
    d.rounded_rectangle((28,y,1090,912),radius=12,fill='#30283e')
    d.text((44,y+12),f'PERIOD-END TBA  /  {len(pending)} product'+('s' if len(pending)!=1 else ''),font=font(20),fill='#e9d5ff')
    groups = sorted({e['period']['label'] for e in pending})
    d.text((44,y+46),textwrap.shorten(' | '.join(groups) or 'No period-end listings this month.',width=106,placeholder='...'),font=font(16),fill='#e2e8f0')
    d.text((32,931),'Select a day for product images and details. TBA endpoints are not release dates.',font=font(16),fill='#94a3b8')
    out=io.BytesIO(); image.save(out,format='PNG'); out.seek(0)
    return out


def placeholder_png():
    from PIL import Image, ImageDraw
    image=Image.new('RGB',(240,240),'#1e293b'); d=ImageDraw.Draw(image)
    d.text((36,75),'PRODUCT IMAGE',font=font(18),fill='#94a3b8')
    d.text((50,110),'COMING SOON',font=font(18),fill='#cbd5e1')
    out=io.BytesIO();image.save(out,format='PNG');out.seek(0);return out


def product_embed(entry):
    p=entry.get('period')
    label=(f"{p['label']} • TBA" if p['tba'] else p['label']) if p else 'Release date TBA'
    e=discord.Embed(title=safe(entry['title'],230),description=f"**{safe(label,150)}**\n{safe(entry['confidence'],100)}",colour=0x8B5CF6 if not p or p['tba'] else 0x34D399)
    e.add_field(name='Game / product',value=f"{safe(entry['game'],80)} • {safe(entry['product_format'],30)}",inline=True)
    e.add_field(name='Edition',value=f"{safe(entry['region'],40)} / {safe(entry['language'],40)}",inline=True)
    e.add_field(name='Date evidence',value=safe(entry['date_origin'],100),inline=False)
    if p and p.get('scope')=='GAME_LAUNCH':
        e.add_field(name='Scope',value='Game launch window; the individual product date remains unconfirmed.',inline=False)
    if p and p['tba']:
        e.add_field(name='TBA placement',value='Shown at the end of its period for organization. This is not an exact release date.',inline=False)
    if entry.get('notes'):e.add_field(name='Notes',value=safe('\n'.join(entry['notes']),500),inline=False)
    if entry.get('source_url'): e.add_field(name='Source',value=f"[View source]({entry['source_url']})",inline=False)
    e.set_thumbnail(url=entry.get('image_url') or 'attachment://image-pending.png')
    e.set_footer(text=f"Lotus Calendar {VERSION} • Release #{entry['id']} • Release date does not establish stock")
    return e


def announcement_embed(entry, day):
    e=product_embed(entry)
    e.title=f"🎉 Release day • {safe(entry['title'],205)}"
    e.description=f"**{safe(entry['title'],200)} releases today — {day:%B %d, %Y}!**\nHappy hunting, collectors! 🪷\n\nRetailer stock and opening times may vary."
    if not entry.get('image_url'): e.set_thumbnail(url=None)
    return e
