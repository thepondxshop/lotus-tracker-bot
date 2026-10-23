"""Opt-in official announcement watcher. At-most-once sends; no inventory claims."""
import asyncio
import json
import os
from datetime import datetime,timezone,timedelta
import aiohttp
from sqlalchemy import text
from app.riot_public import NEWS,FAQ,fetch,article,article_links,SourceError

def change(old,row,baseline,now=None):
    if not baseline:return None
    if old==row['fingerprint']:return None
    if old is not None:return 'ANNOUNCEMENT_UPDATED'
    try:
        published=datetime.fromisoformat(row['published_at'].replace('Z','+00:00'))
        now=now or datetime.now(timezone.utc)
        if published.tzinfo is None or not timedelta(0)<=now-published<=timedelta(days=3):return None
    except (ValueError,TypeError,KeyError,AttributeError):return None
    return 'NEW_OFFICIAL_ANNOUNCEMENT'

async def schema(conn):
    await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_riot_news (
        mode TEXT NOT NULL,url TEXT NOT NULL,fingerprint TEXT NOT NULL,
        checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(mode,url))'''))
    await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_riot_news_delivery (
        event_key TEXT PRIMARY KEY,state TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        message_id BIGINT, error_type TEXT)'''))
    await conn.commit()

async def observe(conn,mode,row,baseline):
    old=await conn.scalar(text('SELECT fingerprint FROM lotus_riot_news WHERE mode=:m AND url=:u'),{'m':mode,'u':row['url']})
    event=change(old,row,baseline)
    await conn.execute(text('''INSERT INTO lotus_riot_news(mode,url,fingerprint) VALUES (:m,:u,:f)
        ON CONFLICT(mode,url) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,checked_at=now()'''),
        {'m':mode,'u':row['url'],'f':row['fingerprint']})
    key=None
    if event and mode=='LIVE':
        import hashlib
        key=hashlib.sha256((row['url']+'|'+row['fingerprint']).encode()).hexdigest()
        reserved=await conn.scalar(text("INSERT INTO lotus_riot_news_delivery(event_key,state) VALUES (:k,'RESERVED') ON CONFLICT DO NOTHING RETURNING event_key"),{'k':key})
        if not reserved:event=None
    await conn.commit()
    return event,key

async def send_notice(channel,row,event):
    import discord
    kind='Drawing announcement' if row['kind']=='DRAWING_ANNOUNCEMENT' else 'Official Riftbound announcement'
    embed=discord.Embed(title=(kind+': '+row['title'])[:256],url=row['url'],color=0x9172ce,
        description='Official Riot news — **not an in-stock or checkout alert**.\n'+('Updated announcement.' if event=='ANNOUNCEMENT_UPDATED' else 'New announcement.'))
    if row.get('schedule_text'):embed.add_field(name='Published schedule — verify on Riot’s page',value=row['schedule_text'][:1000],inline=False)
    if row.get('image_url'):embed.set_image(url=row['image_url'])
    embed.set_footer(text='Lotus • Riot official news • No automatic drawing entry or purchase')
    return await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())

