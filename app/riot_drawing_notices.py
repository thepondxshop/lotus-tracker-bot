"""Source-checked schedule reminders, never claims verified registration or stock."""
import hashlib
import os
from datetime import datetime, timezone
from sqlalchemy import text
from app.riot_schedule import PRODUCTS, SOURCE, epoch
from app.riot_public import fetch, next_page, plain

def due_notices(now=None):
    now=(now or datetime.now(timezone.utc)).timestamp()
    result=[]
    for p in PRODUCTS:
        if not p.get('opens'):continue
        opens,closes=epoch(p['opens']),epoch(p['closes'])
        if opens<=now<min(opens+1800,closes):kind='OPENING'
        elif closes-3600<=now<closes:kind='CLOSING_SOON'
        elif closes<=now<closes+1800:kind='CLOSED'
        else:continue
        key=hashlib.sha256(f"RIOT_DRAWING|{p['title']}|{p['opens']}|{p['closes']}|{kind}".encode()).hexdigest()
        result.append(dict(product=p,kind=kind,key=key))
    return result

def verified_section(body,p):
    """Bind dates to the product section, not another product elsewhere."""
    start=body.find(p['title'])
    if start<0:return False
    end=min([pos for other in PRODUCTS if other['title']!=p['title']
             for pos in [body.find(other['title'],start+len(p['title']))] if pos>=0] or [len(body)])
    section=body[start:end]
    def label(value):
        d=datetime.fromisoformat(value)
        return f"{d:%B} {d.day}, {d.hour if d.hour<=12 else d.hour-12}:{d.minute:02d} {'AM' if d.hour<12 else 'PM'} PT"
    return ('Drawing registration opens: '+label(p['opens']) in section
            and 'Drawing registration closes: '+label(p['closes']) in section)

async def tick(conn,session,channel,mode,now=None):
    if os.getenv('LOTUS_RIOT_DRAWING_NOTICES','true').lower()!='true':return
    notices=due_notices(now)
    if not notices:return
    await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_riot_drawing_delivery (
        event_key TEXT PRIMARY KEY,state TEXT NOT NULL,message_id BIGINT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,error_type TEXT)'''))
    await conn.commit()
    pending=[]
    for notice in notices:
        if not await conn.scalar(text('SELECT 1 FROM lotus_riot_drawing_delivery WHERE event_key=:k'),{'k':notice['key']}):
            pending.append(notice)
    if not pending:return
    page=next_page(await fetch(session,SOURCE))
    body=' '.join(plain(b.get('richText',{}).get('body')) for b in page.get('blades',[]) if b.get('type')=='articleRichText')
    for notice in pending:
        p=notice['product']
        if not verified_section(body,p):
            print('LOTUS RIOT DRAWING | State=SOURCE_CHANGED_REVIEW_REQUIRED',flush=True);continue
        if mode!='LIVE':
            print('LOTUS RIOT DRAWING | State=SHADOW_DUE | Kind='+notice['kind'],flush=True);continue
        if channel is None:raise ValueError('RIOT_CHANNEL_REQUIRED')
        reserved=await conn.scalar(text("INSERT INTO lotus_riot_drawing_delivery(event_key,state) VALUES (:k,'RESERVED') ON CONFLICT DO NOTHING RETURNING event_key"),{'k':notice['key']})
        await conn.commit()
        if not reserved:continue
        try:
            message=await send(channel,notice)
            await conn.execute(text("UPDATE lotus_riot_drawing_delivery SET state='SENT',message_id=:i WHERE event_key=:k"),{'i':message.id,'k':notice['key']})
        except Exception as exc:
            # An ambiguous send is not retried automatically and cannot double ping.
            await conn.execute(text("UPDATE lotus_riot_drawing_delivery SET state='UNRESOLVED',error_type=:e WHERE event_key=:k"),{'e':type(exc).__name__,'k':notice['key']})
        await conn.commit()

async def send(channel,notice):
    import discord
    p=notice['product'];kind=notice['kind']
    titles={'OPENING':'Scheduled drawing window begins','CLOSING_SOON':'Scheduled drawing closes within an hour','CLOSED':'Scheduled drawing window ended'}
    e=discord.Embed(title=(titles[kind]+': '+p['title'])[:256],url=SOURCE,colour=0x9172ce,
        description=f"Opens: <t:{epoch(p['opens'])}:F>\nCloses: <t:{epoch(p['closes'])}:F>\n"
        'Based on Riot’s published schedule. **Registration availability has not been verified.** '
        'Entry is a chance to purchase, not guaranteed stock or a reservation.')
    e.set_image(url=p['image'])
    e.set_footer(text='Lotus • Official drawing schedule • Verify current details at Riot')
    return await channel.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
