"""Private durable support tickets and default Free-role assignment."""
import asyncio
import os
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import text

OPEN_CHANNEL = 1541940377412698223
INFO_CHANNEL = 1541940190422114374
SUPPORT_INFO = (
    '**PonDeX Support**\nOpen a private ticket in <#1541940377412698223>. '
    'Each ticket receives a unique number and is visible to you, server administrators, '
    'and the configured support team. Please describe the issue and include useful screenshots; '
    'never share passwords, payment details, or bot tokens.\n\n'
    'Use **Close ticket** when resolved. Any human reply resets the inactivity timer. '
    'We remind you after **12 hours** and **20 hours**, then close after **24 hours** '
    'without a human reply. Closed tickets remain private and read-only for support history. '
    'You can open another ticket if you still need help. Ticket messages do not earn XP.'
)

def phase(age, reminder):
    if age >= 86400:return 'close'
    if age >= 72000 and reminder < 20:return '20'
    if age >= 43200 and reminder < 12:return '12'
    return None

def support_ids():
    return {int(x) for x in os.getenv('LOTUS_SUPPORT_ROLE_IDS','').split(',') if x.strip().isdigit()}

def can_close(member, owner):
    return member.id == owner or member.guild_permissions.manage_channels or bool({r.id for r in member.roles} & support_ids())

async def schema(engine):
    async with engine.begin() as c:
        await c.execute(text('SELECT pg_advisory_xact_lock(76290415)'))
        await c.execute(text('''CREATE TABLE IF NOT EXISTS lotus_support_tickets (
            id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,
            channel_id BIGINT UNIQUE,state TEXT NOT NULL DEFAULT 'CREATING',
            last_activity TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reminder INTEGER NOT NULL DEFAULT 0,close_reason TEXT)'''))
        await c.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS lotus_ticket_one_active ON lotus_support_tickets(guild_id,user_id) WHERE state IN ('CREATING','OPEN','CLOSING')"))
        await c.execute(text('''CREATE TABLE IF NOT EXISTS lotus_support_panels (
            channel_id BIGINT PRIMARY KEY,message_id BIGINT NOT NULL)'''))

class TicketView(discord.ui.View):
    def __init__(self,cog):super().__init__(timeout=None);self.cog=cog
    @discord.ui.button(label='Open support ticket',style=discord.ButtonStyle.primary,custom_id='lotus:support:open:177')
    async def open_ticket(self,interaction:discord.Interaction,button:discord.ui.Button):
        await self.cog.open_ticket(interaction)

