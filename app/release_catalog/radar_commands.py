"""Private admin Radar commands with owner-bound, expiring navigation."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit
import discord
from discord import app_commands
from .commands import safe
from .extraction import GAMES
from .radar import ReleaseRadar
from .radar_diagnostics import RadarDiagnostics
VERSION = "1.6.0"
from .service import CatalogError

LOG = logging.getLogger(__name__)


def link(url):
    # Never turn unexpected schemes, markdown, or overlong values into links.
    try:
        parsed = urlsplit(url or '')
        if parsed.scheme == 'https' and parsed.hostname and len(url) <= 300 and not any(c in url for c in '<>\n\r '):
            return '<' + url + '>'
    except ValueError:
        pass
    return 'Full source links: /release sources or /release official check'


def card(title, description=''):
    out = discord.Embed(title=title, description=description, colour=0x667ACD)
    out.set_footer(text=f'Release Radar {VERSION} • Admin tools • Publishing: /release radar publishing')
    return out


def evidence_label(data):
    check = data['check']
    labels = []
    if 'DISTRIBUTOR' in data['kinds']:
        labels.append('Distributor-listed')
    if check.get('evidence'):
        labels.append('Official evidence found')
        if all(e.get('stale') for e in check['evidence']):
            labels.append('Official evidence needs refresh')
    else:
        labels.append('Awaiting official match')
    if check.get('date_review'):
        labels.append('DATE CONFLICT / REVIEW')
    if any(e.get('state') == 'EDITION_REVIEW' for e in check.get('evidence', [])):
        labels.append('Region/language review')
    return ' • '.join(labels)


def windows(check, limit=2):
    found = []
    for evidence in check.get('evidence', []):
        for window in evidence.get('windows', []):
            value = f"{window.get('label', 'Unspecified')} ({window.get('precision', 'UNKNOWN')}; {evidence.get('match_scope', 'UNKNOWN')})"
            if evidence.get('stale'):
                value += ' • stale'
            if value not in found:
                found.append(value)
    return '\n'.join(safe(x, 170) for x in found[:limit]) + (f'\n+{len(found)-limit} more; open details' if len(found) > limit else '') or 'No official release window saved'


def catalog_label(row):
    return 'Confirmed catalog record' if row['status']=='CONFIRMED' else ('Archived catalog record' if row['status']=='ARCHIVED' else 'Unconfirmed catalog record')


def diagnostic_embed(data):
    row=data['release']
    out=card(f"Retailer diagnosis • #{row['id']}", safe(row['title'],180)+
             f"\nInspected {data['examined']} newest saved offers for this game. "
             + ('Search limited to 1,000 offers; older offers were not examined.' if data['limited'] else 'All currently saved offers for this game were examined.')+
             '\nCandidates share a code, SKU, or narrowly comparable title. Pack annotations remain review-only; other naming variations may be missed.')
    for item in data['items']:
        value=(f"{safe(item['title'],150)}\nCurrent evaluation: {safe(item['current'],150)}\n"
               f"Title comparison: {safe(item.get('title_relation') or 'Other identity evidence',60)}\n"
               f"Catalog region/language incomplete: {'Yes' if item.get('catalog_scope_missing') else 'No'}\n"
               f"Saved decision: {safe(item['saved_state'],40)} • {safe(item['saved_reason'] or 'No saved reason',90)}\n"
               f"Last match check: {safe(item['checked_at'] or 'Not recorded',40)}\n"
               + (f"Other release: #{item['other_release']}\n" if item['other_release'] else '')
               + link(item['url']))
        out.add_field(name=f"{safe(item['store'],100)} • Product #{item['product_id']}",value=value,inline=False)
    if not data['items']:
        out.add_field(name='No identity candidates found in inspected offers',value='This is not proof the retailer has no listing. It may be undiscovered, outside this search, or named differently.',inline=False)
    out.add_field(name=f"Page {data['page']} of {data['pages']} • {data['total']} candidates",value=
                  'Read-only evaluation; no matches were saved. NO_SAVED_DECISION can mean never checked or previously checked without a match. '
                  'MATCH_ELIGIBLE_NOW is not a stock or delivery confirmation. Buttons expire after 10 minutes of inactivity.',inline=False)
    return out


def formats_embed(data):
    out=card('Product format cleanup • '+('Applied' if data['apply'] else 'Preview'),
             'Title-based classification of UNKNOWN formats only. Region, language, dates, and confirmation status are preserved. '
             'Known formats are not rewritten. No records are merged.')
    counts={state:sum(x['state']==state for x in data['items']) for state in ('PROPOSED','UPDATED','IDENTITY_CONFLICT')}
    out.add_field(name='Result',value=f"Unknown records before: {data['unknown_total']}\nProposed: {counts['PROPOSED']} • Updated: {counts['UPDATED']} • Identity conflicts skipped: {counts['IDENTITY_CONFLICT']}",inline=False)
    lines=[f"#{x['id']} • {safe(x['title'],100)} → {x['format']} ({x['state']})" for x in data['items'][:8]]
    out.add_field(name='First results',value='\n'.join(lines)[:1024] or 'No supported title-based format corrections.',inline=False)
    out.add_field(name='Next step',value=('Up to 50 supported records per run. '+('Run again for remaining records. ' if data['limited'] else '')+
                  ('Existing retailer matching will re-evaluate in batches. Saved extraction issues may remain until the source is scanned again.' if data['apply'] else 'Use /release radar formats apply:True with the same game filter to apply up to 50 corrections. Each correction is recorded in /release history.')),inline=False)
    return out


def unknowns_embed(data):
    out=card('Unknown product formats • '+safe(data.get('game') or 'All games',70),
             'Read-only inspection of active catalog records. Titles and reported details are evidence for review, not verified packaging.')
    for item in data['items']:
        row=item['release']
        value=(f"{safe(row['game'],60)} • {safe(row['region'],40)} / {safe(row['language'],40)}\n"
               f"Set code: {safe(row['set_code'] or 'Unknown',40)} • Title parser: {item['suggested']}\n"
               f"Reported details (excerpt): {safe(row['reported_details'] or 'None',500)}\n"
               f"Full record: /release show release_id:{row['id']}\nSources: /release sources release_id:{row['id']}")
        out.add_field(name=f"#{row['id']} • {safe(row['title'],180)}",value=value,inline=False)
    if not data['items']:
        out.description+='\n\nNo unknown formats in this filter.'
    out.add_field(name=f"Page {data['page']} of {data['pages']} • {data['total']} unknown formats",
                  value='Previous / Next below. Buttons expire after 10 minutes of inactivity or a bot restart.',inline=False)
    return out


def offers_embed(data):
    target=data['release']
    out=card(f"Saved retailer offers • Release #{target['id']}",
             f"Compare with: **{safe(target['title'],180)}**\n"
             f"Catalog: {safe(target['product_format'],20)} • {safe(target['region'],40)} / {safe(target['language'],40)} • Code: {safe(target['set_code'] or 'Unknown',40)}\n"
             'All saved offers for this game, including disabled stores and non-candidates. Sharing a game does not establish a product match.')
    for item in data['items']:
        p,o,t=item['product'],item['offer'],item['store']; saved=item['saved']
        reason='No saved decision'
        if saved:
            import json
            reason=saved['state']+' • '+str(json.loads(saved['details_json']).get('reason') or 'No saved reason')
            if saved['release_id']:
                reason+=f" • Release #{saved['release_id']}"
        value=(f"**{safe(p['name'],240)}**\n"
               f"SKU: {safe(o['sku'] or 'Unknown',65)} • Type: {safe(p['product_type'] or 'Unknown',65)}\n"
               f"Parsed title/type formats: {item['title_format']} / {item['type_format']}\n"
               f"Product region/language: {safe(p['region'] or 'Unknown',40)} / {safe(p['language'] or 'Unknown',40)}\n"
               f"Store region: {safe(t['region'] or 'Unknown',40)} • {'Enabled' if t['active'] else 'Disabled'}\n"
               f"Identity candidate: {'Yes' if item['identity_candidate'] else 'No'} • {safe(reason,130)}\n"
               f"Last seen (UTC): {safe(o['last_seen_at'] or 'Unknown',40)}\n{link(o['url'])}")
        out.add_field(name=f"{safe(t['name'],90)} • Product #{o['id']}",value=value[:1024],inline=False)
    if not data['items']:
        out.description+='\n\nNo saved offers for this game.'
    out.add_field(name=f"Page {data['page']} of {data['pages']} • {data['total']} saved offers",
                  value='Read-only; no new scans, stock checks or matching decisions. Previous / Next shows every saved offer for this game. Buttons expire after 10 minutes of inactivity.',inline=False)
    return out


def list_embed(data):
    out = card('Release Radar • ' + safe(data.get('game') or 'All games', 80),
               'Upcoming dated releases first, then undated leads and past dated records. Archived releases are excluded.\n'
               'Publisher evidence does not establish retailer availability.')
    for item in data['items']:
        row = item['release']
        body = (f"{safe(row['game'], 60)} • {safe(row['product_format'], 20)} • {safe(row['region'], 40)} / {safe(row['language'], 40)}\n"
                f"{safe(evidence_label(item), 200)}\n"
                f"{catalog_label(row)} • Exact date: {row['release_date'] or 'Not confirmed'}\n"
                f"{windows(item['check'])}\n"
                f"Saved retailer matches: {item['retailer_count']}\n"
                f"Details: /release radar show release_id:{row['id']}")
        out.add_field(name=f"#{row['id']} • {safe(row['title'], 180)}", value=body, inline=False)
    if not data['items']:
        out.description += '\n\nNo matching releases.'
    out.add_field(name=f"Page {data['page']} of {data['pages']} • {data['total']} releases",
                  value='Previous / Next below. Buttons expire after 10 minutes of inactivity or a bot restart.', inline=False)
    return out


def detail_embed(data):
    row = data['release']
    check = data['check']
    out = card(f"Release Radar • #{row['id']}",
               f"**{safe(row['title'], 180)}**\n{safe(row['game'], 70)} • {safe(row['product_format'], 20)} • "
               f"{safe(row['region'], 40)} / {safe(row['language'], 40)}\n"
               f"{safe(evidence_label(data), 220)}\n{catalog_label(row)} • Exact product date: {row['release_date'] or 'Not confirmed'}")
    evidence = check.get('evidence', [])
    for e in evidence[:3]:
        dates = '; '.join(f"{w.get('label')} ({w.get('precision')})" for w in e.get('windows', [])) or 'No release date stated'
        body = (f"{safe(dates, 220)}\nScope: {safe(e.get('match_scope', 'UNKNOWN'), 40)}\n"
                f"{link(e.get('url'))}\nFetched: {safe(e.get('fetched_at') or 'Unknown', 40)}\n"
                f"{safe(', '.join(e.get('issues', [])) or 'No reported conflicts', 140)}")
        out.add_field(name='Official evidence' + (' • STALE / refresh needed' if e.get('stale') else ''), value=body[:1024], inline=False)
    if not evidence:
        out.add_field(name='Awaiting official evidence', value='No supported official match is saved yet. This does not disprove the listing.', inline=False)
    if len(evidence) > 3:
        out.add_field(name='More official evidence', value=f"{len(evidence)-3} additional records: /release official check release_id:{row['id']}", inline=False)
    distributor_dates = check.get('distributor_dates', [])
    out.add_field(name='Date interpretation', value=(
        'Month/quarter and set/game-launch windows are broader than an exact SKU date.\n'
        + ('Saved distributor dates: ' + safe(', '.join(distributor_dates), 180) + '\n' if distributor_dates else '')
        + 'Last official evaluation: ' + safe(data.get('checked_at') or 'Pending', 40)
        + f"\nFull evidence: /release official check release_id:{row['id']}"), inline=False)
    for entry in data['retailers']:
        store, product, match = entry['store'], entry['product'], entry['link']
        availability = 'In stock' if product['in_stock'] else 'Not marked in stock'
        body = (f"Last observed: {availability} • {safe(product.get('status') or 'Status unknown', 80)}\n"
                f"Price: {safe(product['price'] if product['price'] is not None else 'Unknown', 30)} {safe(product['currency'], 10)}\n"
                f"Seen (UTC): {safe(product.get('last_seen_at') or 'Unknown', 40)}\n"
                f"Store: {'Enabled' if store['active'] else 'Disabled'} • {safe(store['health_status'], 35)}\n"
                f"Match checked: {safe(match['checked_at'], 40)}\n{link(product['url'])}")
        out.add_field(name=safe(store['name'], 100) + ' • Saved retailer match', value=body[:1024], inline=False)
    if not data['retailers']:
        out.add_field(name='Retailer matches', value=f'No saved matched listings. Diagnose: /release radar diagnose release_id:{row["id"]}. This does not prove no retailer carries it.', inline=False)
    out.add_field(name=f"Retailer page {data['page']} of {data['pages']} • {data['total']} matches", value=
                  'Saved observations, not a live stock check. Disabled/degraded stores may have old data.\n'
                  'Previous / Next changes retailer pages. Buttons expire after 10 minutes of inactivity or a bot restart.', inline=False)
    return out


class RadarView(discord.ui.View):
    def __init__(self, group, interaction, loader, renderer, data):
        super().__init__(timeout=600)
        self.group, self.loader, self.renderer = group, loader, renderer
        self.owner = interaction.user.id
        self.guild = interaction.guild_id
        self.lock = asyncio.Lock()
        self.message = None
        self.set_page(data)

    def set_page(self, data):
        self.page, self.pages = data['page'], data['pages']
        self.previous.disabled = self.page <= 1
        self.next_page.disabled = not data['has_more']
        self.page_label.label = f'Page {self.page}/{self.pages}'

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner or interaction.guild_id != self.guild:
            await interaction.response.send_message('Open your own Radar with /release radar list.', ephemeral=True)
            return False
        return await self.group.interaction_check(interaction)

    async def move(self, interaction, step):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self.lock:
            if self.is_finished():
                await interaction.followup.send('These buttons expired. Reopen /release radar list or show.', ephemeral=True)
                return
            target = min(max(self.page + step, 1), self.pages)
            try:
                data = await self.loader(target)
                result = self.renderer(data)
                old = {'page': self.page, 'pages': self.pages, 'has_more': self.page < self.pages}
                self.set_page(data)
                try:
                    await interaction.edit_original_response(embed=result, view=self, allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    self.set_page(old)
                    raise
            except Exception as error:
                await self.group.failure(interaction, error)

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, -1)

    @discord.ui.button(label='Page', style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label='Next', style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 1)

    async def on_timeout(self):
        async with self.lock:
            self.stop()
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass

    async def on_error(self, interaction, error, item):
        await self.group.failure(interaction, error)


class RadarCommands(app_commands.Group):
    def __init__(self, root):
        super().__init__(name='radar', description='Release Radar: distributor leads, official evidence and retailer matches')
        self.root = root
        self.radar = ReleaseRadar(root.watch_group.runner.official)
        self.diagnostics = RadarDiagnostics(root.watch_group.store)

    async def interaction_check(self, interaction):
        return await self.root.interaction_check(interaction)

    async def failure(self, interaction, error):
        message = str(error) if isinstance(error, CatalogError) else 'Radar could not load. Try again; check Railway for LOTUS RADAR ERROR.'
        if not isinstance(error, CatalogError):
            LOG.error('LOTUS RADAR ERROR | Type=%s', type(error).__name__)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def on_error(self, interaction, error):
        await self.failure(interaction, error)

    async def open(self, interaction, loader, renderer, page):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await loader(page)
            view = RadarView(self, interaction, loader, renderer, data)
            view.message = await interaction.followup.send(embed=renderer(data), view=view, ephemeral=True,
                                                          wait=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            await self.failure(interaction, error)

    @app_commands.command(name='list', description='Browse active releases, official windows and saved retailer match counts')
    @app_commands.choices(game=[app_commands.Choice(name=g, value=g) for g, _ in GAMES])
    async def list_command(self, interaction: discord.Interaction, game: str | None = None,
                           page: app_commands.Range[int, 1, 10000] = 1):
        await self.open(interaction, lambda p: self.radar.page(interaction.guild_id, game, p), list_embed, page)

    @app_commands.command(name='show', description='Inspect release evidence, date conflicts and last observed retailer availability')
    async def show(self, interaction: discord.Interaction, release_id: app_commands.Range[int, 1],
                   page: app_commands.Range[int, 1, 10000] = 1):
        await self.open(interaction, lambda p: self.radar.detail(interaction.guild_id, release_id, p), detail_embed, page)


    @app_commands.command(name='diagnose', description='Explain saved retailer matching decisions for a release without changing them')
    async def diagnose(self, interaction: discord.Interaction, release_id: app_commands.Range[int, 1],
                       page: app_commands.Range[int, 1, 10000] = 1):
        await self.open(interaction, lambda p: self.diagnostics.diagnose(interaction.guild_id, release_id, p), diagnostic_embed, page)

    @app_commands.command(name='formats', description='Preview or apply up to 50 title-based UNKNOWN product-format corrections')
    @app_commands.choices(game=[app_commands.Choice(name=g,value=g) for g,_ in GAMES])
    async def formats(self, interaction: discord.Interaction, game: str | None = None, apply: bool = False):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            data=await self.diagnostics.formats(interaction.guild_id,interaction.user.id,game,apply)
            await interaction.followup.send(embed=formats_embed(data),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            await self.failure(interaction,error)


    @app_commands.command(name='unknowns', description='Inspect remaining UNKNOWN format titles and reported details')
    @app_commands.choices(game=[app_commands.Choice(name=g,value=g) for g,_ in GAMES])
    async def unknowns(self, interaction: discord.Interaction, game: str | None = None,
                       page: app_commands.Range[int, 1, 10000] = 1):
        await self.open(interaction, lambda p: self.diagnostics.unknowns(interaction.guild_id,game,p), unknowns_embed, page)

    @app_commands.command(name='offers', description='Inspect all saved retailer offers for a release game, including non-candidates')
    async def offers(self, interaction: discord.Interaction, release_id: app_commands.Range[int, 1],
                     page: app_commands.Range[int, 1, 10000] = 1):
        await self.open(interaction, lambda p: self.diagnostics.offers(interaction.guild_id,release_id,p), offers_embed, page)


    @app_commands.command(name='enrich', description='Record source-reviewed packaging or edition facts without confirming a date')
    async def enrich_command(self, interaction: discord.Interaction, release_id: app_commands.Range[int,1],
                             source_id: app_commands.Range[int,1], reviewed: bool, note: str,
                             cards_per_pack: app_commands.Range[int,1,10000] | None = None,
                             packs_per_box: app_commands.Range[int,1,10000] | None = None,
                             boxes_per_case: app_commands.Range[int,1,10000] | None = None,
                             region: str | None = None, language: str | None = None):
        if not await self.interaction_check(interaction):return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            from .enrichment import enrich
            row=await enrich(self.root.watch_group.store,interaction.guild_id,interaction.user.id,
                             release_id,source_id,reviewed,note,cards_per_pack=cards_per_pack,
                             packs_per_box=packs_per_box,boxes_per_case=boxes_per_case,region=region,language=language)
            result=card(f"Evidence enrichment saved • #{release_id}",safe(row['title'],180))
            result.add_field(name='Saved packaging',value=f"Cards/pack: {row['reported_cards_per_pack']} • Packs/display: {row['reported_packs_per_box']} • Displays/case: {row['reported_boxes_per_case']}",inline=False)
            result.add_field(name='Edition',value=safe(row['region']+' / '+row['language'],120),inline=False)
            result.add_field(name='Provenance',value=f"Admin attestation to source #{source_id}. History: /release history release_id:{release_id}\nDate/status unchanged; no stock alert sent. Recheck /release radar diagnose.",inline=False)
            await interaction.followup.send(embed=result,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:await self.failure(interaction,error)


    @app_commands.command(name='reviews', description='Browse pending retailer identity decisions from saved observations')
    @app_commands.choices(game=[app_commands.Choice(name=g,value=g) for g,_ in GAMES])
    async def reviews(self, interaction: discord.Interaction, game: str | None = None,
                      page: app_commands.Range[int,1,10000] = 1):
        from .retailer_review import RetailerReview
        await self.open(interaction, lambda p: RetailerReview(self.root.watch_group.store).pending(interaction.guild_id,game,p), reviews_embed, page)

    @app_commands.command(name='recheck', description='Save fresh retailer match decisions for one release; no stock scans or alerts')
    async def recheck(self, interaction: discord.Interaction, release_id: app_commands.Range[int,1]):
        if not await self.interaction_check(interaction): return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            from .retailer_review import RetailerReview
            d = await RetailerReview(self.root.watch_group.store).recheck(interaction.guild_id,interaction.user.id,release_id)
            result = card(f'Retailer recheck saved • #{release_id}',
                f"Saved offers examined: {d['examined']}\nDecisions refreshed: {d['checked']}\n"
                f"Matched: {d['matched']} • Review: {d['review']} • Unmatched: {d['unmatched']}\nDisabled-store candidates skipped: {d['disabled']}\n\n"
                f"Matches are evaluated against the full catalog and may resolve to another release.\n"
                f"Updated reasons: /release radar diagnose release_id:{release_id}\n"
                f"Audit: /release history release_id:{release_id}\nNo live stock scan or alert was sent.")
            await interaction.followup.send(embed=result,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except Exception as error: await self.failure(interaction,error)



    @app_commands.command(name='publishing', description='Configure automatic release leads or inspect publishing health')
    async def publishing(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None,
                         enabled: bool | None = None):
        if not await self.interaction_check(interaction): return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            publisher = self.root.publisher
            current = await publisher.store.settings(interaction.guild_id)
            if channel is not None or enabled is not None:
                cfg = current['configuration']
                if channel is None and cfg:
                    channel = interaction.guild.get_channel(cfg['channel_id'])
                if channel is None:
                    raise CatalogError('Choose the destination channel once, for example /release radar publishing channel:#release-radar enabled:True.')
                if channel.guild.id != interaction.guild_id:
                    raise CatalogError('Choose a channel in this server.')
                perms = channel.permissions_for(interaction.guild.me)
                if not all(getattr(perms, name, False) for name in ('view_channel', 'send_messages', 'embed_links', 'read_message_history')):
                    raise CatalogError('The bot needs View Channel, Send Messages, Embed Links and Read Message History in that channel.')
                await publisher.store.configure(interaction.guild_id, interaction.user.id, channel.id,
                    enabled if enabled is not None else bool(cfg and cfg['enabled']))
                current = await publisher.store.settings(interaction.guild_id)
            cfg = current['configuration']
            text = (f"Automatic publishing: {'ON' if cfg and cfg['enabled'] else 'OFF'}\n"
                    f"Channel: {('<#'+str(cfg['channel_id'])+'>') if cfg else 'Not configured'}\n"
                    f"Worker: {publisher.state}\nLast tick (UTC): {publisher.last_tick or 'Not yet'}\n"
                    f"Last worker error: {publisher.last_error or 'None'}\n"
                    f"Delivery states: {safe(current['deliveries'],350)}\n\n"
                    + ('Recent delivery notes:\n' + '\n'.join(f"Alert #{x['id']} • {x['state']} • {x['error']}" for x in current['errors']) + '\n\n' if current['errors'] else '') +
                    'New leads publish automatically, including uncertain and unmatched source leads. Admin review follows publication.\n'
                    'First setup baselines existing records. To post one existing record: /release radar announce release_id:<ID>.\n'
                    'Pause with enabled:False. Review buttons keep working while paused.\n'
                    'Retailer stock/preorder alerts continue through their existing worker.\n'
                    'UNCERTAIN means a delivery acknowledgement was lost; the worker searches for the original instead of blindly duplicating it.')
            await interaction.followup.send(embed=card('Automatic release publishing',text), ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
        except Exception as error: await self.failure(interaction,error)

    @app_commands.command(name='announce', description='Queue one existing release lead; repeat calls reuse its original alert')
    async def announce(self, interaction: discord.Interaction, release_id: app_commands.Range[int,1]):
        if not await self.interaction_check(interaction): return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            notice = await self.root.publisher.store.queue_existing(interaction.guild_id, release_id)
            await interaction.followup.send(f"Alert #{notice['id']} • {notice['state']}. The automatic publisher handles delivery. Existing messages are reused.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception as error: await self.failure(interaction,error)

    @app_commands.command(name='reviewlog', description='Inspect saved admin decisions for a public release alert')
    async def reviewlog(self, interaction: discord.Interaction, alert_id: app_commands.Range[int,1]):
        if not await self.interaction_check(interaction): return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import json
            rows = await self.root.publisher.store.audit(interaction.guild_id,alert_id)
            lines = []
            for row in rows:
                d = json.loads(row['details_json'])
                lines.append(f"{row['recorded_at']} • Admin {row['actor_id']} • {row['action']}\n"
                    + safe(f"{d.get('field') or 'Review'}: {d.get('value') or 'No replacement'} • {d.get('note') or 'No note'}",260))
            await interaction.followup.send(embed=card(f'Alert #{alert_id} • latest reviews','\n\n'.join(lines) or 'No admin reviews yet.'),
                ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except Exception as error: await self.failure(interaction,error)

    @app_commands.command(name='reconcile', description='Attach a delivered bot message after a lost delivery acknowledgement')
    async def reconcile(self, interaction: discord.Interaction, alert_id: app_commands.Range[int,1], message_id: str):
        if not await self.interaction_check(interaction): return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if not message_id.isdigit(): raise CatalogError('Supply the Discord message ID.')
            publisher = self.root.publisher
            n = await publisher.store.refresh(interaction.guild_id, alert_id)
            channel = await publisher.channel(n)
            msg = await channel.fetch_message(int(message_id))
            marker = f' • Alert #{alert_id} • '
            if msg.author.id != interaction.client.user.id or not any(marker in (e.footer.text or '') for e in msg.embeds):
                raise CatalogError('This is not the original bot message for that alert.')
            await publisher.store.delivery(interaction.guild_id, alert_id, state='SENT', message=msg.id)
            await publisher.sync(await publisher.store.refresh(interaction.guild_id, alert_id))
            await interaction.followup.send('Original message attached. No duplicate alert was sent.',ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
        except Exception as error: await self.failure(interaction,error)

    @app_commands.command(name='preview', description='Privately preview a release or saved preorder listing; no publishing')
    @app_commands.choices(kind=[app_commands.Choice(name='Release update',value='RELEASE'), app_commands.Choice(name='Preorder listing',value='PREORDER')])
    @app_commands.describe(store_product_id='For PREORDER: product ID from /release radar offers')
    async def preview(self, interaction: discord.Interaction, release_id: app_commands.Range[int,1],
                      kind: str = 'RELEASE', store_product_id: app_commands.Range[int,1] | None = None):
        if not await self.interaction_check(interaction): return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            from .alert_preview import build_preview, preview_embeds
            data = await build_preview(self.radar,self.root.watch_group.store,interaction.guild_id,
                                       release_id,kind,store_product_id)
            await interaction.followup.send(embeds=preview_embeds(data),ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())
        except Exception as error: await self.failure(interaction,error)


def review_hint(reason):
    if reason == 'EDITION_REQUIRED_FOR_MATCH':
        return 'Add source-supported region/language with /release radar enrich, then recheck.'
    if 'PACK_COUNT' in reason:
        return 'Review pack counts against distributor/publisher packaging evidence.'
    if 'FORMAT' in reason:
        return 'Compare product packaging and retailer product type; resolve conflicting formats.'
    if 'LANGUAGE' in reason or 'EDITION' in reason:
        return 'Review conflicting edition/language evidence before changing the catalog.'
    if reason == 'READY_TO_SAVE':
        return 'Run /release radar recheck to save the current decision.'
    return 'Use diagnose and sources to review identity and competing catalog records.'


def reviews_embed(data):
    lines = [f"Read-only • {data['examined']} newest saved offers from enabled stores examined.",
             'Coverage limited to 1,000 offers; filter by game to narrow the search.' if data['limited'] else 'All saved offers within this store/game filter examined.',
             'Only identity candidates are shown; undiscovered listings and unrelated titles are outside this view.']
    for item in data['items']:
        candidates = item['candidates']
        refs = '; '.join('#'+str(c['id'])+' missing: '+(', '.join(c['missing']) or 'none of region/language/format') for c in candidates[:3])
        if len(candidates)>3: refs += f"; +{len(candidates)-3} other candidates"
        lines.append(f"**{safe(item['store'],60)} • Product #{item['offer_id']}**\n{safe(item['title'],160)}\n"
                     f"Current: {safe(item['reason'],100)}\n{safe(refs,260)}\n"
                     f"Next: {review_hint(item['reason'])}\n"
                     f"Saved: {safe(item['saved'],40)} • Checked: {item['checked_at'] or 'Never'}\n"
                     f"Inspect: /release radar diagnose release_id:{candidates[0]['id']}")
    if not data['items']: lines.append('No pending identity candidates in the inspected observations. This does not establish complete retailer coverage.')
    lines.append(f"Page {data['page']} of {data['pages']} • {data['total']} pending offers\nAfter enrichment: /release radar recheck release_id:<ID>")
    return card('Retailer match review queue', '\n\n'.join(lines))
