"""Personal ephemeral calendars and a persistent public entry panel."""
import asyncio
import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo
import discord
from .calendar_dates import month_shift
from .calendar_render import month_png, placeholder_png, product_embed, safe
from .calendar_runtime import can_access
from .calendar_store import VERSION


def games_for(entries):
    from app.config import GAME_ROLES
    return sorted(set(GAME_ROLES) | {e['game'] for e in entries})


class OwnedView(discord.ui.View):
    def __init__(self,runtime,guild,user):
        super().__init__(timeout=600);self.runtime=runtime;self.guild_id=guild;self.user_id=user
    async def interaction_check(self,interaction):
        if interaction.guild_id!=self.guild_id or interaction.user.id!=self.user_id:
            await interaction.response.send_message('Open your own calendar to change its filters.',ephemeral=True);return False
        cfg=await self.runtime.store.settings(self.guild_id)
        if not can_access(interaction.user,cfg):
            await interaction.response.send_message(f"Calendar access requires {cfg['minimum_tier']} or above.",ephemeral=True);return False
        return True
    async def on_error(self,interaction,error,item):
        message='The calendar could not update. Try /calendar again; stock monitoring is unaffected.'
        if interaction.response.is_done():await interaction.followup.send(message,ephemeral=True)
        else:await interaction.response.send_message(message,ephemeral=True)


