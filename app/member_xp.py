"""Opt-in member activity XP. PostgreSQL persistence; no paid role changes."""
import hashlib
import math
import os
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import text

def enabled():
    return os.getenv('LOTUS_XP_ENABLED','false').lower()=='true'

def channel_ids():
    return {int(v.strip()) for v in os.getenv('LOTUS_XP_CHANNEL_IDS','').split(',') if v.strip().isdigit() and int(v.strip())>0}

def level(xp):
    return math.isqrt(max(0,int(xp))//100)

def content_key(content):
    normalized=' '.join(str(content or '').casefold().split())
    if len(normalized)<12 or normalized.startswith(('!','/','http://','https://')):
        return None
    if sum(c.isalnum() for c in normalized)<8 or len(set(normalized))<5:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()

def eligible_message(message):
    return (message.guild is not None and not message.author.bot and not message.webhook_id
            and message.channel.id in channel_ids() and content_key(message.content) is not None)

def award_amount(row,key,message_id,now):
    if message_id<=int(row['last_message_id']):return 0
    previous=row['last_awarded_at']
    if previous is not None and (now-previous).total_seconds()<60:return 0
    if row['last_content_hash']==key:return 0
    today=now.date()
    used=int(row['daily_xp']) if row['day']==today else 0
    return max(0,min(10,200-used))

async def ensure_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_member_xp (
            guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, xp BIGINT NOT NULL DEFAULT 0,
            day DATE NOT NULL DEFAULT CURRENT_DATE, daily_xp INTEGER NOT NULL DEFAULT 0,
            last_awarded_at TIMESTAMPTZ, last_message_id BIGINT NOT NULL DEFAULT 0,
            last_content_hash TEXT, PRIMARY KEY(guild_id,user_id))'''))
        await conn.execute(text('CREATE INDEX IF NOT EXISTS lotus_member_xp_ranking ON lotus_member_xp(guild_id,xp DESC,user_id)'))

class XPStore:
    def __init__(self,engine):self.engine=engine
    async def award(self,guild_id,user_id,message_id,key):
        async with self.engine.begin() as conn:
            args=dict(g=guild_id,u=user_id)
            await conn.execute(text('INSERT INTO lotus_member_xp(guild_id,user_id) VALUES (:g,:u) ON CONFLICT DO NOTHING'),args)
            row=(await conn.execute(text('SELECT * FROM lotus_member_xp WHERE guild_id=:g AND user_id=:u FOR UPDATE'),args)).mappings().one()
            # Read the clock after acquiring the lock, so concurrent listeners share the cooldown.
            now=(await conn.scalar(text('SELECT clock_timestamp()'))).astimezone(timezone.utc)
            amount=award_amount(row,key,message_id,now)
            if not amount:return 0
            await conn.execute(text('''UPDATE lotus_member_xp SET xp=xp+:n,
                daily_xp=CASE WHEN day=:day THEN daily_xp+:n ELSE :n END, day=:day,
                last_awarded_at=:now,last_message_id=:mid,last_content_hash=:key
                WHERE guild_id=:g AND user_id=:u'''),dict(args,n=amount,day=now.date(),now=now,mid=message_id,key=key))
            return amount
    async def rank(self,guild_id,user_id):
        async with self.engine.connect() as conn:
            row=(await conn.execute(text('''SELECT xp, 1+(SELECT count(*) FROM lotus_member_xp b
                WHERE b.guild_id=a.guild_id AND b.xp>a.xp) AS rank
                FROM lotus_member_xp a WHERE guild_id=:g AND user_id=:u'''),dict(g=guild_id,u=user_id))).mappings().first()
            return dict(row) if row else dict(xp=0,rank=None)
    async def leaders(self,guild_id):
        async with self.engine.connect() as conn:
            return (await conn.execute(text('SELECT user_id,xp FROM lotus_member_xp WHERE guild_id=:g ORDER BY xp DESC,user_id LIMIT 10'),dict(g=guild_id))).mappings().all()

class MemberXP(commands.Cog):
    def __init__(self,bot,store,active):self.bot,self.store,self.active=bot,store,active
    @commands.Cog.listener()
    async def on_message(self,message):
        if not self.active or not eligible_message(message):return
        try:await self.store.award(message.guild.id,message.author.id,message.id,content_key(message.content))
        except Exception as exc:print('LOTUS XP | State=AWARD_FAILED | Error='+type(exc).__name__,flush=True)
    @app_commands.command(name='rank',description='Show your community level and XP.')
    @app_commands.guild_only()
    async def rank(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.active:
            await interaction.followup.send('Community XP is not enabled.',ephemeral=True);return
        try:
            r=await self.store.rank(interaction.guild_id,interaction.user.id);lv=level(r['xp'])
            await interaction.followup.send(f"Level **{lv}** • **{r['xp']} XP** • Rank **{r['rank'] or 'Unranked'}**\nNext level: {(lv+1)**2*100-r['xp']} XP away.",ephemeral=True)
        except Exception:await interaction.followup.send('XP is temporarily unavailable.',ephemeral=True)
    @app_commands.command(name='leaderboard',description='Show the top ten community XP members.')
    @app_commands.guild_only()
    async def leaderboard(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.active:
            await interaction.followup.send('Community XP is not enabled.',ephemeral=True);return
        try:
            rows=await self.store.leaders(interaction.guild_id)
            lines=[f"{i}. <@{r['user_id']}> — Level {level(r['xp'])}, {r['xp']} XP" for i,r in enumerate(rows,1)]
            await interaction.followup.send('\n'.join(lines) or 'No XP earned yet.',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except Exception:await interaction.followup.send('XP is temporarily unavailable.',ephemeral=True)
    @app_commands.command(name='xpstatus',description='Inspect community XP configuration.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def xpstatus(self,interaction:discord.Interaction):
        await interaction.response.send_message(f'XP active: {self.active}\nConfigured channels: {len(channel_ids())}\n10 XP per eligible message; 60-second cooldown; 200 XP daily cap (UTC).\nPaid-tier access is unchanged.',ephemeral=True)

async def install(bot,database_ready):
    if bot.get_cog('MemberXP'):return
    active=False;store=None
    if enabled() and database_ready and bot.intents.message_content and channel_ids():
        try:
            from app.database import engine
            await ensure_schema(engine);store=XPStore(engine);active=True
        except Exception as exc:print('LOTUS XP | State=SCHEMA_FAILED | Error='+type(exc).__name__,flush=True)
    await bot.add_cog(MemberXP(bot,store,active))
    print(f'LOTUS XP | Active={active} | Channels={len(channel_ids())}',flush=True)
