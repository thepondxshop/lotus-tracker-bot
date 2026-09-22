"""Conservative publisher evidence extraction; never infers stock or exact days."""
import calendar
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from .extraction import canonical_url, host, norm, code, CODE

VERSION = '1.4.0-preview'
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
        if tag in ('h1','h2'): self.heading = []
        if tag == 'a' and a.get('href'): self.anchor = [a['href'], []]
        if tag == 'img' and self.heading is not None: self.heading.append(a.get('alt',''))
        if tag in ('p','div','section','article','h1','h2','h3','li','dt','dd','tr','br'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]: self.skip.pop()
            return
        if tag == 'title': self.in_title = False
        if tag in ('h1','h2') and self.heading is not None:
            self.headings.append(' '.join(self.heading)); self.heading = None
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
            'text':text[:100000], 'links':doc.links[:800]}


def discovery_links(game, page, releases):
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


def identity_match(release, page):
    """Match headings, never navigation or an arbitrary mention in article text."""
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
    if not match: return None
    windows=release_windows(page['text'])
    result={'url':page['url'],'match_scope':match,'language':language,'region':region,
            'publisher_title':page['title'],'windows':windows,
            'state':'OFFICIAL_MENTION','issues':[]}
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
