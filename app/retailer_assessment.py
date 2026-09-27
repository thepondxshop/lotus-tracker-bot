"""Bounded public-source diagnostics for the three pending retailers.

Read-only: no Store rows, queue writes, cart actions, or background scans.
Structured offers are reported evidence, not validated stock transitions.
"""
from __future__ import annotations
import asyncio
import json
import re
import socket
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
import discord
from discord import app_commands

VERSION = '1.0.0'
MAX_BYTES = 1500000
STORES = {
    'turol': {'name': 'Turol Games', 'host': 'turolgames.com', 'region': 'ES',
              'root': 'https://www.turolgames.com/es/', 'sample': None},
    'masterpacks': {'name': 'Masterpacks', 'host': 'masterpacks.pt', 'region': 'PT',
                   'root': 'https://masterpacks.pt/en',
                   'sample': 'https://masterpacks.pt/pt/produto/trading-card-games/pokemon-tcg/ingles/booster-box-3/produto-621'},
    'nobleknight': {'name': 'Noble Knight Games', 'host': 'nobleknight.com', 'region': 'US',
                   'root': 'https://www.nobleknight.com/',
                   'sample': 'https://www.nobleknight.com/P/2148426648/Perfect-Order-Booster-Bundle'},
}
_last_attempt = {}
_active = set()


def validate_url(key, value, *, product=False):
    if key not in STORES:
        raise ValueError('Choose one of the three supported assessment stores.')
    try:
        p = urlsplit(str(value))
        allowed = {STORES[key]['host'], 'www.' + STORES[key]['host']}
        if (p.scheme != 'https' or p.hostname not in allowed or p.username or p.password
                or p.port not in (None, 443) or p.query or p.fragment or re.search(r'[\\\s]', str(value))):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('Use a public HTTPS URL on the selected retailer, without query parameters.') from None
    if product:
        if key == 'masterpacks':
            valid = re.fullmatch(r'/(?:pt|en|es|fr|de|it)/(?:produto|product)/[a-zA-Z0-9_/%-]+-\d+/?', p.path)
        elif key == 'nobleknight':
            valid = re.fullmatch(r'/P/\d+(?:/[a-zA-Z0-9_%+-]+)?/?', p.path)
        else:
            valid = re.fullmatch(r'/[a-z]{2}/[a-zA-Z0-9_/-]+', p.path)
        if not valid:
            raise ValueError('Use a product-page URL for the selected retailer.')
    return urlunsplit(('https', p.netloc, p.path or '/', '', ''))


def product_id(key, url):
    try:
        p = urlsplit(validate_url(key, url, product=True))
    except ValueError:
        return None
    if key == 'masterpacks':
        m = re.search(r'-(\d+)/?$', p.path)
    elif key == 'nobleknight':
        m = re.match(r'/P/(\d+)', p.path)
    else:
        return p.path.rstrip('/')
    return m[1] if m else None


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []; self.scripts = []; self.title = []; self._title = False
        self._json = None; self.refresh = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title': self._title = True
        if tag == 'a' and len(self.links) < 5000: self.links.append(attrs.get('href', ''))
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh': self.refresh = True
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json': self._json = []
    def handle_endtag(self, tag):
        if tag == 'title': self._title = False
        if tag == 'script' and self._json is not None:
            if len(self.scripts) < 50: self.scripts.append(''.join(self._json))
            self._json = None
    def handle_data(self, text):
        if self._title: self.title.append(text)
        if self._json is not None: self._json.append(text)


def schema_products(page):
    products = []
    for script in page.scripts:
        try:
            pending = [json.loads(script)]
        except (ValueError, RecursionError):
            continue
        examined = 0
        while pending and examined < 200:
            node = pending.pop(); examined += 1
            if isinstance(node, list):
                pending.extend(node[:100])
            elif isinstance(node, dict):
                kinds = node.get('@type', [])
                if isinstance(kinds, str): kinds = [kinds]
                if not isinstance(kinds, list): kinds = []
                if 'Product' in kinds: products.append(node)
                graph = node.get('@graph')
                if graph: pending.append(graph)
    return products


