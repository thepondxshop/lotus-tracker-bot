"""Publisher-specific discovery routes and identities; no retailer availability inference."""
import re
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qs
from .extraction import norm

# Explicit routes: do not turn arbitrary news, cards or event pages into products.
ROOTS = {
    'Gundam':'https://www.gundam-gcg.com/en/products/',
    'Dragon Ball Fusion World':'https://www.dbs-cardgame.com/fw/en/products/',
    'Palworld':'https://en.palworld-official-cardgame.com/products',
    'Naruto':'https://www.narutotcgmythos.com/products',
    'MTG':'https://magic.wizards.com/en',
    'Riftbound':'https://playriftbound.com/en-us/',
    'Azuki TCG':'https://tcg.azuki.com/',
}
COVERAGE = {
    'Gundam':'US English boosters, decks, collections and accessories',
    'Dragon Ball Fusion World':'English boosters, decks, collections and accessories',
    'Palworld':'English boosters, trial decks and accessories',
    'Naruto':'Dedicated products and set overviews; combined pages stay grouped',
    'MTG':'Homepage-linked set/product families; individual SKU splitting is not enabled',
    'Riftbound':'Set overview announcements; individual SKU splitting is not enabled',
    'Azuki TCG':'Named AZK set announcements; individual SKU splitting is not enabled',
}

def _url(game, value):
    try:
        p=urlsplit(value); root=urlsplit(ROOTS[game])
        if p.scheme!='https' or p.hostname!=root.hostname or p.port not in (None,443) or p.username or p.password:
            return None
        return p
    except (ValueError,TypeError,KeyError):return None


def product_url(game, value):
    p=_url(game,value)
    if not p:return None
    path=p.path.rstrip('/')
    patterns={
        'Gundam':r'/en/products/(?!index\.|list\.)(?:[a-z0-9_-]+)\.html',
        'Dragon Ball Fusion World':r'/fw/en/products/\d{2}_\d+\.html',
        'Palworld':r'/products/(?!category$|page$)[a-z0-9-]+',
        'Naruto':r'/(?:set-\d+-+[a-z0-9-]+|starter-pack-set\d+-[a-z0-9-]+)',
        'MTG':r'/en/products/(?!card-set-archive$|product-guide$|secret-lair$)[a-z0-9-]+(?:/[a-z0-9-]+)?',
        'Riftbound':r'/en-us/news/announcements/(?:the-)?[a-z0-9-]+-overview',
        'Azuki TCG':r'/blog/[a-f0-9-]{36}',
    }
    if not re.fullmatch(patterns[game],path,re.I):return None
    if game=='MTG' and path.count('/')>3 and not path.startswith('/en/products/marvel/'):
        return None
    return urlunsplit(('https',urlsplit(ROOTS[game]).netloc,path+('/' if game=='Riftbound' else ''),'',''))


def index_url(game,value):
    p=_url(game,value)
    if not p:return None
    path=p.path.rstrip('/'); root=urlsplit(ROOTS[game]).path.rstrip('/')
    if path==root:
        if game=='Dragon Ball Fusion World':
            num=parse_qs(p.query).get('page',['1'])[0]
            if not num.isdigit() or not 1<=int(num)<=50:return None
            return ROOTS[game]+('?page='+str(int(num)) if int(num)>1 else '')
        return ROOTS[game]
    if game=='Gundam' and path=='/en/products/list.php':
        num=parse_qs(p.query).get('page',['1'])[0]
        if num.isdigit() and 1<=int(num)<=50:
            return 'https://'+p.netloc+path+('?page='+str(int(num)) if int(num)>1 else '')
    if game=='Palworld' and re.fullmatch(r'/products/(?:page/\d+|category/(?:trial-decks|booster-packs|others))',path):
        if '/page/' in path and not 1<=int(path.rsplit('/',1)[1])<=50:return None
        return 'https://'+p.netloc+path
    return None


def links(game,page):
    products=[];indexes=[]
    for href,label in page.get('links',[]):
        url=urljoin(page['url'],href)
        target=product_url(game,url)
        if game=='Azuki TCG' and target and not (re.search(r'\bAZK[ -]?\d+\b',label,re.I) and re.search(r'\bIntroducing\b',label,re.I) and not re.search(r'\bEVENT\b',label)):
            continue
        if target:
            if target!=page['url'] and target not in products:products.append(target)
        else:
            target=index_url(game,url)
            if target and target!=page['url'] and target not in indexes:indexes.append(target)
    return products+indexes


def _clean(value):return ' '.join(re.findall(r'[a-z0-9]+',norm(value)))
def _title(page):return re.split(r'\||｜',page.get('title',''),maxsplit=1)[0].strip()
def _lines(page):return [x.strip() for x in page.get('text','').splitlines() if x.strip()]


def packaging(title):
    text=norm(title)
    if re.search(r'(?:playmat|sleeves?)\s*(?:&|and)\s*card|card\s+collection|anniversary\s+set',text):return 'SET'
    if re.search(r'sleeves?|playmat|binder|storage\s+box|(?:card|deck)\s+(?:case|box|holder)',text):return 'ACCESSORY'
    if re.search(r'booster\s+(?:box|display)|display\s+box',text):return 'BOX'
    if re.search(r'(?:starter|trial|ultimate|champion)\s+deck',text):return 'DECK'
    if re.search(r'starter\s+pack|collection|bundle',text):return 'SET'
    if re.search(r'booster(?:\s+pack)?',text):return 'PACK'
    return 'UNKNOWN'


