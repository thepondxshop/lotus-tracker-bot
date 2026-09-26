"""Conservative publisher evidence extraction; never infers stock or exact days."""
import calendar
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs
from .extraction import canonical_url, host, norm, code, CODE
from . import pokemon_products
from .one_piece_products import product_path, product_identity, main_text, main_title, BOOSTERS

VERSION = '1.6.5'
# Publisher-owned pages, reviewed 2026-09-20. Reachability is reported at runtime.
PRESETS = {
    'One Piece': ('https://en.onepiece-cardgame.com/products/', 'EN', 'UNKNOWN'),
    'Pokemon': ('https://www.pokemon.com/us/pokemon-tcg/product-gallery', 'EN', 'US'),
    'Gundam': ('https://www.gundam-gcg.com/en/products/', 'EN', 'US'),
    'Dragon Ball Fusion World': ('https://www.dbs-cardgame.com/fw/en/products/', 'EN', 'UNKNOWN'),
    'Riftbound': ('https://playriftbound.com/en-us/', 'EN', 'UNKNOWN'),
    'Palworld': ('https://en.palworld-official-cardgame.com/products', 'EN', 'UNKNOWN'),
    'Naruto': ('https://www.narutotcgmythos.com/products', 'EN', 'UNKNOWN'),
    'Cyberpunk TCG': ('https://cyberpunktcg.com/blog', 'EN', 'UNKNOWN'),
    'Azuki TCG': ('https://tcg.azuki.com/', 'EN', 'UNKNOWN'),
    'Hellbreak TCG': ('https://hellbreakgame.com/blogs/news/hellbreak-launch-update', 'UNKNOWN', 'GLOBAL'),
}


def approved_url(game, url):
    value = canonical_url(url)
    if game not in PRESETS or host(value) != host(PRESETS[game][0]):
        raise ValueError('Use the publisher domain listed by /release official sources for this game.')
    p = urlsplit(value)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = []
        self.title = []
        self.headings = []
        self.detail_headings = []
        self.heading_tag = None
        self.parts = []
        self.links = []
        self.heading = None
        self.in_title = False
        self.anchor = None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script','style','noscript','nav','footer','header'):
            self.skip.append(tag)
        if self.skip: return
        if tag == 'title': self.in_title = True
        if tag in ('h1','h2','h3','h4'):
            self.heading = []; self.heading_tag = tag
        if tag == 'a' and a.get('href'): self.anchor = [a['href'], []]
        if tag == 'img' and self.heading is not None: self.heading.append(a.get('alt',''))
        if tag in ('p','div','section','article','h1','h2','h3','li','dt','dd','tr','br'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]: self.skip.pop()
            return
        if tag == 'title': self.in_title = False
        if tag == self.heading_tag and self.heading is not None:
            target = self.headings if tag in ('h1','h2') else self.detail_headings
            target.append(' '.join(self.heading)); self.heading = None; self.heading_tag = None
        if tag == 'a' and self.anchor:
            self.links.append((self.anchor[0], ' '.join(self.anchor[1]))); self.anchor = None
        if tag in ('p','div','section','article','h1','h2','h3','li','dt','dd','tr'): self.parts.append('\n')
    def handle_data(self, value):
        if self.skip: return
        value = ' '.join(value.split())
        if not value: return
        if self.in_title: self.title.append(value); return
        self.parts.append(value+' ')
        if self.heading is not None: self.heading.append(value)
        if self.anchor: self.anchor[1].append(value)


def parse_page(url, html):
    doc = Document(); doc.feed(html)
    text = '\n'.join(' '.join(x.split()) for x in ''.join(doc.parts).splitlines() if x.strip())
    return {'url':url, 'title':' '.join(doc.title)[:500], 'headings':doc.headings[:30],
            'text':text[:100000], 'links':doc.links[:800], 'detail_headings':doc.detail_headings[:30]}