def analyze(key, url, status, body):
    page = Page(); page.feed(body)
    title = ' '.join(''.join(page.title).split())[:160]
    challenge = bool(re.search(r'captcha|just a moment|access denied|verify you are human', title, re.I)
                     or re.search(r'cf-chl-|challenge-platform', body[:12000], re.I))
    if status == 429:
        outcome = 'RATE_LIMITED'
    elif status in (401, 403) or challenge:
        outcome = 'ACCESS_CHALLENGE'
    elif status == 202 and page.refresh:
        outcome = 'LOADING_INTERSTITIAL'
    elif status != 200:
        outcome = 'HTTP_ERROR'
    else:
        outcome = 'READABLE'
    result = {'url': url, 'http_status': status, 'outcome': outcome, 'title': title,
              'product_links': [], 'products': [], 'product_nodes': 0}
    if outcome != 'READABLE': return result
    for href in page.links:
        try: target = validate_url(key, urljoin(url, href), product=True)
        except ValueError: continue
        if target not in result['product_links']: result['product_links'].append(target)
        if len(result['product_links']) >= 5: break
    expected = product_id(key, url)
    nodes = schema_products(page); result['product_nodes'] = len(nodes)
    for node in nodes:
        if not expected: continue
        offers = node.get('offers') or []
        if isinstance(offers, dict): offers = [offers]
        if not isinstance(offers, list): continue
        claimed = node.get('url')
        if claimed and product_id(key, urljoin(url, str(claimed))) != expected: continue
        scoped_offers = []
        for offer in offers[:20]:
            if not isinstance(offer, dict) or offer.get('@type') != 'Offer': continue
            offer_url = offer.get('url') or claimed
            if not offer_url or product_id(key, urljoin(url, str(offer_url))) != expected: continue
            # Keep condition and stock signal per offer. Do not turn an
            # AggregateOffer or a used copy into a new/sealed stock result.
            scoped_offers.append({k: str(offer.get(k) or 'Unknown')[:100]
                                  for k in ('price', 'priceCurrency', 'availability', 'itemCondition')})
        if scoped_offers:
            result['products'].append({'name': str(node.get('name') or 'Unknown')[:180],
                                       'id': expected, 'sku': str(node.get('sku') or node.get('mpn') or 'Unknown')[:80],
                                       'offers': scoped_offers[:3]})
        if len(result['products']) >= 3: break
    return result


async def fetch_page(session, key, url):
    url = validate_url(key, url)
    for _ in range(4):
        async with session.get(url, allow_redirects=False) as response:
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location: raise ValueError('Redirect had no location.')
                # Redirects stay on the exact retailer's public HTTPS origin.
                url = validate_url(key, urljoin(url, location))
                continue
            chunks = []; size = 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    return {'url': url, 'http_status': response.status, 'outcome': 'RESPONSE_TOO_LARGE',
                            'title': '', 'product_links': [], 'products': [], 'product_nodes': 0}
                chunks.append(chunk)
            return analyze(key, url, response.status, b''.join(chunks).decode('utf-8', errors='replace'))
    raise ValueError('Too many redirects.')


async def assess(key, sample=None):
    cfg = STORES[key]
    sample = validate_url(key, sample, product=True) if sample else cfg['sample']
    timeout = aiohttp.ClientTimeout(total=20, connect=8)
    async def inspect(session, url):
        try:
            return await fetch_page(session, key, url)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            return {'url': url, 'http_status': None, 'outcome': 'NETWORK_OR_REDIRECT_ERROR',
                    'title': type(error).__name__, 'product_links': [], 'products': [], 'product_nodes': 0}
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True,
            headers={'User-Agent': 'LotusTracker/1.0.6 (public retailer assessment)',
                     'Accept': 'text/html,application/xhtml+xml'}, cookie_jar=aiohttp.DummyCookieJar(),
            connector=aiohttp.TCPConnector(family=socket.AF_INET, limit=2, limit_per_host=1)) as session:
        root = await inspect(session, cfg['root'])
        pages = [root]
        # Do not continue after a loading page, access challenge or rate limit.
        if root['outcome'] == 'READABLE' and sample:
            await asyncio.sleep(1)
            pages.append(await inspect(session, sample))
    return {'key': key, 'checked_at': datetime.now(timezone.utc).isoformat(), 'pages': pages}


