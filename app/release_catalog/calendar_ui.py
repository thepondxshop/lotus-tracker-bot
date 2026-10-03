from .calendar_filters import filter_editions
"""Personal ephemeral calendars and a persistent public entry panel."""
import asyncio
import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo
import discord
from .calendar_dates import month_shift
from .calendar_render import month_png, placeholder_png, product_embed, safe, product_image_file
from .calendar_runtime import can_access
from .calendar_render import UI_VERSION


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
    @discord.ui.button(label='◀ Previous month',style=discord.ButtonStyle.secondary,custom_id='lotus:calendar:previous:v2',row=0)
    async def previous(self,interaction,button):
        await open_calendar(self.runtime,interaction,offset=-1)
    @discord.ui.button(label='Next month ▶',style=discord.ButtonStyle.secondary,custom_id='lotus:calendar:next:v2',row=0)
    async def next_month(self,interaction,button):
        await open_calendar(self.runtime,interaction,offset=1)
    @discord.ui.button(label='Week zoom',style=discord.ButtonStyle.primary,custom_id='lotus:calendar:week:v2',row=1)
    async def week_zoom(self,interaction,button):
        await open_calendar(self.runtime,interaction,mode='week')
    @discord.ui.button(label='Release-day ping settings',row=1,style=discord.ButtonStyle.secondary,custom_id='lotus:calendar:preferences:v1')
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
        self.calendar_owner.mode='month';self.calendar_owner.page=0;self.calendar_owner.week=0
        await self.calendar_owner.update(interaction)


def exact_on(entries, day):
    return sorted((e for e in entries if e.get('period') and not e['period']['tba']
                   and e['period']['anchor']==day.isoformat()), key=lambda e:(e['game'],e['title'],e['id']))


class DaySelect(discord.ui.Select):
    def __init__(self, owner, start, end, row, entries):
        self.calendar_owner=owner
        options=[]
        for n in range(start,end+1):
            count=len(exact_on(entries,date(owner.year,owner.month,n)))
            options.append(discord.SelectOption(label=f'{calendar.month_name[owner.month]} {n} — {count} releases',value=str(n)))
        super().__init__(placeholder=f'Choose a day ({start}–{end})',row=row,options=options)
    async def callback(self,interaction):
        self.calendar_owner.select_day(int(self.values[0]))
        await self.calendar_owner.update(interaction)


class WeekSelect(discord.ui.Select):
    def __init__(self,owner,entries,row):
        self.calendar_owner=owner
        options=[]
        for i,days in enumerate(owner.weeks()):
            count=sum(len(exact_on(entries,date(owner.year,owner.month,d))) for d in days)
            options.append(discord.SelectOption(label=f'{calendar.month_abbr[owner.month]} {days[0]}–{days[-1]} · {count} releases',value=str(i),default=owner.mode!='month' and i==owner.week))
        super().__init__(placeholder='Zoom into a week',row=row,options=options)
    async def callback(self,interaction):
        owner=self.calendar_owner;owner.week=int(self.values[0]);owner.mode='week';owner.page=0
        await owner.update(interaction)


