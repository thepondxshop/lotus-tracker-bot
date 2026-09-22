"""Private admin Radar commands with owner-bound, expiring navigation."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit
import discord
from discord import app_commands
from .commands import safe
from .extraction import GAMES
from .radar import ReleaseRadar, VERSION
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
    out.set_footer(text=f'Release Radar {VERSION} • Admin preview • Release/preorder publishing OFF')
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


def list_embed(data):
    out = card('Release Radar • ' + safe(data.get('game') or 'All games', 80),
               'Upcoming dated releases first, then undated leads and past dated records. Archived releases are excluded.\n'
               'Publisher evidence does not establish retailer availability.')
    for item in data['items']:
        row = item['release']
        body = (f"{safe(row['game'], 60)} • {safe(row['product_format'], 20)} • {safe(row['region'], 40)} / {safe(row['language'], 40)}\n"
                f"{safe(evidence_label(item), 200)}\n"
                f"Catalog: {row['status']} • Date: {row['release_date'] or 'Unknown'}\n"
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
               f"{safe(evidence_label(data), 220)}\nCatalog: {row['status']} • Date: {row['release_date'] or 'Unknown'}")
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
        out.add_field(name='Retailer matches', value='No saved matched listings. Matching runs in batches; this does not prove no retailer carries it.', inline=False)
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