class CalendarEntry(discord.ui.View):
    def __init__(self,runtime):super().__init__(timeout=None);self.runtime=runtime
    @discord.ui.button(label='Open my calendar',style=discord.ButtonStyle.primary,custom_id='lotus:calendar:open:v1')
    async def open(self,interaction,button):
        await open_calendar(self.runtime,interaction)
    @discord.ui.button(label='Release-day ping settings',style=discord.ButtonStyle.secondary,custom_id='lotus:calendar:preferences:v1')
    async def preferences(self,interaction,button):
        cfg=await self.runtime.store.settings(interaction.guild_id)
        if not can_access(interaction.user,cfg):
            await interaction.response.send_message(f"Calendar access requires {cfg['minimum_tier']} or above.",ephemeral=True);return
        await interaction.response.defer(ephemeral=True)
        view=SettingsView(self.runtime,interaction.guild_id,interaction.user.id)
        await view.load()
        await interaction.followup.send(embed=view.embed(),view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    async def on_error(self,interaction,error,item):
        if interaction.response.is_done():await interaction.followup.send('Calendar unavailable; try /calendar again.',ephemeral=True)
        else:await interaction.response.send_message('Calendar unavailable; try /calendar again.',ephemeral=True)


class MonthJump(discord.ui.Modal,title='Choose a calendar month'):
    month=discord.ui.TextInput(label='Month (YYYY-MM)',placeholder='2028-12',max_length=7)
    def __init__(self,parent):super().__init__();self.calendar_owner=parent
    async def on_submit(self,interaction):
        if not await self.calendar_owner.interaction_check(interaction):return
        try:
            d=date.fromisoformat(str(self.month)+'-01')
            if not 2000<=d.year<=2099:raise ValueError()
        except ValueError:
            await interaction.response.send_message('Enter a month such as 2028-12 (years 2000–2099).',ephemeral=True);return
        self.calendar_owner.year,self.calendar_owner.month=d.year,d.month
        self.calendar_owner.mode='month';self.calendar_owner.page=0
        await self.calendar_owner.update(interaction)


class DaySelect(discord.ui.Select):
    def __init__(self,parent,start,end,row):
        self.calendar_owner=parent
        super().__init__(placeholder=f'View a release day ({start}–{end})',row=row,
            options=[discord.SelectOption(label=f'{calendar.month_name[parent.month]} {n}',value=str(n)) for n in range(start,end+1)])
    async def callback(self,interaction):
        self.calendar_owner.mode='day';self.calendar_owner.day=int(self.values[0]);self.calendar_owner.page=0
        await self.calendar_owner.update(interaction)


class CalendarView(OwnedView):
    def __init__(self,runtime,guild,user,year,month):
        super().__init__(runtime,guild,user);self.year=year;self.month=month
        self.mode='month';self.day=None;self.page=0;self.pages=1

    async def render(self):
        self.clear_items()
        entries=await self.runtime.entries(self.guild_id)
        prefs=await self.runtime.store.preference(self.guild_id,self.user_id)
        entries=[e for e in entries if prefs['games'] is None or e['game'] in prefs['games']]
        self.add_item(DaySelect(self,1,16,0))
        self.add_item(DaySelect(self,17,calendar.monthrange(self.year,self.month)[1],1))
        for label,action,style in [('Previous month','prev',discord.ButtonStyle.secondary),('This month','today',discord.ButtonStyle.secondary),
                ('Next month','next',discord.ButtonStyle.secondary),('Jump to month','jump',discord.ButtonStyle.secondary)]:
            b=discord.ui.Button(label=label,style=style,row=2)
            async def callback(i,action=action):
                if action=='jump':await i.response.send_modal(MonthJump(self));return
                if action=='today':
                    cfg=await self.runtime.store.settings(self.guild_id);now=datetime.now(ZoneInfo(cfg['timezone']))
                    self.year,self.month=now.year,now.month
                else:self.year,self.month=month_shift(self.year,self.month,-1 if action=='prev' else 1)
                self.mode='month';self.page=0;await self.update(i)
            b.callback=callback;self.add_item(b)
        for label,action in [('Month overview','month'),('Period-end TBA','tba'),('Undated releases','undated'),('My games / pings','settings')]:
            b=discord.ui.Button(label=label,row=3,style=discord.ButtonStyle.primary if action=='tba' else discord.ButtonStyle.secondary)
            async def callback(i,action=action):
                if action=='settings':
                    await i.response.defer(ephemeral=True)
                    view=SettingsView(self.runtime,self.guild_id,self.user_id);await view.load()
                    await i.followup.send(embed=view.embed(),view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none());return
                self.mode=action;self.page=0;await self.update(i)
            b.callback=callback;self.add_item(b)
        if self.mode=='month':
            picture=await asyncio.to_thread(month_png,self.year,self.month,entries,prefs['games'])
            embed=discord.Embed(title=f'🪷 {calendar.month_name[self.month]} {self.year}',description=
                'Choose a day for product images and release details.\n'
                '**Period-end TBA** contains month, quarter, season and year-only listings.\n'
                'Seasons use Northern Hemisphere meteorological months; Winter starts in December.',colour=0x667ACD)
            embed.set_image(url='attachment://my-calendar.png')
            embed.set_footer(text=f'Calendar {VERSION} • Personal filters • Controls expire after 10 minutes of inactivity')
            return [embed],[discord.File(picture,filename='my-calendar.png')]
        prefix=f'{self.year:04d}-{self.month:02d}'
        if self.mode=='day':
            wanted=f'{prefix}-{self.day:02d}'
            items=[e for e in entries if e.get('period') and not e['period']['tba'] and e['period']['anchor']==wanted]
            heading=f'Releases • {wanted}'
        elif self.mode=='tba':
            items=[e for e in entries if e.get('period') and e['period']['tba'] and e['period']['anchor'].startswith(prefix)]
            heading=f'Period-end TBA • {calendar.month_name[self.month]} {self.year}'
        else:items=[e for e in entries if not e.get('period')];heading='Upcoming • Date TBA'
        items.sort(key=lambda e:((e.get('period') or {}).get('anchor',''),(e.get('period') or {}).get('precision',''),e['game'],e['title'],e['id']))
        self.pages=max(1,(len(items)+2)//3);self.page=min(self.page,self.pages-1)
        header=discord.Embed(title=heading,description=f'{len(items)} products • Page {self.page+1}/{self.pages}\n'+('No matching releases.' if not items else 'Dates and source confidence appear on each product.'),colour=0x667ACD)
        batch=items[self.page*3:self.page*3+3]
        for label,delta in [('Previous products',-1),('Next products',1)]:
            b=discord.ui.Button(label=label,row=4,disabled=(self.page==0 if delta<0 else self.page>=self.pages-1))
            async def callback(i,delta=delta):self.page=max(0,min(self.pages-1,self.page+delta));await self.update(i)
            b.callback=callback;self.add_item(b)
        files=[discord.File(await asyncio.to_thread(placeholder_png),filename='image-pending.png')] if any(not e.get('image_url') for e in batch) else []
        return [header]+[product_embed(e) for e in batch],files

    async def update(self,interaction):
        await interaction.response.defer()
        embeds,files=await self.render()
        await interaction.edit_original_response(embeds=embeds,attachments=files,view=self,allowed_mentions=discord.AllowedMentions.none())


class PreferenceSelect(discord.ui.Select):
    def __init__(self,parent,games,kind,current):
        self.calendar_owner,self.kind=parent,kind
        options=[]
        if kind=='games':options.append(discord.SelectOption(label='All games (including future additions)',value='__ALL__',default=current is None))
        options += [discord.SelectOption(label=g[:100],value=g,default=bool(current and g in current)) for g in games[:24]]
        super().__init__(options=options,min_values=0,max_values=len(options),row=0 if kind=='games' else 1,
            placeholder='Games shown on my calendar' if kind=='games' else 'Release-day pings — choose games or clear to turn off')
    async def callback(self,interaction):
        await interaction.response.defer()
        values=sorted(self.values)
        if self.kind=='games':
            await self.calendar_owner.runtime.store.save_preference(self.calendar_owner.guild_id,self.calendar_owner.user_id,games=None if '__ALL__' in values else values)
        else:await self.calendar_owner.runtime.store.save_preference(self.calendar_owner.guild_id,self.calendar_owner.user_id,announcements=values)
        await self.calendar_owner.load()
        await interaction.edit_original_response(embed=self.calendar_owner.embed(),view=self.calendar_owner,allowed_mentions=discord.AllowedMentions.none())


class SettingsView(OwnedView):
    async def load(self):
        self.clear_items();self.prefs=await self.runtime.store.preference(self.guild_id,self.user_id)
        entries=await self.runtime.entries(self.guild_id);games=games_for(entries)
        self.add_item(PreferenceSelect(self,games,'games',self.prefs['games']))
        self.add_item(PreferenceSelect(self,games,'announcements',self.prefs['announcements']))
    def embed(self):
        shown='All games' if self.prefs['games'] is None else ', '.join(self.prefs['games']) or 'None'
        pings=', '.join(self.prefs['announcements']) or 'Off'
        return discord.Embed(title='My calendar preferences',description=
            f'**Show:** {safe(shown,700)}\n**Release-day pings:** {safe(pings,700)}\n\n'
            'Your choices are saved across restarts. Calendar filters do not change stock-alert preferences.\n'
            'For release-day pings, also select the matching game role in **Choose your games**. '
            'Only subscribed, eligible members are mentioned; the entire game role is never pinged.\n'
            'Clear the second dropdown to turn all release-day pings off.',colour=0x667ACD)


async def open_calendar(runtime,interaction,month=None):
    if not interaction.guild_id:
        await interaction.response.send_message('Open the calendar in your server.',ephemeral=True);return
    cfg=await runtime.store.settings(interaction.guild_id)
    if not can_access(interaction.user,cfg):
        await interaction.response.send_message(f"Calendar access requires {cfg['minimum_tier']} or above.",ephemeral=True);return
    try:
        now=datetime.now(ZoneInfo(cfg['timezone']))
        start=date.fromisoformat(month+'-01') if month else now.date()
        if not 2000<=start.year<=2099:raise ValueError()
    except ValueError:
        await interaction.response.send_message('Use a month such as 2028-12 (years 2000–2099).',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    view=CalendarView(runtime,interaction.guild_id,interaction.user.id,start.year,start.month)
    embeds,files=await view.render()
    await interaction.followup.send(embeds=embeds,files=files,view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