class CalendarView(OwnedView):
    def __init__(self,runtime,guild,user,year,month):
        super().__init__(runtime,guild,user);self.year=year;self.month=month
        self.region='ALL';self.language='all'
        self.mode='month';self.day=None;self.week=0;self.page=0;self.pages=1

    def weeks(self):
        return [[d for d in row if d] for row in calendar.Calendar(firstweekday=6).monthdayscalendar(self.year,self.month)]

    def select_day(self,day):
        self.day=day;self.mode='day';self.page=0
        self.week=next(i for i,days in enumerate(self.weeks()) if day in days)

    def shift_week(self,delta):
        new=self.week+delta
        if new<0:
            self.year,self.month=month_shift(self.year,self.month,-1)
            self.week=len(self.weeks())-1
        elif new>=len(self.weeks()):
            self.year,self.month=month_shift(self.year,self.month,1);self.week=0
        else:self.week=new
        self.mode='week';self.page=0

    def button(self,label,row,callback,disabled=False,primary=False):
        button=discord.ui.Button(label=label,row=row,disabled=disabled,
            style=discord.ButtonStyle.primary if primary else discord.ButtonStyle.secondary)
        button.callback=callback;self.add_item(button)

    async def navigate(self,interaction,action):
        if action=='jump':await interaction.response.send_modal(MonthJump(self));return
        if action=='settings':
            await interaction.response.defer(ephemeral=True)
            view=SettingsView(self.runtime,self.guild_id,self.user_id);await view.load()
            await interaction.followup.send(embed=view.embed(),view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none());return
        if action in ('prev','next','today'):
            if action=='today':
                cfg=await self.runtime.store.settings(self.guild_id);now=datetime.now(ZoneInfo(cfg['timezone']))
                self.year,self.month=now.year,now.month
            else:self.year,self.month=month_shift(self.year,self.month,-1 if action=='prev' else 1)
            self.week=0;self.mode='month'
        elif action in ('weekprev','weeknext'):self.shift_week(-1 if action=='weekprev' else 1)
        else:self.mode=action
        self.page=0;await self.update(interaction)

    def action(self,label,action,row,disabled=False,primary=False):
        async def callback(i):await self.navigate(i,action)
        self.button(label,row,callback,disabled,primary)

    async def render(self):
        self.clear_items()
        entries=await self.runtime.entries(self.guild_id)
        entries=filter_editions(entries,self.region,self.language)
        prefs=await self.runtime.store.preference(self.guild_id,self.user_id)
        entries=[e for e in entries if prefs['games'] is None or e['game'] in prefs['games']]
        if self.mode=='day' and self.day is not None:
            self.week=next(i for i,days in enumerate(self.weeks()) if self.day in days)
        self.week=max(0,min(self.week,len(self.weeks())-1))
        if self.mode=='month':
            self.add_item(WeekSelect(self,entries,0))
            self.add_item(DaySelect(self,1,16,1,entries))
            self.add_item(DaySelect(self,17,calendar.monthrange(self.year,self.month)[1],2,entries))
        elif self.mode in ('week','day'):
            for index,n in enumerate(self.weeks()[self.week]):
                day=date(self.year,self.month,n);count=len(exact_on(entries,day))
                async def choose(i,n=n):self.select_day(n);await self.update(i)
                self.button(f'{day:%a} {n} · {count}',0 if index<4 else 1,choose,
                            primary=bool(count) or (self.mode=='day' and self.day==n))
            self.add_item(WeekSelect(self,entries,2))
        else:
            self.add_item(WeekSelect(self,entries,0))
            self.add_item(DaySelect(self,1,16,1,entries))
            self.add_item(DaySelect(self,17,calendar.monthrange(self.year,self.month)[1],2,entries))
        for label,action in [('◀ Month','prev'),('This month','today'),('Month ▶','next'),('Jump to month','jump'),('Month grid','month')]:
            self.action(label,action,3,disabled=(action=='prev' and (self.year,self.month)==(2000,1)) or (action=='next' and (self.year,self.month)==(2099,12)))
        if self.mode=='week':
            self.action('◀ Week','weekprev',4,disabled=(self.year,self.month,self.week)==(2000,1,0))
            self.action('Week ▶','weeknext',4,disabled=(self.year,self.month)==(2099,12) and self.week==len(self.weeks())-1)
            for label,action in [('Period-end TBA','tba'),('Undated','undated'),('My games / pings','settings')]:self.action(label,action,4)
            days=self.weeks()[self.week]
            header=discord.Embed(title=f'🪷 {calendar.month_name[self.month]} {days[0]}–{days[-1]}, {self.year}',
                description='**Tap a day button below to open its releases.** The number on each button is your filtered release count.\n'
                'These are catalog dates; source confidence appears on the product card. Period-end TBA is separate.',colour=0x667ACD)
            header.set_footer(text=f'Calendar {UI_VERSION} • Personal week view • Controls expire after 10 minutes')
            embeds=[header]
            for n in days:
                d=date(self.year,self.month,n);items=exact_on(entries,d)
                lines=[f"• **{safe(e['game'],40)}** — {safe(e['title'],160)}" for e in items[:2]]
                if len(items)>2:lines.append(f'+ {len(items)-2} more — tap this day to browse all.')
                embeds.append(discord.Embed(title=f'{d:%A, %B} {n} · {len(items)} release'+('s' if len(items)!=1 else ''),
                    description='\n'.join(lines) or 'No releases listed for your selected games.',colour=0x34D399 if items else 0x334155))
            return embeds,[]
        if self.mode=='month':
            for label,action in [('Week zoom','week'),('Period-end TBA','tba'),('Undated','undated'),('My games / pings','settings')]:self.action(label,action,4,primary=action=='week')
            picture=await asyncio.to_thread(month_png,self.year,self.month,entries,prefs['games'])
            embed=discord.Embed(title=f'🪷 {calendar.month_name[self.month]} {self.year}',description=
                '**Choose a week for larger text and clickable day buttons.** Or choose a date directly from the day menus.\n'
                'Click/tap the image to enlarge it. Dates inside the image are visual; use the controls below.\n'
                '**Period-end TBA** holds month, quarter, season and year-only listings.',colour=0x667ACD)
            embed.set_image(url='attachment://my-calendar.png')
            embed.set_footer(text=f'Calendar {UI_VERSION} • {self.region} / {self.language} • Controls expire after 10 minutes')
            return [embed],[discord.File(picture,filename='my-calendar.png')]
        prefix=f'{self.year:04d}-{self.month:02d}'
        if self.mode=='day':
            wanted=date(self.year,self.month,self.day);items=exact_on(entries,wanted)
            heading=f'{wanted:%A, %B} {self.day}, {self.year}'
        elif self.mode=='tba':
            items=[e for e in entries if e.get('period') and e['period']['tba'] and e['period']['anchor'].startswith(prefix)]
            heading=f'Period-end TBA • {calendar.month_name[self.month]} {self.year}'
        else:items=[e for e in entries if not e.get('period')];heading='Upcoming • Date TBA'
        items.sort(key=lambda e:((e.get('period') or {}).get('anchor',''),e['game'],e['title'],e['id']))
        # One large product card at a time: images and product text stay readable.
        self.pages=max(1,len(items));self.page=max(0,min(self.page,self.pages-1))
        header=discord.Embed(title=heading,description=f'{len(items)} products • Product {self.page+1}/{self.pages}\n'+('No matching releases.' if not items else 'Use Previous / Next product to browse this date or section.'),colour=0x667ACD)
        for label,delta in [('◀ Product',-1),('Product ▶',1)]:
            async def callback(i,delta=delta):self.page=max(0,min(self.pages-1,self.page+delta));await self.update(i)
            self.button(label,4,callback,disabled=(self.page==0 if delta<0 else self.page>=self.pages-1))
        self.action('Back to week','week',4)
        self.action('Period-end TBA','tba',4)
        self.action('My games / pings','settings',4)
        if not items:return [header],[]
        entry=items[self.page];card=product_embed(entry)
        card.set_thumbnail(url=None);card.set_image(url=entry.get('image_url') or 'attachment://image-pending.png')
        file=await asyncio.to_thread(product_image_file,entry)
        files=[file] if file else []
        return [header,card],files

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


async def open_calendar(runtime,interaction,month=None,*,mode='month',offset=0,region='ALL',language='ALL'):
    if not interaction.guild_id:
        await interaction.response.send_message('Open the calendar in your server.',ephemeral=True);return
    cfg=await runtime.store.settings(interaction.guild_id)
    if not can_access(interaction.user,cfg):
        await interaction.response.send_message(f"Calendar access requires {cfg['minimum_tier']} or above.",ephemeral=True);return
    try:
        now=datetime.now(ZoneInfo(cfg['timezone']))
        start=date.fromisoformat(month+'-01') if month else now.date()
        if not 2000<=start.year<=2099:raise ValueError()
        if offset:
            y,m=month_shift(start.year,start.month,offset);start=date(y,m,1)
    except ValueError:
        await interaction.response.send_message('Use a month such as 2028-12 (years 2000–2099).',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    view=CalendarView(runtime,interaction.guild_id,interaction.user.id,start.year,start.month)
    view.region=region.strip().upper();view.language=language.strip().casefold()
    view.mode=mode
    if mode=='week':
        view.week=next(i for i,days in enumerate(view.weeks()) if start.day in days)
    embeds,files=await view.render()
    await interaction.followup.send(embeds=embeds,files=files,view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