def discovery_links(game, page, releases):
    if game == 'Pokemon':
        products, indexes = [], []
        for href, _ in page.get('links', []):
            try:
                url = approved_url(game, urljoin(page['url'], href))
            except (ValueError, TypeError):
                continue
            product = pokemon_products.product_url(url)
            index = pokemon_products.index_url(url)
            target, value = (products, product) if product else (indexes, index)
            if value and value != page['url'] and value not in target:
                target.append(value)
        return products + indexes
    if game == 'One Piece':
        products, indexes = [], []
        for href, _ in page['links']:
            try:
                url = approved_url(game, urljoin(page['url'], href))
            except (ValueError, TypeError):
                continue
            parsed = urlsplit(url)
            if product_path(url):
                url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
                target = products
            elif parsed.path.rstrip('/') == '/products':
                params = parse_qs(parsed.query)
                number = params.get('page', ['1'])[0]
                if not number.isdigit() or not 1 <= int(number) <= 100:
                    continue
                url = 'https://en.onepiece-cardgame.com/products/' + ('?page='+str(int(number)) if int(number)>1 else '')
                target = indexes
            else:
                continue
            if url != page['url'] and url not in target:
                target.append(url)
        return products + indexes
    links = []
    for href, label in page['links']:
        try: url = approved_url(game, urljoin(page['url'], href))
        except (ValueError, TypeError): continue
        path = urlsplit(url).path.lower()
        if re.search(r'\.(?:png|jpg|jpeg|gif|pdf|zip|svg|webp)$',path): continue
        if any(x in path for x in ('/login','/account','/cart','/events','/rules','/cardlist','/cards/','privacy','terms')): continue
        if url == page['url'] or url in links: continue
        if not re.search(r'product|news|blog|article|booster|deck|expansion|set|release',path): continue
        links.append(url)
    # Prioritize a release code/name in the link, but persist the remaining queue.
    def priority(url):
        compact = re.sub(r'[^a-z0-9]','',url.lower())
        return 0 if any(code(r.get('set_code')) and code(r['set_code']).lower() in compact for r in releases) else 1
    return sorted(links,key=priority)


MONTHS = {m.lower(): i for i,m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower():i for i,m in enumerate(calendar.month_abbr) if m})
MONTH_RE = '|'.join(sorted(MONTHS,key=len,reverse=True))
DATE_RE = re.compile(rf'\b(?:(?P<iso>20\d{{2}}-\d{{2}}-\d{{2}})|(?P<month>{MONTH_RE})\.?\s+(?:(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,.]?\s+)?(?P<year>20\d{{2}})|(?P<quarter>Q[1-4])\s+(?P<qy>20\d{{2}}))\b',re.I)
RELEASE_WORD = re.compile(r'\breleas(?:e|es|ed|ing)|\blaunch(?:es|ing)?\b|\bavailable\b|\bon sale\b',re.I)


def release_windows(text):
    """Only dates after release wording; publishing/order deadlines aren't dates."""
    found = []
    for m in DATE_RE.finditer(text):
        prefix = text[max(0,m.start()-170):m.start()]
        marker = list(RELEASE_WORD.finditer(prefix))
        if not marker: continue
        if re.search(r'pre.?order\s*$',prefix[:marker[-1].start()],re.I): continue
        if re.search(r'update|announcement|posted|published',prefix[marker[-1].end():],re.I): continue
        context = prefix[max(0,marker[-1].start()-25):]
        if re.search(r'pre.?order|order due|deadline|copyright|published|posted',context,re.I): continue
        try:
            if m['iso']:
                start = end = date.fromisoformat(m['iso']); precision='DAY'
            elif m['quarter']:
                y=int(m['qy']); mo=(int(m['quarter'][1])-1)*3+1
                start=date(y,mo,1);end=date(y,mo+2,calendar.monthrange(y,mo+2)[1]);precision='QUARTER'
            else:
                y=int(m['year']); mo=MONTHS[m['month'].lower()]
                if m['day']: start=end=date(y,mo,int(m['day']));precision='DAY'
                else: start=date(y,mo,1);end=date(y,mo,calendar.monthrange(y,mo)[1]);precision='MONTH'
        except ValueError: continue
        row={'label':m.group(), 'precision':precision, 'start':start.isoformat(), 'end':end.isoformat(),
             'excerpt':(context+m.group())[-300:]}
        if not any((x['start'],x['end'])==(row['start'],row['end']) for x in found): found.append(row)
    return found


def primary_product_text(page):
    """Do not let related One Piece products supply the main product's date."""
    if pokemon_products.product_url(page.get('url', '')):
        return pokemon_products.date_text(page)
    return main_text(page)