async def run(bot,mode):
    from app.database import engine
    import discord
    await bot.wait_until_ready()
    cursor=0
    while not bot.is_closed():
        delay=300
        try:
            channel=None
            if mode=='LIVE':
                channel=await bot.fetch_channel(int(os.environ['CHANNEL_RIOT_RIFTBOUND']))
                if not isinstance(channel,discord.TextChannel):raise ValueError('RIOT_TEXT_CHANNEL_REQUIRED')
                me=channel.guild.me
                if me is None:raise ValueError('RIOT_BOT_MEMBER_REQUIRED')
                perms=channel.permissions_for(me)
                if not (perms.view_channel and perms.send_messages and perms.embed_links):raise ValueError('RIOT_CHANNEL_PERMISSIONS')
            async with engine.connect() as conn:
                await schema(conn)
                locked=await conn.scalar(text('SELECT pg_try_advisory_lock(76290413)'))
                await conn.commit()
                if not locked:
                    await asyncio.sleep(30);continue
                try:
                    baseline=bool(await conn.scalar(text("SELECT 1 FROM lotus_riot_news WHERE mode=:m AND url='__BASELINE__'"),{'m':mode}))
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'LotusTracker/1.7.3 (+https://thepondx.com)'}) as session:
                        links=article_links(await fetch(session,NEWS))
                        if not links:raise ValueError('RIOT_NEWS_INDEX_EMPTY')
                        # Baseline observes the index without fetching every old article.
                        if not baseline:
                            for url in links:
                                await conn.execute(text("INSERT INTO lotus_riot_news(mode,url,fingerprint) VALUES (:m,:u,'INDEX_BASELINE') ON CONFLICT DO NOTHING"),{'m':mode,'u':url})
                        choices=[FAQ]
                        rest=[u for u in links if u!=FAQ]
                        if rest:choices.append(rest[cursor%len(rest)]);cursor+=1
                        # Prioritize newly discovered links ahead of deep rechecks.
                        for url in rest:
                            if not await conn.scalar(text('SELECT 1 FROM lotus_riot_news WHERE mode=:m AND url=:u'),{'m':mode,'u':url}):
                                if url not in choices:choices.append(url)
                                break
                        rows=[]
                        # Same leader lock and validated channel as official news.
                        # Drawing reminders do not promote a stock/release event.
                        from app.riot_drawing_notices import tick as drawing_tick
                        await drawing_tick(conn,session,channel,mode)
                        for url in choices:
                            await asyncio.sleep(1.5)
                            rows.append(article(await fetch(session,url),url))
                    for row in rows:
                        old=await conn.scalar(text('SELECT fingerprint FROM lotus_riot_news WHERE mode=:m AND url=:u'),{'m':mode,'u':row['url']})
                        event,key=await observe(conn,mode,row,baseline and old!='INDEX_BASELINE')
                        if event:
                            print('LOTUS RIOT NEWS | '+json.dumps({'mode':mode,'event':event,'url':row['url'],'stock_verified':False}),flush=True)
                            if mode=='LIVE':
                                try:
                                    message=await send_notice(channel,row,event)
                                    await conn.execute(text("UPDATE lotus_riot_news_delivery SET state='SENT',message_id=:i WHERE event_key=:k"),{'i':message.id,'k':key})
                                except Exception as exc:
                                    await conn.execute(text("UPDATE lotus_riot_news_delivery SET state='UNRESOLVED',error_type=:e WHERE event_key=:k"),{'e':type(exc).__name__,'k':key})
                                await conn.commit()
                    await conn.execute(text("INSERT INTO lotus_riot_news(mode,url,fingerprint) VALUES (:m,'__BASELINE__','READY') ON CONFLICT DO NOTHING"),{'m':mode})
                    await conn.commit()
                    print('LOTUS RIOT NEWS | '+json.dumps({'state':'CYCLE_COMPLETE','mode':mode,'index_articles':len(links),'articles_checked':len(rows),'stock_verified':False}),flush=True)
                finally:
                    await conn.rollback()
                    await conn.execute(text('SELECT pg_advisory_unlock(76290413)'));await conn.commit()
        except asyncio.CancelledError:raise
        except Exception as exc:
            delay=exc.wait if isinstance(exc,SourceError) else 900
            print('LOTUS RIOT NEWS | '+json.dumps({'state':'DEFERRED','error_type':type(exc).__name__,'retry_seconds':delay}),flush=True)
        await asyncio.sleep(delay)

def start(bot):
    mode=os.getenv('LOTUS_RIOT_NEWS_MODE','OFF').upper()
    if mode not in ('SHADOW','LIVE'):return None
    if mode=='LIVE' and not os.getenv('CHANNEL_RIOT_RIFTBOUND','').isdigit():
        print('LOTUS RIOT NEWS | State=CHANNEL_REQUIRED',flush=True);return None
    task=getattr(bot,'riot_news_task',None)
    if task and not task.done():return task
    bot.riot_news_task=asyncio.create_task(run(bot,mode));return bot.riot_news_task
