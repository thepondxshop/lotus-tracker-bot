"""Administrator-only source configuration and private ingestion diagnostics."""
from __future__ import annotations
import asyncio
import json
import discord
from discord import app_commands
from .extraction import GAMES
from .ingestion_store import IngestionStore
from .ingestion_runner import IngestionRunner

class ReleaseItemsView(discord.ui.View):
    """Private item navigation, scoped to the opening administrator and guild."""

    def __init__(self, group, interaction, data, review=False):
        super().__init__(timeout=600)
        self.group = group
        self.owner_id = interaction.user.id
        self.guild_id = interaction.guild_id
        self.review = review
        self.page = data['page']
        self.has_more = data['has_more']
        self.message = None
        self.lock = asyncio.Lock()
        self.update_buttons()

    def update_buttons(self):
        self.previous.disabled = self.page <= 1
        self.next_page.disabled = not self.has_more or self.page >= 10000
        self.page_label.label = f'Page {self.page}'

    async def interaction_check(self, interaction):
        if (interaction.user.id != self.owner_id
                or interaction.guild_id != self.guild_id):
            await interaction.response.send_message(
                'Open your own list with /release watch items or /release watch review.',
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
            return False
        return await self.group.interaction_check(interaction)

    async def move(self, interaction, step):
        # Also guard direct callback calls; permissions may change after opening.
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        if self.lock.locked():
            await interaction.followup.send(
                'A page is loading. Please wait a moment.', ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        async with self.lock:
            if self.is_finished():
                await interaction.followup.send(
                    'These buttons expired. Run the list command again.', ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            target = self.page + step
            if target < 1 or target > 10000 or (step > 0 and not self.has_more):
                return
            old_page, old_more = self.page, self.has_more
            try:
                data = await self.group.store.items(
                    self.guild_id, target, self.review,
                )
                title = ('Release ingestion exceptions' if self.review
                         else 'Automatically discovered items')
                result = self.group.items_embed(data, title)
                self.page, self.has_more = data['page'], data['has_more']
                self.update_buttons()
                await interaction.edit_original_response(
                    embed=result, view=self,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception as error:
                self.page, self.has_more = old_page, old_more
                self.update_buttons()
                await self.group.on_error(interaction, error)

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, -1)

    @discord.ui.button(label='Page 1', style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label='Next', style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 1)

    async def on_timeout(self):
        async with self.lock:
            self.stop()
            for button in self.children:
                button.disabled = True
            self.page_label.label = f'Page {self.page} · Expired'
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass

    async def on_error(self, interaction, error, item):
        await self.group.on_error(interaction, error)

class ReleaseWatchCommands(app_commands.Group):
    def __init__(self,parent):
        super().__init__(name='watch',description='Automatic public-source discovery, evidence and retailer matching')
        self.root=parent;self.store=IngestionStore(parent.catalog);self.runner=IngestionRunner(self.store)
    async def interaction_check(self,interaction): return await self.root.interaction_check(interaction)
    async def on_error(self,interaction,error): await self.root.on_error(interaction,error)
    @staticmethod
    def watch_embed(row):
        from .commands import embed,safe
        settings=json.loads(row['scope_json']);last=json.loads(row['last_json'])
        return embed(f"Source watch #{row['id']} • {safe(row['label'],150)}",
            f"{safe(row['url'],1500)}\n\nEnabled: **{row['enabled']}** • every **{row['interval_minutes']} minutes**\n"
            f"Kind: {row['kind']} • Game: {safe(settings['game'] or 'All supported games',80)}\n"
            f"Source scope: {safe(settings['region'],40)} / {safe(settings['language'],40)}\n"
            f"Automatic calendar confirmation: **{row['auto_confirm']}**\n"
            f"Last scan: {last.get('at','Not scanned')} • {last.get('error') or 'No error recorded'}\n"
            f"Next scan: {row['next_due']}\n\n"
            'New releases and evidence are saved automatically. A product URL tracks that item; a supported category/feed discovers additional items. Exceptions: /release watch review.')
    @app_commands.command(name='add',description='Configure a public source once; supported releases are then imported automatically')
    @app_commands.choices(kind=[app_commands.Choice(name=x.title(),value=x) for x in ('DISTRIBUTOR','PUBLISHER','RETAILER')],game=[app_commands.Choice(name=g,value=g) for g,_ in GAMES])
    @app_commands.describe(url='Public HTTPS category, feed, sitemap or product URL',label='Name of this source watch',game='Omit to include all supported games',region='Only set a region that applies to this entire source',language='Only set an edition language that applies to this entire source',auto_confirm='Approve clean dated items for the calendar; requires known source region and language')
    async def add(self,interaction:discord.Interaction,url:str,kind:str,label:str,game:str|None=None,region:str='UNKNOWN',language:str='UNKNOWN',interval_minutes:app_commands.Range[int,15,10080]=60,auto_confirm:bool=False):
        await self.root._run(interaction,lambda:self.store.add_watch(interaction.guild_id,interaction.user.id,url=url,kind=kind,label=label,game=game,region=region,language=language,interval_minutes=interval_minutes,auto_confirm=auto_confirm),self.watch_embed)
    @app_commands.command(name='settings',description='Pause or enable a source and change its interval or approved scope')
    @app_commands.describe(auto_confirm='Source-policy approval for clean dated items; not a per-item human attestation')
    async def settings(self,interaction:discord.Interaction,watch_id:int,enabled:bool|None=None,interval_minutes:app_commands.Range[int,15,10080]|None=None,region:str|None=None,language:str|None=None,auto_confirm:bool|None=None):
        await self.root._run(interaction,lambda:self.store.settings(interaction.guild_id,interaction.user.id,watch_id,enabled=enabled,interval_minutes=interval_minutes,region=region,language=language,auto_confirm=auto_confirm),self.watch_embed)
    @app_commands.command(name='list',description='List configured source watches and their most recent results')
    async def list(self,interaction:discord.Interaction,page:app_commands.Range[int,1,3]=1):
        from .commands import embed,safe
        def render(rows):
            lines=[]
            for w in rows[(page-1)*10:page*10]:
                last=json.loads(w['last_json'])
                lines.append(f"**#{w['id']} {safe(w['label'],70)}** • {'ON' if w['enabled'] else 'OFF'} • {w['interval_minutes']} min\n{last.get('error') or ('Completed' if last else 'Pending')}")
            return embed('Automatic release sources',('\n\n'.join(lines) or 'No watches on this page.')+f'\n\nPage {page}')
        await self.root._run(interaction,lambda:self.store.watches(interaction.guild_id),render)
    @app_commands.command(name='scan',description='Run a bounded source scan now; rate-limit backoff still applies')
    async def scan(self,interaction:discord.Interaction,watch_id:int):
        from .commands import embed
        await self.root._run(interaction,lambda:self.runner.scan(interaction.guild_id,watch_id),lambda r:embed(f"Source scan #{r['watch_id']}",'\n'.join(f"{k.replace('_',' ').title()}: {v}" for k,v in r['stats'].items())+f"\nRemaining discovery pages: {r['remaining_pages']}\nResult: {r['error'] or 'Completed'}\n\nRecords: /release list\nExtracted items: /release watch items\nExceptions: /release watch review"))
    @app_commands.command(name='status',description='Check the installed ingestion version and background worker')
    async def status(self,interaction:discord.Interaction):
        from .commands import embed,safe
        await self.root._run(interaction,lambda:self.runner.status(interaction.guild_id),lambda r:embed('Release ingestion status','\n'.join(f"{k.replace('_',' ').title()}: {safe(v,100)}" for k,v in r.items())+'\n\nExtraction: deterministic public product data\nRetailer matching: existing monitor database, in batches\nAI model calls: OFF\nRelease/preorder alert publishing: OFF'))
    @staticmethod
    def items_embed(data,title):
        from .commands import embed,safe
        lines=[]
        for row in data['items']:
            payload=json.loads(row['payload_json']);issues=json.loads(row['issues_json'])
            lines.append(f"**Item #{row['id']} • {safe(payload.get('title',row['state']),120)}**\nRelease: {row['release_id'] or 'Unmatched'} • {row['state']}\n{safe(', '.join(issues) or 'No extraction issues',140)}")
        return embed(title,('\n\n'.join(lines) or 'No matching items.')+f"\n\nPage {data['page']} • {'More available' if data['has_more'] else 'End'}\nUse Previous / Next below. Buttons expire after 10 minutes of inactivity or a bot restart.\nDetails: /release watch item")

    async def _show_items(self, interaction, page, review=False):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        view = None
        try:
            data = await self.store.items(interaction.guild_id, page, review)
            title = 'Release ingestion exceptions' if review else 'Automatically discovered items'
            result = self.items_embed(data, title)
            view = ReleaseItemsView(self, interaction, data, review)
            view.message = await interaction.followup.send(
                embed=result, view=view, ephemeral=True, wait=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as error:
            if view is not None:
                view.stop()
            await self.on_error(interaction, error)

    @app_commands.command(name='items',description='List automatically discovered items and their release IDs')
    async def items(self,interaction:discord.Interaction,page:app_commands.Range[int,1,10000]=1):
        await self._show_items(interaction, page)
    @app_commands.command(name='review',description='Show items that need extraction or identity review')
    async def review(self,interaction:discord.Interaction,page:app_commands.Range[int,1,10000]=1):
        await self._show_items(interaction, page, True)
    @app_commands.command(name='item',description='Inspect extracted dates, packaging, source evidence and the linked release')
    async def item(self,interaction:discord.Interaction,item_id:int):
        from .commands import embed,safe
        def render(row):
            data=json.loads(row['payload_json'])
            lines=[f"Watch #{row['watch_id']} • {row['state']} • Release {row['release_id'] or 'Unmatched'}",safe(row['url'],900)]
            for key in ('title','game','sku','set_code','product_format','region','language','release_date','order_due_date','cards_per_pack','packs_per_box','boxes_per_case','all_foil','reported_rarity_total','computed_rarity_total','extractor'):
                if data.get(key) is not None: lines.append(f"{key.replace('_',' ').title()}: {safe(data[key],180)}")
            lines.append('Issues: '+safe(row['issues_json'],400))
            if row['last_error']: lines.append('Last fetch: '+safe(row['last_error'],100)+' • previous evidence retained')
            lines.append(f"Attached evidence source: {row['source_id'] or 'Not yet matched'}. Order due dates are distributor deadlines, not customer preorder openings.")
            return embed(f"Ingested item #{row['id']}",'\n'.join(lines)[:3900])
        await self.root._run(interaction,lambda:self.store.item(interaction.guild_id,item_id),render)
    @app_commands.command(name='link',description='Resolve an ambiguous source item after checking its edition and format')
    async def link(self,interaction:discord.Interaction,item_id:int,release_id:int):
        from .commands import embed
        await self.root._run(interaction,lambda:self.store.link(interaction.guild_id,interaction.user.id,item_id,release_id),lambda r:embed('Identity link recorded',f"Item #{r['item_id']} → release #{r['release_id']}. Watch #{r['watch_id']} will recheck the source. This does not confirm a date or open a preorder."))
    @app_commands.command(name='retailers',description='Show matches to products already found by the retailer monitors')
    async def retailers(self,interaction:discord.Interaction,page:app_commands.Range[int,1,10000]=1):
        from .commands import embed,safe
        def render(data):
            lines=[]
            for row in data['items']:
                d=json.loads(row['details_json'])
                lines.append(f"**{safe(d['store'],60)} • {row['state']}**\n{safe(d['title'],140)}\nRelease: {row['release_id'] or 'Unmatched'} • {d['reason'] or 'Identity matched'}")
            return embed('Retailer product matches',('\n\n'.join(lines) or 'No matches yet. The worker checks existing monitor results in batches; unknown editions need review.')+f"\n\nPage {data['page']} • {'More available' if data['has_more'] else 'End'}\nA catalog match does not establish stock or a customer preorder opening.")
        await self.root._run(interaction,lambda:self.store.retailers(interaction.guild_id,page),render)