class CloseView(discord.ui.View):
    def __init__(self,cog):super().__init__(timeout=None);self.cog=cog
    @discord.ui.button(label='Close ticket',style=discord.ButtonStyle.danger,custom_id='lotus:support:close:177')
    async def close_ticket(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        async with self.cog.engine.begin() as c:
            row=(await c.execute(text('SELECT * FROM lotus_support_tickets WHERE channel_id=:id FOR UPDATE'),dict(id=interaction.channel_id))).mappings().first()
            if not row or not can_close(interaction.user,row['user_id']):
                await interaction.followup.send('Only the ticket owner or support team can close this ticket.',ephemeral=True);return
            if row['state'] != 'OPEN':
                await interaction.followup.send('This ticket is already closed or closing.',ephemeral=True);return
            await c.execute(text("UPDATE lotus_support_tickets SET state='CLOSING',close_reason='MEMBER_OR_STAFF' WHERE id=:id"),dict(id=row['id']))
        await self.cog.finish_close(dict(row))
        await interaction.followup.send('Ticket closed and retained as private support history.',ephemeral=True)

class CommunitySupport(commands.Cog):
    def __init__(self,bot,engine):self.bot=bot;self.engine=engine
    async def cog_load(self):
        if self.engine:
            self.bot.add_view(TicketView(self));self.bot.add_view(CloseView(self))
            self.sweep.start()
    async def cog_unload(self):self.sweep.cancel()
    @commands.Cog.listener()
    async def on_member_join(self,member):
        if member.bot:return
        from app.config import SUBSCRIPTION_ROLES
        raw=str(SUBSCRIPTION_ROLES.get('Free') or '')
        if not raw.isdigit():
            print('LOTUS FREE ROLE | State=ROLE_FREE_MISSING',flush=True);return
        role=member.guild.get_role(int(raw))
        paid={str(v) for k,v in SUBSCRIPTION_ROLES.items() if k != 'Free'}
        if role is None or raw in paid or role.managed or role.is_default() or role.permissions.administrator:
            print('LOTUS FREE ROLE | State=INVALID_ROLE',flush=True);return
        if role in member.roles:return
        try:await member.add_roles(role,reason='Lotus default Free membership on join')
        except discord.HTTPException as exc:print('LOTUS FREE ROLE | State=FAILED | Error='+type(exc).__name__,flush=True)
    async def open_ticket(self,interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None or interaction.channel_id != OPEN_CHANNEL or interaction.user.bot:
            await interaction.followup.send(f'Open tickets in <#{OPEN_CHANNEL}>.',ephemeral=True);return
        guild=interaction.guild
        async with self.engine.begin() as c:
            # Serialize opening per guild/member across processes.
            await c.execute(text('SELECT pg_advisory_xact_lock(:key)'),dict(key=(guild.id ^ interaction.user.id) & ((1<<63)-1)))
            row=(await c.execute(text("SELECT * FROM lotus_support_tickets WHERE guild_id=:g AND user_id=:u AND state IN ('CREATING','OPEN','CLOSING')"),dict(g=guild.id,u=interaction.user.id))).mappings().first()
            if row:
                location=f"<#{row['channel_id']}>" if row['channel_id'] else 'being created; ask an admin if this persists'
                await interaction.followup.send('Your existing ticket is '+location+'.',ephemeral=True);return
            tid=await c.scalar(text('INSERT INTO lotus_support_tickets(guild_id,user_id) VALUES (:g,:u) RETURNING id'),dict(g=guild.id,u=interaction.user.id))
        overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False),
            guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True),
            interaction.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)}
        for rid in support_ids():
            role=guild.get_role(rid)
            if role and not role.is_default():overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
        # A CREATING row survives an ambiguous API response; never blindly create a second channel.
        try:
            channel=await guild.create_text_channel(f'ticket-{tid:06d}',category=interaction.channel.category,
                overwrites=overwrites,topic=f'Lotus ticket {tid}; owner {interaction.user.id}',reason='Member requested private support')
            async with self.engine.begin() as c:
                await c.execute(text("UPDATE lotus_support_tickets SET channel_id=:c,state='OPEN',last_activity=CURRENT_TIMESTAMP WHERE id=:id"),dict(c=channel.id,id=tid))
            await channel.send(f'{interaction.user.mention} — **Ticket #{tid:06d}**\nDescribe your issue here. Reminders at 12/20 hours; automatic closure at 24 hours without a human reply.',
                view=CloseView(self),allowed_mentions=discord.AllowedMentions(users=[interaction.user],roles=False,everyone=False))
            await interaction.followup.send(f'Your private ticket: {channel.mention}',ephemeral=True)
        except discord.HTTPException as exc:
            print(f'LOTUS TICKET | State=OPEN_UNRESOLVED | ID={tid} | Error={type(exc).__name__}',flush=True)
            await interaction.followup.send(f'Ticket #{tid} needs administrator review; no automatic duplicate will be created.',ephemeral=True)
    @commands.Cog.listener()
    async def on_message(self,message):
        if not self.engine or not message.guild or message.author.bot or message.webhook_id:return
        if not str(getattr(message.channel,'name','')).startswith('ticket-'):return
        async with self.engine.begin() as c:
            await c.execute(text("UPDATE lotus_support_tickets SET last_activity=CURRENT_TIMESTAMP,reminder=0 WHERE channel_id=:c AND state='OPEN'"),dict(c=message.channel.id))
    async def finish_close(self,row):
        guild=self.bot.get_guild(row['guild_id'])
        if not guild:return
        channel=guild.get_channel(row['channel_id'])
        if channel:
            # Freeze every explicit participant overwrite, preserving privacy.
            overwrites=channel.overwrites
            for target,overwrite in overwrites.items():
                if target.id != guild.me.id:
                    overwrite.send_messages=False;overwrite.send_messages_in_threads=False
                    overwrite.create_public_threads=False;overwrite.create_private_threads=False
            await channel.edit(overwrites=overwrites,topic=f"Closed Lotus ticket {row['id']}; private support history")
        async with self.engine.begin() as c:
            await c.execute(text("UPDATE lotus_support_tickets SET state='CLOSED' WHERE id=:id AND state='CLOSING'"),dict(id=row['id']))
        if channel:await channel.send('🔒 Ticket closed. You may open a new ticket if you need further help.',allowed_mentions=discord.AllowedMentions.none())
    @tasks.loop(seconds=60)
    async def sweep(self):
        try:
            async with self.engine.connect() as c:
                rows=(await c.execute(text("SELECT * FROM lotus_support_tickets WHERE state IN ('OPEN','CLOSING')"))).mappings().all()
            for original in rows:
                row=dict(original)
                if row['state']=='CLOSING':
                    await self.finish_close(row);continue
                # Row lock makes a simultaneous reply/reset win before the inactivity decision.
                async with self.engine.begin() as c:
                    fresh=(await c.execute(text("SELECT *,EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-last_activity)) AS age FROM lotus_support_tickets WHERE id=:id AND state='OPEN' FOR UPDATE SKIP LOCKED"),dict(id=row['id']))).mappings().first()
                    if not fresh:continue
                    action=phase(float(fresh['age']),fresh['reminder'])
                    if not action:continue
                    if action=='close':
                        await c.execute(text("UPDATE lotus_support_tickets SET state='CLOSING',close_reason='INACTIVE_24H' WHERE id=:id"),dict(id=row['id']))
                    else:
                        await c.execute(text('UPDATE lotus_support_tickets SET reminder=:r WHERE id=:id'),dict(r=int(action),id=row['id']))
                if action=='close':await self.finish_close(row)
                else:
                    channel=self.bot.get_channel(row['channel_id'])
                    if channel:await channel.send(f"Ticket #{row['id']:06d}: no human reply for {action} hours. It closes at <t:{int(row['last_activity'].timestamp())+86400}:F> unless someone replies.",allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:print('LOTUS TICKET | State=SWEEP_FAILED | Error='+type(exc).__name__,flush=True)
    @sweep.before_loop
    async def before_sweep(self):await self.bot.wait_until_ready()
    @app_commands.command(name='supportsetup',description='Publish or refresh the support info and persistent Open ticket panel.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def supportsetup(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.engine:
            await interaction.followup.send('Support database unavailable.',ephemeral=True);return
        for cid,content,view in ((INFO_CHANNEL,SUPPORT_INFO,None),(OPEN_CHANNEL,'Need help? Open a private numbered support ticket below.',TicketView(self))):
            channel=interaction.guild.get_channel(cid)
            if not channel:
                await interaction.followup.send(f'Missing channel {cid}.',ephemeral=True);return
            async with self.engine.begin() as c:
                await c.execute(text('SELECT pg_advisory_xact_lock(:id)'),dict(id=cid))
                mid=await c.scalar(text('SELECT message_id FROM lotus_support_panels WHERE channel_id=:id'),dict(id=cid))
                try:message=await channel.fetch_message(mid) if mid else None
                except discord.NotFound:message=None
                if message:await message.edit(content=content,view=view,allowed_mentions=discord.AllowedMentions.none())
                else:
                    message=await channel.send(content,view=view,allowed_mentions=discord.AllowedMentions.none())
                    await c.execute(text('INSERT INTO lotus_support_panels(channel_id,message_id) VALUES (:c,:m) ON CONFLICT(channel_id) DO UPDATE SET message_id=:m'),dict(c=cid,m=message.id))
        await interaction.followup.send('Support info and ticket panel are ready.',ephemeral=True)

    @app_commands.command(name='ticketrepair',description='Recover an interrupted ticket opening without creating duplicate channels.')
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticketrepair(self,interaction:discord.Interaction,number:int):
        await interaction.response.defer(ephemeral=True)
        if not self.engine:
            await interaction.followup.send('Support database unavailable.',ephemeral=True);return
        channels=await interaction.guild.fetch_channels()
        async with self.engine.begin() as c:
            row=(await c.execute(text("SELECT * FROM lotus_support_tickets WHERE id=:id AND guild_id=:g AND state='CREATING' FOR UPDATE"),dict(id=number,g=interaction.guild_id))).mappings().first()
            if not row:
                await interaction.followup.send('No interrupted opening found.',ephemeral=True);return
            matches=[ch for ch in channels if getattr(ch,'topic',None)==f"Lotus ticket {number}; owner {row['user_id']}"]
            if len(matches)>1:
                await interaction.followup.send('Multiple matching channels; review manually.',ephemeral=True);return
            if matches:
                channel=matches[0]
                if channel.overwrites_for(interaction.guild.default_role).view_channel is not False:
                    await interaction.followup.send('Channel privacy must be repaired first.',ephemeral=True);return
                await c.execute(text("UPDATE lotus_support_tickets SET state='OPEN',channel_id=:c,last_activity=CURRENT_TIMESTAMP WHERE id=:id"),dict(id=number,c=channel.id))
            else:await c.execute(text("UPDATE lotus_support_tickets SET state='CLOSED',close_reason='NO_CHANNEL_AFTER_REVIEW' WHERE id=:id"),dict(id=number))
        if matches:await channel.send('Support ticket recovered.',view=CloseView(self))
        await interaction.followup.send('Recovered the ticket.' if matches else 'Confirmed no matching channel; member may try opening again.',ephemeral=True)

async def install(bot,database_ready):
    engine=None
    if database_ready:
        from app.database import engine as db_engine
        try:await schema(db_engine);engine=db_engine
        except Exception as exc:print('LOTUS TICKET | State=SCHEMA_FAILED | Error='+type(exc).__name__,flush=True)
    if not bot.get_cog('CommunitySupport'):await bot.add_cog(CommunitySupport(bot,engine))
