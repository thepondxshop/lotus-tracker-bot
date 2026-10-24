"""Official-page retirement candidates. Only explicit admin decisions disable alerts.

Coverage is the configured source list, not a claim that every publisher is watched.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import aiohttp
from bs4 import BeautifulSoup
import discord
from discord import app_commands
from discord.ext import commands,tasks
from sqlalchemy import text

NEWS_CHANNEL=1560358191689367642
ANNOUNCEMENTS_CHANNEL=1541869401220055201
SOURCES=(
    {'game':'Beyblade X TCG — Blader League','url':'https://bladerleague.com/news','identity':'blader league'},
    {'game':'World of Tanks TCG','url':'https://worldoftanks.com/en/news/merchandise/','identity':'world of tanks'},
    {'game':'Vibes TCG','url':'https://www.vibes.game/','identity':'vibes'},
    {'game':'Shadowverse Evolve','url':'https://en.shadowverse-evolve.com/news/','identity':'shadowverse'},
)
RETIRE=re.compile(r'\b(?:discontinu(?:ed|ation|ing)|end(?:ing)? (?:of )?(?:production|service|support)|ceas(?:e|ing) (?:production|operations)|shutting down|retir(?:ement|ing)|closure)\b',re.I)
_disabled=set()

def disabled(guild,game):return (guild,game) in _disabled

def safe_source(url,base):
    try:
        p=urlsplit(url);b=urlsplit(base)
        return p.scheme=='https' and p.hostname==b.hostname and not p.username and not p.password and p.port in (None,443)
    except ValueError:return False

def candidate_text(html,identity):
    soup=BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style','nav','footer','header']):tag.decompose()
    article=soup.find('article') or soup.find('main')
    if article is None:return None
    value=' '.join(article.get_text(' ',strip=True).split())
    for hit in RETIRE.finditer(value):
        excerpt=value[max(0,hit.start()-140):hit.end()+220]
        if identity.casefold() in excerpt.casefold() and not re.search(r'\b(?:not|no plans to|rumou?r)\b',excerpt,re.I):
            return excerpt[:450]
    return None

async def fetch(session,url,base):
    if not safe_source(url,base):raise ValueError('Unapproved source host')
    async with session.get(url,allow_redirects=False) as r:
        if r.status!=200:raise ValueError('Source HTTP '+str(r.status))
        if 'text/html' not in r.headers.get('Content-Type',''):raise ValueError('Source not HTML')
        parts=[];size=0
        async for part in r.content.iter_chunked(65536):
            size+=len(part)
            if size>2_000_000:raise ValueError('Source too large')
            parts.append(part)
        body=b''.join(parts).decode('utf-8',errors='replace')
        if re.search(r'cookies disabled|javascript disabled|just a moment|cf-chl-|verify you are human',body,re.I):
            raise ValueError('Source challenge')
        if not BeautifulSoup(body,'html.parser').find(['main','article']):
            raise ValueError('Source content schema unverified')
        return body

async def schema(engine):
    async with engine.begin() as c:
        await c.execute(text('''CREATE TABLE IF NOT EXISTS lotus_game_lifecycle (
            id TEXT PRIMARY KEY,guild_id BIGINT NOT NULL,game TEXT NOT NULL,url TEXT NOT NULL,
            excerpt TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'PENDING',
            admin_notice TEXT NOT NULL DEFAULT 'NEW',decision_by BIGINT,delete_role BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)'''))

class GameLifecycle(commands.Cog):
    def __init__(self,bot,engine):self.bot=bot;self.engine=engine;self.last_checks={}
    async def cog_load(self):
        async with self.engine.connect() as c:
            rows=(await c.execute(text("SELECT guild_id,game FROM lotus_game_lifecycle WHERE state IN ('DISCONNECTED','DISCONNECTING')"))).all()
        _disabled.update((r[0],r[1]) for r in rows)
        self.poll.start()
    async def cog_unload(self):self.poll.cancel()
    @tasks.loop(minutes=60)
    async def poll(self):
        raw=os.getenv('CHANNEL_TCG_DISCOVERIES','')
        admin=self.bot.get_channel(int(raw)) if raw.isdigit() else None
        if not admin:
            print(f'LOTUS GAME LIFECYCLE | State=ADMIN_CHANNEL_MISSING | Sources={len(SOURCES)}',flush=True);return
        # One worker per database. Sources are bounded and isolated on error.
        async with self.engine.connect() as lock:
            if not await lock.scalar(text('SELECT pg_try_advisory_lock(76290416)')):return
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                    for source in SOURCES:
                        try:
                            html=await fetch(session,source['url'],source['url'])
                            soup=BeautifulSoup(html,'html.parser')
                            urls=[source['url']]
                            for a in soup.select('a[href]'):
                                url=urljoin(source['url'],a['href']).split('#')[0]
                                if RETIRE.search(a.get_text(' ',strip=True)) and safe_source(url,source['url']) and url not in urls:urls.append(url)
                            for url in urls[:4]:
                                body=html if url==source['url'] else await fetch(session,url,source['url'])
                                excerpt=candidate_text(body,source['identity'])
                                if not excerpt:continue
                                key=hashlib.sha256(f"{admin.guild.id}|{source['game']}|{url}".encode()).hexdigest()[:20]
                                async with self.engine.begin() as c:
                                    await c.execute(text('INSERT INTO lotus_game_lifecycle(id,guild_id,game,url,excerpt) VALUES (:id,:g,:game,:url,:excerpt) ON CONFLICT DO NOTHING'),dict(id=key,g=admin.guild.id,game=source['game'],url=url,excerpt=excerpt))
                                await self.notify(admin,key)
                            self.last_checks[source['game']]='CHECKED_PARTIAL'
                            print(f"LOTUS GAME LIFECYCLE | Game={source['game']} | State=CHECKED_PARTIAL | Pages={min(len(urls),4)}",flush=True)
                        except Exception as exc:
                            self.last_checks[source['game']]='SOURCE_UNAVAILABLE'
                            print(f"LOTUS GAME LIFECYCLE | Game={source['game']} | State=SOURCE_UNAVAILABLE | Error={type(exc).__name__}",flush=True)
            finally:await lock.execute(text('SELECT pg_advisory_unlock(76290416)'))
    @poll.before_loop
    async def before_poll(self):await self.bot.wait_until_ready()
    async def notify(self,admin,key):
        async with self.engine.begin() as c:
            row=(await c.execute(text("UPDATE lotus_game_lifecycle SET admin_notice='RESERVED' WHERE id=:id AND admin_notice='NEW' RETURNING *"),dict(id=key))).mappings().first()
        if not row:return
        # Reservation prevents repeated pings after ambiguous network failures.
        role_raw=os.getenv('ROLE_TCG_DISCOVERY_ADMIN','')
        role=admin.guild.get_role(int(role_raw)) if role_raw.isdigit() else None
        await admin.send((role.mention+'\n' if role else '')+f"**Game status review — {row['game']}**\nPossible discontinuation announcement; not yet confirmed.\n{row['url']}\nUse `/gamereview candidate:{key}` with Keep, Disconnect, or Dismiss after reviewing the official source.",
            allowed_mentions=discord.AllowedMentions(everyone=False,users=False,roles=[role] if role else []))
        async with self.engine.begin() as c:await c.execute(text("UPDATE lotus_game_lifecycle SET admin_notice='SENT' WHERE id=:id"),dict(id=key))
    @app_commands.command(name='gamestatus',description='List monitored official sources and pending retirement reviews.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def status(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.engine.connect() as c:
            rows=(await c.execute(text('SELECT id,game,state FROM lotus_game_lifecycle WHERE guild_id=:g ORDER BY created_at DESC LIMIT 15'),dict(g=interaction.guild_id))).mappings().all()
        await interaction.followup.send('Configured official pages (partial coverage):\n'+'\n'.join(s['game']+': '+self.last_checks.get(s['game'],'NOT_CHECKED') for s in SOURCES)+'. Other games are not yet covered by this status watcher.\n'+'\n'.join(f"{r['id']} · {r['game']} · {r['state']}" for r in rows),ephemeral=True)
    @app_commands.command(name='gamereview',description='Confirm a publisher announcement and keep/disconnect alerts, or dismiss a false positive.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.choices(decision=[app_commands.Choice(name='Confirmed; keep alerts and post news',value='keep'),app_commands.Choice(name='Confirmed; disconnect alerts and announce',value='disconnect'),app_commands.Choice(name='Dismiss false positive',value='dismiss')])
    async def review(self,interaction:discord.Interaction,candidate:str,decision:str,delete_role:bool=False):
        await interaction.response.defer(ephemeral=True)
        if decision not in {'keep','disconnect','dismiss'}:return
        if delete_role and (decision!='disconnect' or not interaction.user.guild_permissions.manage_roles):
            await interaction.followup.send('Role deletion requires Manage Roles and Disconnect.',ephemeral=True);return
        channel=interaction.guild.get_channel(ANNOUNCEMENTS_CHANNEL if decision=='disconnect' else NEWS_CHANNEL)
        if decision!='dismiss' and channel is None:
            await interaction.followup.send('Destination channel is missing; no decision saved.',ephemeral=True);return
        async with self.engine.begin() as c:
            row=(await c.execute(text("SELECT * FROM lotus_game_lifecycle WHERE id=:id AND guild_id=:g FOR UPDATE"),dict(id=candidate,g=interaction.guild_id))).mappings().first()
            if not row or row['state']!='PENDING':
                await interaction.followup.send('Review missing or already decided. See /gamestatus.',ephemeral=True);return
            state={'keep':'KEEPING','disconnect':'DISCONNECTING','dismiss':'DISMISSED'}[decision]
            await c.execute(text('UPDATE lotus_game_lifecycle SET state=:s,decision_by=:u,delete_role=:d WHERE id=:id'),dict(s=state,u=interaction.user.id,d=delete_role,id=candidate))
        if decision=='disconnect':_disabled.add((interaction.guild_id,row['game']))
        if decision=='dismiss':
            await interaction.followup.send('Dismissed; alerts unchanged.',ephemeral=True);return
        # Keep pending delivery state on any failure; do not blindly replay @everyone.
        try:
            if delete_role:
                from app.config import GAME_ROLES,SUBSCRIPTION_ROLES
                raw=str(GAME_ROLES.get(row['game']) or '')
                role=interaction.guild.get_role(int(raw)) if raw.isdigit() else None
                if role:
                    if raw in {str(x) for x in SUBSCRIPTION_ROLES.values()} or role.is_default() or role.managed:raise ValueError('Protected role')
                    await role.delete(reason='Admin-confirmed game discontinuation; explicit delete_role request')
            text_body=f"**{row['game']} — publisher discontinuation/status announcement**\nOfficial announcement: {row['url']}\n"
            text_body+=('PonDeX has disconnected alerts for this game.' if decision=='disconnect' else 'PonDeX will continue tracking this game following admin review.')
            await channel.send(('@everyone\n' if decision=='disconnect' else '')+text_body,allowed_mentions=discord.AllowedMentions(everyone=decision=='disconnect',users=False,roles=False))
            async with self.engine.begin() as c:await c.execute(text('UPDATE lotus_game_lifecycle SET state=:s WHERE id=:id'),dict(id=candidate,s='DISCONNECTED' if decision=='disconnect' else 'KEPT'))
            await interaction.followup.send('Decision saved and announcement posted.',ephemeral=True)
        except Exception as exc:
            print('LOTUS GAME LIFECYCLE | State=DECISION_DELIVERY_UNRESOLVED | Error='+type(exc).__name__,flush=True)
            await interaction.followup.send('Decision saved, but delivery or role deletion needs manual review. No automatic announcement replay.',ephemeral=True)

async def install(bot,database_ready):
    if not database_ready:return
    from app.database import engine
    try:
        await schema(engine)
        if not bot.get_cog('GameLifecycle'):await bot.add_cog(GameLifecycle(bot,engine))
    except Exception as exc:print('LOTUS GAME LIFECYCLE | State=START_FAILED | Error='+type(exc).__name__,flush=True)