def safe(value, limit=200):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value)))[:limit]


def assessment_embed(data):
    cfg = STORES[data['key']]
    embed = discord.Embed(title=f"Retailer assessment • {cfg['name']}", colour=0x667ACD,
        description=f"Region: {cfg['region']} • Checked UTC: {data['checked_at']}\n"
                    'Read-only public-source inspection. No store was added and no alert was sent.')
    for index, page in enumerate(data['pages']):
        text = f"HTTP {page['http_status'] if page['http_status'] is not None else 'unavailable'} • {page['outcome']}\n{safe(page['title'], 160)}\n"
        text += f"Product links found (up to 5): {len(page['product_links'])}\nProduct schema nodes: {page['product_nodes']}"
        embed.add_field(name='Homepage' if index == 0 else 'Sample product page', value=text, inline=False)
        for product in page['products'][:2]:
            offers = []
            for offer in product['offers'][:3]:
                state = offer['availability'].rsplit('/', 1)[-1]
                condition = offer['itemCondition'].rsplit('/', 1)[-1]
                offers.append(safe(f"{offer['price']} {offer['priceCurrency']} • {state} • {condition}", 200))
            embed.add_field(name='Source-reported product', value=safe(product['name'], 180)
                + f"\nID: {safe(product['id'], 60)} • SKU/MPN: {safe(product['sku'], 80)}\n"
                + '\n'.join(offers), inline=False)
        if index > 0:
            embed.add_field(name='Inspected product URL', value=page['url'][:900], inline=False)
    if any(p['outcome'] != 'READABLE' for p in data['pages']):
        next_step = 'Access is incomplete. Keep this store pending; a platform override will not fix unreadable pages.'
    elif any(p['products'] for p in data['pages']):
        next_step = ('Product evidence is readable. Adapter work still needs discovery coverage, new/used condition handling, '
                     'and verified stock transitions before alert activation. Repeat with a known in-stock product URL to compare.')
    else:
        next_step = 'No offer was tied to the inspected product. Keep pending and inspect a public product page.'
    embed.add_field(name='Next step', value=next_step, inline=False)
    embed.set_footer(text=f'Retailer assessment {VERSION} • Schema reports are not checkout or shelf-stock verification')
    return embed


def register_retailer_assessment(bot):
    @bot.tree.command(name='retailerassessment', description='Inspect pending Turol, Masterpacks or Noble Knight sources without adding them.')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(store=[app_commands.Choice(name=cfg['name'], value=key) for key, cfg in STORES.items()])
    @app_commands.describe(product_url='Optional public product URL on the selected store to inspect instead of the sample.')
    async def retailerassessment(interaction: discord.Interaction, store: app_commands.Choice[str], product_url: str | None = None):
        if interaction.guild_id is None:
            await interaction.response.send_message('Run this in your server.', ephemeral=True)
            return
        if store.value not in STORES:
            await interaction.response.send_message('Choose a listed store.', ephemeral=True)
            return
        if product_url:
            try: validate_url(store.value, product_url, product=True)
            except ValueError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
        # One request sequence per domain per process, shared across servers.
        now = time.monotonic(); remaining = 60 - (now - _last_attempt.get(store.value, -1000))
        if store.value in _active or remaining > 0:
            await interaction.response.send_message('Assessment cooling down. Try again in one minute.', ephemeral=True)
            return
        _active.add(store.value); _last_attempt[store.value] = now
        try:
            await interaction.response.defer(ephemeral=True)
            result = await asyncio.wait_for(assess(store.value, product_url), timeout=50)
            await interaction.followup.send(embed=assessment_embed(result), ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            await interaction.followup.send(f'Assessment could not finish ({type(error).__name__}). Store remains pending.', ephemeral=True)
        finally:
            _active.discard(store.value)
