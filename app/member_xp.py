"""Opt-in member activity XP. PostgreSQL persistence; no paid role changes."""
import hashlib
import math
import secrets
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

COMMANDS_CHANNEL = 1541940028165591140
LEVELS_CHANNEL = 1563288538433192076
EXCLUDED_CHANNELS = {COMMANDS_CHANNEL, 1541940125343293561, LEVELS_CHANNEL, 1541940377412698223}

def level_cost(target_level):
    """Cost of entering a level; each tenth level costs 50% extra."""
    return target_level * (150 if target_level % 10 == 0 else 100)

def level_floor(lv):
    milestones = lv // 10
    return 50 * lv * (lv + 1) + 250 * milestones * (milestones + 1)

def level(xp):
    total = max(0, int(xp))
    low = 0
    # The ordinary curve provides an upper bound; milestone costs only add XP.
    high = (math.isqrt(1 + total // 50 * 4) - 1) // 2 + 1
    while low + 1 < high:
        mid = (low + high) // 2
        if level_floor(mid) <= total:
            low = mid
        else:
            high = mid
    return low

def chat_allowed(message, overrides=None):
    channel = message.channel
    ids = {channel.id, getattr(channel, 'parent_id', None), getattr(channel, 'category_id', None)}
    if ids & EXCLUDED_CHANNELS or any((overrides or {}).get(cid) is False for cid in ids):
        return False
    if str(getattr(channel, 'name', '')).startswith('ticket-'):
        return False
    # A parent ticket channel also excludes its threads.
    if str(getattr(getattr(channel, 'parent', None), 'name', '')).startswith('ticket-'):
        return False
    return True

def cosmetic_role(guild,role):
    """Reject roles that grant permissions or are used for game/paid access."""
    from app.config import GAME_ROLES, SUBSCRIPTION_ROLES
    protected={str(v) for v in list(GAME_ROLES.values())+list(SUBSCRIPTION_ROLES.values())}
    if role is None or str(role.id) in protected or role.is_default() or role.managed or role.permissions.value:
        return False
    if guild.me is None or not guild.me.guild_permissions.manage_roles or role>=guild.me.top_role:
        return False
    for channel in guild.channels:
        allow,_=channel.overwrites_for(role).pair()
        if allow.value:return False
    return True

def content_key(content):
    normalized=' '.join(str(content or '').casefold().split())
    if len(normalized)<12 or normalized.startswith(('!','/','http://','https://')):
        return None
    if sum(c.isalnum() for c in normalized)<8 or len(set(normalized))<5:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()

def eligible_message(message,allowed_channels=None):
    return (message.guild is not None and not message.author.bot and not message.webhook_id
            and message.channel.id in (channel_ids() if allowed_channels is None else allowed_channels)
            and content_key(message.content) is not None)

def award_amount(row,key,message_id,now):
    if row.get('enabled') is False:return 0
    if message_id<=int(row['last_message_id']):return 0
    previous=row['last_awarded_at']
    if previous is not None and (now-previous).total_seconds()<60:return 0
    if row['last_content_hash']==key:return 0
    return secrets.randbelow(11) + 10

async def ensure_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text('SELECT pg_advisory_xact_lock(76290414)'))
        await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_member_xp (
            guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, xp BIGINT NOT NULL DEFAULT 0,
            day DATE NOT NULL DEFAULT CURRENT_DATE, daily_xp INTEGER NOT NULL DEFAULT 0,
            last_awarded_at TIMESTAMPTZ, last_message_id BIGINT NOT NULL DEFAULT 0,
            last_content_hash TEXT, PRIMARY KEY(guild_id,user_id))'''))
        await conn.execute(text('CREATE INDEX IF NOT EXISTS lotus_member_xp_ranking ON lotus_member_xp(guild_id,xp DESC,user_id)'))
        await conn.execute(text('ALTER TABLE lotus_member_xp ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE'))
        await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_xp_channels (
            guild_id BIGINT NOT NULL,channel_id BIGINT NOT NULL,enabled BOOLEAN NOT NULL,
            PRIMARY KEY(guild_id,channel_id))'''))
        await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_xp_adjustments (
            id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,
            actor_id BIGINT NOT NULL,delta INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)'''))
        await conn.execute(text('''CREATE TABLE IF NOT EXISTS lotus_xp_rewards (
            guild_id BIGINT NOT NULL,level INTEGER NOT NULL,role_id BIGINT NOT NULL,
            PRIMARY KEY(guild_id,level))'''))

class XPStore:
    def __init__(self,engine):self.engine=engine
    async def rewards(self):
        async with self.engine.connect() as conn:
            rows=(await conn.execute(text('SELECT guild_id,level,role_id FROM lotus_xp_rewards'))).mappings().all()
        result={}
        for row in rows:result.setdefault(row['guild_id'],{})[row['level']]=row['role_id']
        return result
    async def set_reward(self,guild,lv,role_id):
        async with self.engine.begin() as conn:
            if role_id is None:
                await conn.execute(text('DELETE FROM lotus_xp_rewards WHERE guild_id=:g AND level=:l'),dict(g=guild,l=lv))
            else:
                await conn.execute(text('''INSERT INTO lotus_xp_rewards(guild_id,level,role_id) VALUES (:g,:l,:r)
                    ON CONFLICT(guild_id,level) DO UPDATE SET role_id=:r'''),dict(g=guild,l=lv,r=role_id))
    async def configured_channels(self):
        async with self.engine.connect() as conn:
            rows=(await conn.execute(text('SELECT guild_id,channel_id,enabled FROM lotus_xp_channels'))).mappings().all()
        result={}
        for row in rows:result.setdefault(row['guild_id'],{})[row['channel_id']]=row['enabled']
        return result
    async def set_channel(self,guild_id,channel_id,enabled):
        async with self.engine.begin() as conn:
            await conn.execute(text('''INSERT INTO lotus_xp_channels(guild_id,channel_id,enabled) VALUES (:g,:c,:e)
                ON CONFLICT(guild_id,channel_id) DO UPDATE SET enabled=:e'''),dict(g=guild_id,c=channel_id,e=enabled))
    async def adjust(self,guild_id,user_id,actor_id,delta):
        if type(delta) is not int or not -10000<=delta<=10000 or delta==0:
            raise ValueError('Use a nonzero adjustment between -10000 and 10000 XP.')
        async with self.engine.begin() as conn:
            args=dict(g=guild_id,u=user_id)
            await conn.execute(text('INSERT INTO lotus_member_xp(guild_id,user_id) VALUES (:g,:u) ON CONFLICT DO NOTHING'),args)
            row=(await conn.execute(text('SELECT xp,enabled FROM lotus_member_xp WHERE guild_id=:g AND user_id=:u FOR UPDATE'),args)).mappings().one()
            if not row['enabled']:raise ValueError('This member opted out of XP.')
            actual=max(0,int(row['xp'])+delta)-int(row['xp'])
            await conn.execute(text('UPDATE lotus_member_xp SET xp=xp+:d WHERE guild_id=:g AND user_id=:u'),dict(args,d=actual))
            await conn.execute(text('INSERT INTO lotus_xp_adjustments(guild_id,user_id,actor_id,delta) VALUES (:g,:u,:a,:d)'),dict(args,a=actor_id,d=actual))
            return int(row['xp'])+actual
    async def privacy(self,guild_id,user_id,enabled):
        async with self.engine.begin() as conn:
            # Reset personal progress when opting out. Keep only the opt-out identity
            # needed to prevent the next message from silently re-enrolling the member.
            await conn.execute(text('''INSERT INTO lotus_member_xp(guild_id,user_id,enabled) VALUES (:g,:u,:enabled)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET enabled=:enabled,
                xp=CASE WHEN :enabled THEN lotus_member_xp.xp ELSE 0 END,
                daily_xp=CASE WHEN :enabled THEN lotus_member_xp.daily_xp ELSE 0 END,
                last_content_hash=CASE WHEN :enabled THEN lotus_member_xp.last_content_hash ELSE NULL END,
                last_awarded_at=CASE WHEN :enabled THEN lotus_member_xp.last_awarded_at ELSE NULL END,
                last_message_id=CASE WHEN :enabled THEN lotus_member_xp.last_message_id ELSE 0 END'''),
                dict(g=guild_id,u=user_id,enabled=enabled))
            if not enabled:
                await conn.execute(text('DELETE FROM lotus_xp_adjustments WHERE guild_id=:g AND user_id=:u'),dict(g=guild_id,u=user_id))
    async def award(self,guild_id,user_id,message_id,key,*,with_progress=False):
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
            return (amount,int(row['xp']),int(row['xp'])+amount) if with_progress else amount
    async def rank(self,guild_id,user_id):
        async with self.engine.connect() as conn:
            row=(await conn.execute(text('''SELECT xp, 1+(SELECT count(*) FROM lotus_member_xp b
                WHERE b.guild_id=a.guild_id AND b.enabled AND b.xp>a.xp) AS rank
                FROM lotus_member_xp a WHERE guild_id=:g AND user_id=:u AND enabled'''),dict(g=guild_id,u=user_id))).mappings().first()
            return dict(row) if row else dict(xp=0,rank=None)
    async def leaders(self,guild_id,limit=10):
        if limit not in (10,15,20):raise ValueError("Choose 10, 15 or 20.")
        async with self.engine.connect() as conn:
            return (await conn.execute(text('SELECT user_id,xp FROM lotus_member_xp WHERE guild_id=:g AND enabled AND xp>0 ORDER BY xp DESC,user_id LIMIT :limit'),dict(g=guild_id,limit=limit))).mappings().all()

class MemberXP(commands.Cog):
    def __init__(self,bot,store,active):
        self.bot,self.store,self.active=bot,store,active
        self.channel_overrides={}
        self.reward_roles={}
    async def interaction_check(self, interaction):
        if interaction.channel_id != COMMANDS_CHANNEL:
            await interaction.response.send_message(f'Use XP commands in <#{COMMANDS_CHANNEL}>.', ephemeral=True)
            return False
        return True
    @app_commands.command(name='xpreward',description='Configure a cosmetic level role, or remove its future assignment.')
    @app_commands.default_permissions(manage_guild=True,manage_roles=True)
    @app_commands.checks.has_permissions(manage_guild=True,manage_roles=True)
    @app_commands.guild_only()
    async def xpreward(self,interaction:discord.Interaction,at_level:app_commands.Range[int,1,300],role:discord.Role|None=None):
        await interaction.response.defer(ephemeral=True)
        if self.store is None:
            await interaction.followup.send('XP database unavailable.',ephemeral=True);return
        if role is not None and (role.guild.id!=interaction.guild_id or not cosmetic_role(interaction.guild,role)):
            await interaction.followup.send('Choose a cosmetic role below Lotus, with no permissions/channel grants, not a game or paid-tier role.',ephemeral=True);return
        await self.store.set_reward(interaction.guild_id,at_level,role.id if role else None)
        rewards=self.reward_roles.setdefault(interaction.guild_id,{})
        if role:rewards[at_level]=role.id
        else:rewards.pop(at_level,None)
        await interaction.followup.send('Reward setting saved. Earned roles apply on the next qualifying XP award. Removing a setting does not revoke previously earned roles.',ephemeral=True)
    async def sync_rewards(self,member,xp):
        current={r.id for r in member.roles}
        for threshold,rid in self.reward_roles.get(member.guild.id,{}).items():
            if level(xp)<threshold or rid in current:continue
            role=member.guild.get_role(rid)
            if cosmetic_role(member.guild,role):
                await member.add_roles(role,reason='Lotus community level reward')
                current.add(rid)
    def channels(self,guild_id):
        result=channel_ids()
        for cid,on in self.channel_overrides.get(guild_id,{}).items():
            if on:result.add(cid)
            else:result.discard(cid)
        return result
    @app_commands.command(name='xpsetup',description='Enable or disable message XP in a selected channel.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def xpsetup(self,interaction:discord.Interaction,channel:discord.TextChannel,enabled:bool=True):
        await interaction.response.defer(ephemeral=True)
        if self.store is None:
            await interaction.followup.send('XP database is unavailable.',ephemeral=True);return
        if channel.guild.id!=interaction.guild_id:
            await interaction.followup.send('Choose a channel in this server.',ephemeral=True);return
        await self.store.set_channel(interaction.guild_id,channel.id,enabled)
        self.channel_overrides.setdefault(interaction.guild_id,{})[channel.id]=enabled
        await interaction.followup.send(
            f'XP channel setting saved: {channel.mention} — {"ON" if enabled else "OFF"}.\n'
            +('XP listener is active.' if self.active else 'To start XP, set LOTUS_XP_ENABLED=true and LOTUS_XP_MESSAGE_CONTENT=true in Railway, enable Message Content Intent in Discord, and redeploy.'),
            ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    @app_commands.command(name='xpadjust',description='Correct member XP; changes are audited and do not grant paid roles.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def xpadjust(self,interaction:discord.Interaction,member:discord.Member,delta:app_commands.Range[int,-10000,10000]):
        await interaction.response.defer(ephemeral=True)
        if self.store is None or member.bot or member.guild.id!=interaction.guild_id:
            await interaction.followup.send('XP database/member unavailable.',ephemeral=True);return
        try:
            xp=await self.store.adjust(interaction.guild_id,member.id,interaction.user.id,delta)
            await interaction.followup.send(f'XP corrected: {xp} XP, level {level(xp)}. Paid roles unchanged.',ephemeral=True)
        except ValueError as exc:await interaction.followup.send(str(exc),ephemeral=True)
    @app_commands.command(name='xpprivacy',description='Opt out and erase XP progress, or opt back in.')
    @app_commands.guild_only()
    @app_commands.choices(action=[app_commands.Choice(name='Opt out and erase my XP',value='out'),app_commands.Choice(name='Opt back in',value='in')])
    async def xpprivacy(self,interaction:discord.Interaction,action:app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        if self.store is None:
            await interaction.followup.send('XP is inactive. Ask an administrator to handle any existing XP data request.',ephemeral=True);return
        try:
            await self.store.privacy(interaction.guild_id,interaction.user.id,action.value=='in')
            await interaction.followup.send('XP enabled; previous erased progress is not restored.' if action.value=='in' else 'XP disabled and progress erased. Your guild/member IDs remain only to remember the opt-out. Paid roles are unchanged.',ephemeral=True)
        except Exception:await interaction.followup.send('XP privacy update failed; no success is confirmed. Please contact an administrator.',ephemeral=True)
    @commands.Cog.listener()
    async def on_message(self,message):
        if not self.active or message.guild is None or not chat_allowed(message,self.channel_overrides.get(message.guild.id)):
            return
        if not eligible_message(message,{message.channel.id}):return
        # Exclude this bot's recognized prefix commands as well as slash/bang commands.
        if hasattr(self.bot, 'get_context'):
            context = await self.bot.get_context(message)
            if context.valid:return
        try:
            result=await self.store.award(message.guild.id,message.author.id,message.id,content_key(message.content),with_progress=True)
            if not result:return
            awarded,before,after=result
            if self.reward_roles.get(message.guild.id):
                try:await self.sync_rewards(message.author,after)
                except discord.HTTPException as exc:print('LOTUS XP | State=REWARD_FAILED | Error='+type(exc).__name__,flush=True)
            if level(after)>level(before):
                channel=message.guild.get_channel(LEVELS_CHANNEL)
                if channel:
                    await channel.send(f'🎉 {message.author.mention} reached **Level {level(after)}**! **{after} XP** total.',
                        allowed_mentions=discord.AllowedMentions(users=[message.author],roles=False,everyone=False))
                else:print('LOTUS XP | State=LEVEL_CHANNEL_MISSING',flush=True)
        except Exception as exc:print('LOTUS XP | State=AWARD_OR_NOTICE_FAILED | Error='+type(exc).__name__,flush=True)
    async def show_level(self,interaction):
        await interaction.response.defer(ephemeral=False)
        if not self.active:
            await interaction.followup.send('Community XP is not enabled.');return
        try:
            r=await self.store.rank(interaction.guild_id,interaction.user.id);lv=level(r['xp'])
            await interaction.followup.send(f"{interaction.user.mention} — Level **{lv}** • **{r['xp']} XP** • Rank **{r['rank'] or 'Unranked'}**\n"
                f"Progress: {r['xp']-level_floor(lv)}/{level_cost(lv+1)} XP toward level {lv+1}.",allowed_mentions=discord.AllowedMentions.none())
        except Exception:await interaction.followup.send('XP is temporarily unavailable.')
    @app_commands.command(name='level',description='Show your community level and XP in bot-commands.')
    @app_commands.guild_only()
    async def level_command(self,interaction:discord.Interaction):
        await self.show_level(interaction)
    @app_commands.command(name='rank',description='Alias for /level; show your public community rank.')
    @app_commands.guild_only()
    async def rank(self,interaction:discord.Interaction):
        await self.show_level(interaction)
    @app_commands.command(name='leaderboard',description='Show this server’s top 10, 15 or 20 members in bot-commands.')
    @app_commands.guild_only()
    @app_commands.choices(top=[app_commands.Choice(name=str(n),value=n) for n in (10,15,20)])
    async def leaderboard(self,interaction:discord.Interaction,top:int=10):
        await interaction.response.defer(ephemeral=False)
        if not self.active:
            await interaction.followup.send('Community XP is not enabled.');return
        try:
            rows=await self.store.leaders(interaction.guild_id,top)
            lines=[f"{i}. <@{r['user_id']}> — Level {level(r['xp'])}, {r['xp']} XP" for i,r in enumerate(rows,1)]
            await interaction.followup.send('\n'.join(lines) or 'No XP earned yet.',allowed_mentions=discord.AllowedMentions.none())
        except Exception:await interaction.followup.send('XP is temporarily unavailable.')
    @app_commands.command(name='xpstatus',description='Inspect community XP configuration.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def xpstatus(self,interaction:discord.Interaction):
        visible=[cid for cid in self.channels(interaction.guild_id) if interaction.guild.get_channel(cid)]
        await interaction.response.send_message(f'XP active: {self.active}\nSaved enabled channel overrides: {len(visible)}\n10–20 random XP per active minute; no idle XP or daily cap. All chat channels by default; excluded channels and tickets never earn XP.\nUse /xpsetup to save channel settings. Paid-tier access is unchanged.',ephemeral=True)

async def install(bot,database_ready):
    if bot.get_cog('MemberXP'):return
    active=False;store=None
    if database_ready:
        try:
            from app.database import engine
            await ensure_schema(engine);store=XPStore(engine)
            overrides=await store.configured_channels()
            rewards=await store.rewards()
            active=enabled() and bot.intents.message_content
        except Exception as exc:
            store=None;active=False
            print('LOTUS XP | State=SCHEMA_FAILED | Error='+type(exc).__name__,flush=True)
    cog=MemberXP(bot,store,active)
    if store is not None:
        cog.channel_overrides=overrides
        cog.reward_roles=rewards
    await bot.add_cog(cog)
    print(f'LOTUS XP | Active={active} | Channels={len(channel_ids())}',flush=True)