def identity(game,page):
    url=product_url(game,page.get('url',''))
    if not url:return None
    from .official_parser import access_challenge
    if access_challenge(page):return None
    lines=_lines(page); body='\n'.join(lines)
    title=_title(page); headings=page.get('headings',[])+page.get('detail_headings',[])
    if re.search(r'404|not found|registration|event ticket',title,re.I):return None
    form='UNKNOWN'; scope='PRODUCT';code=None;language='UNKNOWN';region='UNKNOWN'
    if game in ('Gundam','Dragon Ball Fusion World','Palworld'):
        if not 5<=len(title)<=180:return None
        # Palworld places its product title in plain text rather than an h tag.
        evidence=headings if game!='Palworld' else lines[:14]
        if not any(_clean(x)==_clean(title) for x in evidence):return None
        if not re.search(r'\b(?:Contents|MSRP|Product Specifications|Release Date)\b',body,re.I):return None
        if game=='Gundam':
            # Use only a heading that contains the main name, not unrelated products.
            forms=[packaging(x) for x in headings if _clean(title) in _clean(x)]
            form=next((x for x in forms if x!='UNKNOWN'),packaging(title))
            expected=re.fullmatch(r'(gd|st|pc)(\d+)(a?)',urlsplit(url).path.rsplit('/',1)[-1][:-5],re.I)
            if expected:
                m=re.search(r'\[('+expected[1]+r')[ -]?('+expected[2]+expected[3]+r')\]',title,re.I)
                if not m:return None
                code=m[1].upper()+'-'+m[2].upper()
            region='US'
        else:form=packaging(title)
        if game=='Dragon Ball Fusion World':
            codes=re.findall(r'\[((?:FB|FS|SB|ST))[ -]?(\d+)\]',title,re.I)
            if len(codes)>1:return None
            if codes:code=codes[0][0].upper()+'-'+codes[0][1]
        language='English'
    elif game=='Naruto':
        primary=next((x for x in page.get('headings',[]) if re.match(r'^SET\s+\d+\s*:',x,re.I)),None)
        if primary and re.search(r'\b(?:THE SET PRODUCTS|booster packs?|starter packs?)\b',body,re.I):
            title='Naruto Mythos TCG: '+primary;scope='PRODUCT_GROUP'
        else:
            primary=next((x for x in page.get('detail_headings',[])[:4] if packaging(x)!='UNKNOWN'),None)
            set_name=next((x for x in lines[:12] if re.match(r'^Set\s+\d+\s*:',x,re.I)),None)
            if not primary or not set_name or not re.search(r'\b(?:contains?|includes?|cards|packs)\b',body,re.I):return None
            # Preserve first/second edition from the URL when it is explicit in the title.
            edition=re.search(r'\b\d+(?:st|nd|rd|th) edition\b',title,re.I)
            title='Naruto Mythos TCG: '+set_name+' — '+primary+(' '+edition[0] if edition and edition[0].lower() not in primary.lower() else '')
            form=packaging(primary)
    elif game=='MTG':
        primary=next((x for x in page.get('headings',[])[:2] if len(x)>4),None)
        if not primary or not re.search(r'\b(?:play boosters?|collector boosters?|commander decks?|starter kit|bundle)\b',body,re.I):return None
        if _clean(primary) not in _clean(page.get('title','')):return None
        title='Magic: The Gathering — '+primary;scope='PRODUCT_GROUP'
    elif game=='Riftbound':
        m=re.fullmatch(r'(?:The )?(.+?) Overview',title,re.I)
        if not m or not any(_clean(h)==_clean(title) for h in headings[:3]):return None
        name=m[1]
        if not re.search(r'\b'+re.escape(name)+r'\s+Product Line[- ]Up\b',body,re.I):return None
        if not re.search(r'\bRiftbound\b',body):return None
        title='Riftbound: '+name;scope='PRODUCT_GROUP'
    elif game=='Azuki TCG':
        m=re.fullmatch(r'Introducing\s+(.+?)\s*\(AZK[ -]?(\d+)\)',title,re.I)
        if not m or not any(_clean(h)==_clean(title) for h in headings[:3]):return None
        if not re.search(r'\bset for Azuki TCG\b',body,re.I):return None
        title='Azuki TCG: '+m[1]+' [AZK-'+m[2]+']';code='AZK-'+m[2];scope='SET'
    if not 5<=len(title)<=220:return None
    return dict(url=url,game=game,title=title,set_code=code,product_format=form,
                language=language,region=region,publisher_scope=scope)


def date_text(game,page):
    """Only dedicated release fields; no publication, preview or tournament dates."""
    from .official_parser import DATE_RE
    if game=='Naruto':return ''  # different products on overview pages have different dates
    lines=_lines(page);dates=[]
    for i,line in enumerate(lines):
        m=re.match(r'^Release(?: Date)?\s*:?\s*(.*)$',line,re.I)
        if not m:continue
        value=m[1] or (lines[i+1] if i+1<len(lines) else '')
        value=re.sub(r'(?<=\d),(?=20\d{2}\b)',', ',value)
        d=DATE_RE.match(value)
        if d:dates.append('Release '+d[0])
    if game=='Azuki TCG':
        # The introduction's named-set release, not a later article's dates.
        intro=' '.join(lines)[:1800]
        m=re.search(r'\bset for Azuki TCG,\s+releases\s+(.{1,40})',intro,re.I)
        if m:
            d=DATE_RE.match(m[1])
            if d:dates.append('Release '+d[0])
    return '\n'.join(dates)
