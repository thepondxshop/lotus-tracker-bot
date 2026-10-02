"""Discord calendar presentation. Rendering uses stored data, with no retailer HTTP."""
import calendar
import io
import textwrap
from datetime import date
import discord
UI_VERSION = '1.1.2-CAL3-IMG2'
from .service import CatalogError
from .calendar_images import asset_path


def pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except ModuleNotFoundError as error:
        if error.name != 'PIL' and not str(error.name).startswith('PIL.'):
            raise
        raise CatalogError('Calendar images need Pillow. Add Pillow>=11.3,<13 to the repository-root requirements.txt, commit it, and rebuild/redeploy Railway. Then run /calendaradmin setup again.') from error


def safe(value, limit=1000):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value or '')))[:limit]


def font(size):
    _, _, ImageFont = pillow()
    try: return ImageFont.truetype('DejaVuSans.ttf', size)
    except OSError: return ImageFont.load_default(size=size)


def month_png(year, month, entries, games=None):
    Image, ImageDraw, _ = pillow()
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    width, top, cell_w, cell_h = 1600, 206, 220, 132
    footer = top + len(weeks)*cell_h + 16
    image = Image.new('RGB', (width, footer+142), '#111827')
    d = ImageDraw.Draw(image)
    exact, pending = {}, []
    for e in entries:
        if games is not None and e['game'] not in games: continue
        p = e.get('period')
        if not p: continue
        anchor = date.fromisoformat(p['anchor'])
        if (anchor.year, anchor.month) != (year, month): continue
        if p['tba']: pending.append(e)
        else: exact.setdefault(anchor.day, []).append(e)
    def fitted(text, max_width, size):
        text=str(text)
        while text and d.textlength(text, font=font(size))>max_width:
            text=text[:-1]
        return text
    d.text((32, 20), 'LOTUS  /  RELEASE CALENDAR', font=font(24), fill='#93c5fd')
    d.text((32, 60), f'{calendar.month_name[month]} {year}', font=font(56), fill='white')
    label = 'All games' if games is None else ', '.join(games) or 'No games selected'
    d.text((32, 132), fitted(label,1530,24), font=font(24), fill='#cbd5e1')
    for i, label in enumerate(('SUN','MON','TUE','WED','THU','FRI','SAT')):
        d.text((44+i*cell_w, 172), label, font=font(24), fill='#94a3b8')
    for week, days in enumerate(weeks):
        for col, day in enumerate(days):
            x, y = 30+col*cell_w, top+week*cell_h
            rows=exact.get(day, []) if day else []
            d.rounded_rectangle((x,y,x+cell_w-10,y+cell_h-10),radius=12,
                fill='#163b36' if rows else '#1e293b',outline='#34d399' if rows else None,width=2)
            if not day: continue
            d.text((x+14,y+8),str(day),font=font(42),fill='white')
            if rows:
                d.text((x+14,y+66),f'{len(rows)} release'+('s' if len(rows)>1 else ''),font=font(27),fill='#86efac')
    # Period endpoints organize uncertain dates, never imply a numbered-day release.
    d.rounded_rectangle((30,footer,1570,footer+90),radius=12,fill='#30283e')
    d.text((46,footer+10),f'PERIOD-END TBA  /  {len(pending)} product'+('s' if len(pending)!=1 else ''),font=font(28),fill='#e9d5ff')
    groups = sorted({e['period']['label'] for e in pending})
    d.text((46,footer+50),fitted(' | '.join(groups) or 'No period-end listings this month.',1490,23),font=font(23),fill='#e2e8f0')
    d.text((32,footer+106),'Open Week zoom below for readable lists and clickable day buttons.',font=font(25),fill='#94a3b8')
    out=io.BytesIO(); image.save(out,format='PNG'); out.seek(0)
    return out


def placeholder_png(entry=None):
    Image, ImageDraw, _ = pillow()
    entry=entry or {}
    image=Image.new('RGB',(960,600),'#111827'); d=ImageDraw.Draw(image)
    d.text((40,28),'LOTUS  /  ARTWORK PENDING',font=font(24),fill='#93c5fd')
    d.rounded_rectangle((40,88,920,502),radius=22,fill='#1e293b',outline='#475569',width=3)
    d.text((70,113),str(entry.get('game') or 'TCG release')[:40],font=font(30),fill='#a5b4fc')
    label=str(entry.get('set_code') or entry.get('product_format') or 'PRODUCT')
    d.text((70,170),label[:18],font=font(66),fill='white')
    title=str(entry.get('title') or 'Product image coming soon')
    lines=textwrap.wrap(title,width=42)[:3]
    for n,line in enumerate(lines):d.text((70,280+n*46),line,font=font(31),fill='#e2e8f0')
    d.text((70,447),'Illustrative placeholder',font=font(26),fill='#fcd34d')
    d.text((40,535),'Final product artwork has not been supplied.',font=font(29),fill='#cbd5e1')
    out=io.BytesIO();image.save(out,format='PNG');out.seek(0);return out


def product_image_file(entry):
    name=entry.get('image_asset')
    if name:
        path=asset_path(name)
        if path: return discord.File(path,filename=name)
    if not entry.get('image_url'):
        return discord.File(placeholder_png(entry),filename='image-pending.png')
    return None


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
    additional = [u for u in entry.get('calendar_source_urls', []) if u != entry.get('source_url')]
    if additional:
        e.add_field(name='Additional sources', value=' • '.join(
            f'[Source {i+2}]({url})' for i, url in enumerate(additional[:3])), inline=False)
    if entry.get('image_label'):e.add_field(name='Artwork',value=safe(entry['image_label'],500),inline=False)
    e.set_thumbnail(url=entry.get('image_url') or 'attachment://image-pending.png')
    e.set_footer(text=f"Lotus Calendar {UI_VERSION} • Release #{entry['id']} • Release date does not establish stock")
    return e


def announcement_embed(entry, day):
    e=product_embed(entry)
    e.title=f"🎉 Release day • {safe(entry['title'],205)}"
    e.description=f"**{safe(entry['title'],200)} releases today — {day:%B %d, %Y}!**\nHappy hunting, collectors! 🪷\n\nRetailer stock and opening times may vary."
    e.set_thumbnail(url=None)
    e.set_image(url=entry.get('image_url') or 'attachment://image-pending.png')
    return e
