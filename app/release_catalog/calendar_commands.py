"""Member /calendar and administrator setup commands."""
import discord
from discord import app_commands
from .calendar_runtime import CalendarRuntime
from .calendar_ui import open_calendar
from .calendar_store import VERSION
from .service import CatalogError

class CalendarAdmin(app_commands.Group):
    def __init__(self,runtime):
        super().__init__(name='calendaradmin',description='Set up the release calendar and release-day announcements',
            guild_only=True,default_permissions=discord.Permissions(administrator=True))
        self.runtime=runtime
    async def interaction_check(self,interaction):
        if interaction.guild_id and getattr(interaction.permissions,'administrator',False):return True
        await interaction.response.send_message('Calendar setup requires a server administrator.',ephemeral=True);return False
    async def on_error(self,interaction,error):
        cause=getattr(error,'original',error)
        message=str(cause) if isinstance(cause,CatalogError) else 'Calendar command failed. Check bot channel permissions and Railway logs.'
        if interaction.response.is_done():await interaction.followup.send(message,ephemeral=True)
        else:await interaction.response.send_message(message,ephemeral=True)
    @app_commands.command(name='setup',description='Post or update the pinned calendar entry panel')
    async def setup(self,interaction:discord.Interaction,channel:discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        if channel.guild.id!=interaction.guild_id:raise CatalogError('Select a channel in this server.')
        cfg=await self.runtime.store.settings(interaction.guild_id)
        changes={'channel_id':channel.id}
        if cfg.get('channel_id')!=channel.id:changes['panel_id']=None
        cfg=await self.runtime.store.configure(interaction.guild_id,**changes)
        self.runtime.start()
        await self.runtime.panel(cfg,await self.runtime.entries(interaction.guild_id,fresh=True),create=True)
        await interaction.followup.send(f'Calendar panel is configured in {channel.mention}. Members can open their personal calendar. Release-day pings remain separately configured.',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    @app_commands.command(name='announcements',description='Configure opt-in release-day announcements; no retailer stock check')
    @app_commands.describe(hour='Local hour 0–23; default 9 AM',region='US by default; ALL includes all regional editions',timezone='Default America/New_York')
    async def announcements(self,interaction:discord.Interaction,channel:discord.TextChannel,enabled:bool,
                            hour:app_commands.Range[int,0,23]=9,timezone:str='America/New_York',region:str='US'):
        await interaction.response.defer(ephemeral=True)
        if channel.guild.id!=interaction.guild_id:raise CatalogError('Select a channel in this server.')
        region=region.strip().upper()
        if len(region)>40 or not region:raise CatalogError('Use US, CA, JP, GLOBAL, or ALL.')
        cfg=await self.runtime.store.configure(interaction.guild_id,announcement_channel_id=channel.id,
            announcements_enabled=enabled,announcement_hour=hour,timezone=timezone,announcement_region=region)
        self.runtime.start()
        await interaction.followup.send(f"Release-day announcements {'enabled' if enabled else 'disabled'} in {channel.mention}.\n"
            f"Schedule: {hour:02d}:00 {timezone}; region: {region}.\n"
            'Only exact confirmed dates trigger “releases today.” TBA windows never trigger it. '
            'If enabled after the scheduled hour, remaining releases for today may post; past days are not replayed. '
            'Members must opt in through the calendar and have the matching game role.',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    @app_commands.command(name='access',description='Set the calendar minimum tier; existing default is Lite')
    @app_commands.choices(tier=[app_commands.Choice(name=t,value=t) for t in ('Free','Lite','Premium','Premium+')])
    async def access(self,interaction:discord.Interaction,tier:str):
        await interaction.response.defer(ephemeral=True)
        await self.runtime.store.configure(interaction.guild_id,minimum_tier=tier)
        await interaction.followup.send(f'Calendar and release-day subscription access: {tier} and above. Match the public channel permissions to this tier.',ephemeral=True)
    @app_commands.command(name='image',description='Attach a source-supported product image to a release card')
    async def image(self,interaction:discord.Interaction,release_id:int,source_id:int,image_url:str):
        await interaction.response.defer(ephemeral=True)
        await self.runtime.store.save_image(interaction.guild_id,release_id,source_id,image_url)
        self.runtime.cache.pop(interaction.guild_id,None)
        await interaction.followup.send('Calendar product image saved. Release dates and stock status were not changed.',ephemeral=True)
    @app_commands.command(name='status',description='Inspect calendar configuration and announcement delivery issues')
    async def status(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg=await self.runtime.store.settings(interaction.guild_id)
        rows=await self.runtime.store.delivery_rows(interaction.guild_id)
        problem=[r for r in rows if r['state'] in ('SENDING','UNCERTAIN')]
        e=discord.Embed(title=f'Lotus Calendar {VERSION}',description=
            f"Worker: {self.runtime.state}\nCalendar channel: {cfg.get('channel_id') or 'Not configured'}\n"
            f"Announcement channel: {cfg.get('announcement_channel_id') or 'Not configured'}\n"
            f"Announcements: {'ON' if cfg['announcements_enabled'] else 'OFF'}\n"
            f"Schedule: {cfg['announcement_hour']:02d}:00 {cfg['timezone']}\nRegion: {cfg['announcement_region']}\n"
            f"Access: {cfg['minimum_tier']}+\nUncertain recent deliveries: {len(problem)}\nLast error: {self.runtime.last_error or 'None'}",
            colour=0x667ACD)
        if problem:e.add_field(name='Not automatically replayed',value='\n'.join(f"Release #{r['release_id']} • {r['release_date']} • {r['state']}" for r in problem[:8]),inline=False)
        await interaction.followup.send(embed=e,ephemeral=True)


def register_calendar(bot,catalog,verifier):
    existing=getattr(bot,'release_calendar',None)
    if existing:return existing
    runtime=CalendarRuntime(bot,catalog,verifier)
    @app_commands.command(name='calendar',description='Browse releases, product images, period-end TBA and your game filters')
    @app_commands.guild_only()
    async def calendar_command(interaction:discord.Interaction,month:str|None=None):
        await open_calendar(runtime,interaction,month)
    bot.tree.add_command(calendar_command)
    bot.tree.add_command(CalendarAdmin(runtime))
    bot.release_calendar=runtime
    return runtime
