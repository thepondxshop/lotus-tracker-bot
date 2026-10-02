"""Independent calendar/announcement worker; never blocks the stock event queue."""
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import discord
from .calendar_store import CalendarStore
from .calendar_render import UI_VERSION
from .calendar_render import announcement_embed, month_png, safe, product_image_file
from .service import CatalogError

LOG=logging.getLogger(__name__)


def can_access(member, cfg):
    if getattr(getattr(member,'guild_permissions',None),'administrator',False):return True
    from app.helpers import get_subscription, tier_allows
    return tier_allows(get_subscription(member),cfg.get('minimum_tier','Lite'))


def due(entry, cfg, now):
    local=now.astimezone(ZoneInfo(cfg['timezone']))
    region=str(entry.get('region','')).upper()
    wanted=cfg.get('announcement_region','US').upper()
    return bool(cfg.get('announcements_enabled') and cfg.get('announcement_channel_id')
        and local.hour>=cfg['announcement_hour'] and entry.get('announceable')
        and entry.get('release_date')==local.date().isoformat()
        and (wanted=='ALL' or region in {wanted,'GLOBAL','WORLDWIDE'}))


class CalendarRuntime:
    def __init__(self,bot,catalog,verifier):
        self.bot=bot;self.store=CalendarStore(catalog,verifier)
        self.task=None;self.view=None;self.state='NOT_STARTED';self.last_error=None
        self.cache={};self.panel_signatures={};self.guild_locks={}

    async def entries(self,guild,fresh=False):
        prior=self.cache.get(guild)
        if not fresh and prior and time.monotonic()-prior[0]<30:return prior[1]
        result=await self.store.entries(guild);self.cache[guild]=(time.monotonic(),result);return result

    def start(self):
        from .calendar_ui import CalendarEntry
        if self.view is None:
            self.view=CalendarEntry(self);self.bot.add_view(self.view)
        if self.task is None or self.task.done():self.task=asyncio.create_task(self.run(),name='lotus-member-calendar')
        return self.task

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
        self.state='STOPPED'

    async def channel(self,guild_id,channel_id):
        guild=self.bot.get_guild(guild_id)
        if not guild:raise CatalogError('Server is unavailable.')
        channel=guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not isinstance(channel,discord.TextChannel) or channel.guild.id!=guild_id:
            raise CatalogError('Select a text channel in this server.')
        return channel

    async def panel(self,cfg,entries,*,create=False):
        if not cfg.get('channel_id'):return
        now=datetime.now(ZoneInfo(cfg['timezone']))
        sig=hashlib.sha256(json.dumps([UI_VERSION,now.year,now.month,entries],sort_keys=True,default=str).encode()).hexdigest()
        if not create and self.panel_signatures.get(cfg['guild_id'])==sig:return
        if not cfg.get('panel_id') and not create:return
        channel=await self.channel(cfg['guild_id'],cfg['channel_id'])
        from .calendar_ui import CalendarEntry
        picture=await asyncio.to_thread(month_png,now.year,now.month,entries)
        embed=discord.Embed(title='🪷 Lotus Release Calendar',description=
            'All games are shown here. Use the month buttons to browse privately, or **Week zoom** for larger text and clickable day buttons.\n'
            'Tap the image to enlarge it. **Open my calendar** also lets you choose your games.\n'
            'Release-day pings are optional and start off.\n'
            'Month, quarter, season and year-only releases appear in period-end TBA sections.',colour=0x667ACD)
        embed.set_image(url='attachment://lotus-calendar.png')
        embed.set_footer(text=f"Calendar {UI_VERSION} • Updated from the catalog • {cfg['timezone']}")
        file=discord.File(picture,filename='lotus-calendar.png')
        if cfg.get('panel_id'):
            try:
                await channel.get_partial_message(cfg['panel_id']).edit(embed=embed,attachments=[file],view=CalendarEntry(self),allowed_mentions=discord.AllowedMentions.none())
            except discord.NotFound:
                await self.store.configure(cfg['guild_id'],panel_id=None)
                self.last_error='CALENDAR_PANEL_DELETED_RUN_SETUP'
                return
        else:
            message=await channel.send(embed=embed,file=file,view=CalendarEntry(self),allowed_mentions=discord.AllowedMentions.none())
            await self.store.configure(cfg['guild_id'],panel_id=message.id)
            try:await message.pin(reason='Lotus release calendar')
            except discord.Forbidden:self.last_error='CALENDAR_CREATED_BUT_PIN_PERMISSION_MISSING'
        self.panel_signatures[cfg['guild_id']]=sig

    async def audience(self,cfg,entry,channel):
        from app.config import GAME_ROLES
        from app.helpers import safe_int
        role_id=safe_int(GAME_ROLES.get(entry['game']))
        if not role_id:return []
        result=[]
        for user_id in await self.store.subscribers(cfg['guild_id'],entry['game']):
            try:member=channel.guild.get_member(user_id) or await channel.guild.fetch_member(user_id)
            except (discord.NotFound,discord.Forbidden):continue
            if (not member.bot and can_access(member,cfg) and role_id in {r.id for r in member.roles}
                    and channel.permissions_for(member).view_channel):result.append(member.id)
        return result

    async def announce(self,cfg,entry,now):
        if not due(entry,cfg,now):return
        day=now.astimezone(ZoneInfo(cfg['timezone'])).date()
        channel=await self.channel(cfg['guild_id'],cfg['announcement_channel_id'])
        # Resolve audience before durable claim. All pings are individual opt-ins,
        # never a broad game-role mention that would ping non-subscribers.
        members=await self.audience(cfg,entry,channel)
        key=await self.store.claim(cfg['guild_id'],entry,channel.id,day)
        if not key:return
        embed=announcement_embed(entry,day)
        embed.set_footer(text=f'Lotus release day • {key} • Stock varies by retailer')
        groups=[members[i:i+70] for i in range(0,len(members),70)] or [[]]
        try:
            ids=groups[0]
            picture=await asyncio.to_thread(product_image_file,entry)
            image_args={'file':picture} if picture else {}
            message=await channel.send(content=' '.join(f'<@{x}>' for x in ids) or None,embed=embed,**image_args,
                allowed_mentions=discord.AllowedMentions(everyone=False,roles=False,users=[discord.Object(id=x) for x in ids]))
            await self.store.delivered(key,'SENT',message.id)
        except (discord.Forbidden, discord.NotFound) as error:
            await self.store.delivered(key,'RETRY',error=type(error).__name__)
            raise
        except Exception as error:
            # Ambiguous HTTP outcomes must not replay a ping after a redeploy.
            await self.store.delivered(key,'UNCERTAIN',error=type(error).__name__)
            raise
        for ids in groups[1:]:
            try:
                await channel.send(content=' '.join(f'<@{x}>' for x in ids),
                    allowed_mentions=discord.AllowedMentions(everyone=False,roles=False,users=[discord.Object(id=x) for x in ids]))
            except Exception as error:
                LOG.warning('LOTUS RELEASE DAY MENTION ERROR | Key=%s | Type=%s',key,type(error).__name__)
        LOG.info('LOTUS RELEASE DAY SENT | Release=%s | Game=%s | OptInMentions=%s',entry['id'],entry['game'],len(members))

    async def reconcile(self,cfg,entries):
        """Recover lost acknowledgments; retract changed dates without another ping."""
        by_id={e['id']:e for e in entries}
        for entry in entries:
            for member in entry.get('calendar_members', []):
                by_id[member['id']] = member
        for row in await self.store.delivery_rows(cfg['guild_id']):
            channel=None
            if row['state'] in ('SENDING','UNCERTAIN'):
                attempt=datetime.fromisoformat(row['created_at'])
                if (datetime.now(timezone.utc)-attempt).total_seconds()<90:continue
                channel=await self.channel(cfg['guild_id'],row['channel_id'])
                async for message in channel.history(limit=100,after=attempt,oldest_first=True):
                    if message.author.id==self.bot.user.id and any(row['key'] in (e.footer.text or '') for e in message.embeds):
                        await self.store.delivered(row['key'],'SENT',message.id);break
                continue
            entry=by_id.get(row['release_id'])
            changed=not entry or not entry.get('announceable') or entry.get('release_date')!=row['release_date']
            if row['state']=='SENT' and row.get('message_id') and changed:
                channel=await self.channel(cfg['guild_id'],row['channel_id'])
                embed=discord.Embed(title='Release date updated',description='The date or supporting evidence for this release has changed. Check the release calendar for the current record.',colour=0xF59E0B)
                try:
                    await channel.get_partial_message(row['message_id']).edit(content=None,embed=embed,allowed_mentions=discord.AllowedMentions.none())
                except discord.NotFound:pass
                await self.store.delivered(row['key'],'CORRECTED',row['message_id'])

    async def tick(self):
        now=datetime.now(timezone.utc)
        for cfg in await self.store.configured():
            try:
                entries=await self.entries(cfg['guild_id'],fresh=True)
                # Panel errors do not stop date announcements.
                try:await self.panel(cfg,entries)
                except Exception as error:LOG.warning('LOTUS CALENDAR PANEL | Type=%s',type(error).__name__)
                try:await self.reconcile(cfg,entries)
                except Exception as error:LOG.warning('LOTUS CALENDAR RECONCILE | Type=%s',type(error).__name__)
                for entry in entries:
                    if due(entry,cfg,now):
                        try:await self.announce(cfg,entry,now)
                        except Exception as error:
                            self.last_error=type(error).__name__;LOG.error('LOTUS RELEASE DAY | Release=%s | Type=%s',entry['id'],self.last_error)
            except Exception as error:
                self.last_error=type(error).__name__;LOG.error('LOTUS CALENDAR | Guild=%s | Type=%s',cfg['guild_id'],self.last_error)

    async def run(self):
        await self.bot.wait_until_ready()
        try:
            while not self.bot.is_closed():
                self.state='RUNNING'
                try:await self.tick()
                except Exception as error:
                    self.state='ERROR';self.last_error=type(error).__name__;LOG.error('LOTUS CALENDAR WORKER | Type=%s',self.last_error)
                await asyncio.sleep(60)
        finally:self.state='STOPPED'