def identity_match(release, page):
    """Match headings, never navigation or an arbitrary mention in article text."""
    if norm(release.get('game')) == 'pokemon' and pokemon_products.product_url(page.get('url', '')):
        item = pokemon_products.product_identity(page)
        if not item or pokemon_products.comparable(release['title']) != pokemon_products.comparable(item['title']):
            return None
        return item['publisher_scope']
    if norm(release.get('game')) == 'one piece' and product_path(page.get('url', '')):
        item = product_identity(page)
        if not item:
            return None
        clean = lambda x: ' '.join(re.findall(r'[a-z0-9]+', norm(main_title(x))))
        if clean(release['title']) == clean(item['title']):
            return 'SET' if str(item.get('set_code') or '').split('-')[0] in BOOSTERS else 'PRODUCT'
        wanted = code(release.get('set_code'))
        if wanted and wanted == code(item.get('set_code')):
            # A shared contained-booster code cannot confirm a collection.
            if str(item.get('set_code') or '').split('-')[0] not in BOOSTERS:
                return 'PRODUCT' if release.get('product_format') == item['product_format'] else None
            if item['product_format'] in ('PACK', 'BOX') and release.get('product_format') in ('PACK', 'BOX', 'CASE', 'UNKNOWN', None):
                return 'SET'
        return None
    titles = page['headings'][:3] + [page['title'].split('|')[0].split('｜')[0]]
    wanted = code(release.get('set_code'))
    if not wanted:
        codes={code(m.group()) for m in CODE.finditer(release['title'])}
        wanted=next(iter(codes)) if len(codes)==1 else None
    if wanted:
        for title in titles:
            codes={code(m.group()) for m in CODE.finditer(title)}
            if codes == {wanted}: return 'SET'
    clean=lambda x:' '.join(re.findall(r'[a-z0-9]+',norm(x)))
    title=clean(release['title'])
    if len(title)>12 and any(clean(t)==title for t in titles): return 'PRODUCT'
    return None


def evaluate(release, page, language, region):
    match = identity_match(release,page)
    # This announcement is game-wide; it does not prove every individual SKU's date.
    launch = (norm(release['game'])=='hellbreak tcg'
              and urlsplit(page['url']).path.rstrip('/')=='/blogs/news/hellbreak-launch-update'
              and ('dawn of terror' in norm(release['title'])
                   or ('jaws' in norm(release['title']) and 'dracula' in norm(release['title']))))
    if launch: match='GAME_LAUNCH'
    if norm(release.get('game')) == 'pokemon' and pokemon_products.product_url(page.get('url', '')):
        language, region = 'English', 'US'
    if not match: return None
    windows=release_windows(primary_product_text(page))
    result={'url':page['url'],'match_scope':match,'language':language,'region':region,
            'publisher_title':page['title'],'windows':windows,
            'state':'OFFICIAL_MENTION','issues':[]}
    if match == 'PRODUCT_GROUP':
        result['issues'].append('Multiple product variants; not one combined bundle.')
    if launch:
        windows=[w for w in windows if 'worldwide launch' in w['excerpt'].lower()]
        result['windows']=windows
    if len(windows)>1:
        result['state']='DATE_REVIEW';result['issues'].append('MULTIPLE_RELEASE_WINDOWS')
    elif windows:
        result['state']='OFFICIAL_LAUNCH_WINDOW' if launch else 'OFFICIAL_DATE_EVIDENCE'
    if release.get('release_date') and len(windows)==1:
        if not windows[0]['start']<=release['release_date']<=windows[0]['end']:
            result['issues'].append('CATALOG_DATE_CONFLICT');result['state']='DATE_REVIEW'
    # Explicitly report edition uncertainty; never silently copy English dates to JP etc.
    from .extraction import scope
    if scope(release.get('language')) not in ('unknown',scope(language)) and scope(language)!='unknown':
        result['issues'].append('LANGUAGE_MISMATCH');result['state']='EDITION_REVIEW'
    if region!='GLOBAL' and scope(release.get('region')) not in ('unknown',scope(region)):
        result['issues'].append('REGION_REVIEW');result['state']='EDITION_REVIEW'
    if scope(release.get('region'))=='unknown' or scope(region)=='unknown': result['issues'].append('REGION_UNVERIFIED')
    if scope(release.get('language'))=='unknown' or scope(language)=='unknown': result['issues'].append('LANGUAGE_UNVERIFIED')
    return result
