"""Public distributor metadata adapters. No account access or stock inference.

Public page shapes reviewed 2026-09-20. New adapters are preview integrations:
their HTTP reachability must be checked from the deployed worker.
"""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, parse_qsl, urlencode, urlunsplit

ADAPTER_VERSION = '1.3.1-preview'
PRESETS = {
    'gts': dict(label='GTS Distribution', url='https://gtsdistribution.com/pc_combined_results.asp?faceted_search_terms=Category~04552AD14A72447B95ECFC368E1CB6BD', region='UNKNOWN', ready=True, status='SUPPORTED',
                note='Existing public card-game catalog importer. Reuses a matching watch and preserves its settings.'),
    'southern': dict(label='Southern Hobby Distribution', url='https://www.southernhobby.com/products_recent.php', region='UNKNOWN', ready=True,
                     note='Preview: recent public products. Automated access challenge observed; scan on Railway to verify access.'),
    'phd': dict(label='PHD Games', url='https://www.phdgames.com/blog-tcgs/', region='UNKNOWN', ready=True,
                note='Preview: public TCG announcements. Separates product blocks by SKU; ambiguous blocks still require review.'),
    'grosnor': dict(label='Grosnor Distribution (Canada)', url='https://www.grosnor.com/product-category/234', region='CA', ready=True,
                    note='Preview: public category titles/SKUs only. Detail pages require login; no inferred release dates. HTTP 403 observed.'),
    'alliance': dict(label='Alliance Game Distributors', url='https://www.alliance-games.com/', region='UNKNOWN', ready=False,
                     note='Pending: public discovery endpoint not validated; site request timed out.'),
    'acd': dict(label='ACD Distribution', url='https://www.acdd.com/', region='UNKNOWN', ready=False,
                note='Pending: JavaScript storefront; no usable public product feed validated.'),
    'universal_us': dict(label='Universal Distribution (US)', url='https://us.universaldist.com/', region='US', ready=False,
                         note='Pending: regional site found; public product feed not validated.'),
    'universal_ca': dict(label='Universal Distribution (Canada)', url='https://ca.universaldist.com/', region='CA', ready=False,
                         note='Pending: regional site found; public product feed not validated.'),
}

def hostname(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')

def product_url(url):
    domain, path = hostname(url), urlsplit(url).path
    if domain == 'southernhobby.com':
        return bool(re.search(r'/p\d+/?$', path))
    if domain == 'phdgames.com':
        return bool(re.fullmatch(r'/\d{4}/\d{2}/\d{2}/[^/]+/?', path))
    return False

def listing_allowed(seed, link):
    """Return None for sites handled by the generic pagination policy."""
    domain = hostname(seed)
    if domain != hostname(link):
        return False
    a, b = urlsplit(seed), urlsplit(link)
    if domain == 'phdgames.com':
        base = re.sub(r'/page/\d+/?$', '/', a.path).rstrip('/')
        other = re.sub(r'/page/\d+/?$', '/', b.path).rstrip('/')
        return base == other and a.query == b.query
    if domain == 'grosnor.com':
        # A broad CCG source may follow subcategories, but never the rest of the catalog.
        return (a.path.startswith('/product-category/') and
                (a.path.rstrip('/') == b.path.rstrip('/') or
                 (a.path.rstrip('/') == '/product-category/234' and b.path.startswith('/product-category/'))))
    return None

class Markup(HTMLParser):
    """Small text/anchor reader; preserves breaks without executing scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.anchors=[]; self.headings=[]
        self.skip=0; self.anchor=None; self.heading=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag in ('script','style','noscript'): self.skip+=1
        if tag in ('div','p','br','tr','td','li','h1','h2','h3','h4','h5','section','article'): self.parts.append('\n')
        if tag == 'a': self.anchor=[attrs.get('href',''), []]
        if tag in ('h1','h2'): self.heading=[tag, []]
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript'): self.skip=max(0,self.skip-1)
        if tag == 'a' and self.anchor:
            self.anchors.append((self.anchor[0], ' '.join(''.join(self.anchor[1]).split())))
            self.anchor=None
        if tag in ('h1','h2') and self.heading:
            self.headings.append((self.heading[0], ' '.join(''.join(self.heading[1]).split())))
            self.heading=None
        if tag in ('div','p','tr','td','li','h1','h2','h3','h4','h5','section','article'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.anchor: self.anchor[1].append(data)
            if self.heading: self.heading[1].append(data)
    @property
    def text(self):
        return '\n'.join(' '.join(x.split()) for x in ''.join(self.parts).splitlines() if x.strip())

def first(pattern, text):
    m=re.search(pattern,text,re.I)
    return m[1].strip() if m else None

def public_data(url, body, diagnostics=None):
    """Return None for generic sites, or (raw products, product links, listings, issues).

    Grosnor facts are taken from public anchor text only; its login-protected
    detail URLs are identifiers, never followed by this adapter.
    """
    domain=hostname(url)
    if domain not in ('southernhobby.com','phdgames.com','grosnor.com'): return None
    page=Markup();page.feed(body)
    text=page.text; products=[]; links=[]; listings=[]; issues=[]
    if re.search(r'<title[^>]*>\s*(?:One moment|Just a moment|Access Denied)',body,re.I):
        return [],[],[],['ACCESS_CHALLENGE']
    if urlsplit(url).path.rstrip('/') in ('/login','/sign-in'):
        return [],[],[],['LOGIN_REQUIRED']
    for href, title in page.anchors:
        # Distributor navigation may include HTTP, malformed URLs, or script links.
        # Apply the same validation used by generic extraction before returning links.
        from .extraction import canonical_url
        from .service import CatalogError
        try:
            target=canonical_url(urljoin(url,href))
        except (CatalogError, ValueError):
            continue
        if hostname(target)!=domain: continue
        if domain=='grosnor.com' and re.fullmatch(r'/product/[^/]+/?',urlsplit(target).path):
            if not title: continue
            p=urlsplit(target)
            target=urlunsplit((p.scheme,p.netloc,p.path,'',''))
            products.append(dict(name=title,sku=p.path.rstrip('/').rsplit('/',1)[-1],url=target,
                description='Public category listing: '+url+'\n'+title,
                _extractor='GROSNOR_PUBLIC_LISTING',_issues=['LISTING_ONLY_NO_RELEASE_DATE']))
        elif product_url(target): links.append(target)
        elif domain=='grosnor.com':
            ccg_categories=('alpha clash','force of will','konami (yugioh)','kayou tcg',
                'pokemon usa (pokemon)','soul masters tcg','upper deck entertainment',
                'misc. collectible card games','all collectible card games')
            if (urlsplit(target).path==urlsplit(url).path or title.casefold() in ccg_categories) and listing_allowed(url,target):
                listings.append(target)
        elif listing_allowed(url,target) is not False: listings.append(target)
    if domain=='southernhobby.com' and product_url(url):
        title=next((v for tag,v in page.headings if tag=='h1'),None)
        if title:
            details=text.split(title,1)[-1].split('In This Category',1)[0]
            sku=first(r'Item\s*#\s*[:|]?\s*([A-Z0-9][A-Z0-9_-]*)',details)
            if sku:
                products=[dict(name=title,sku=sku,url=url,description=details,
                    release_date=first(r'Release Date\s*:\s*(\d{2}/\d{2}/\d{4})',details),
                    order_due_date=first(r'Order Due Date\s*:\s*(\d{2}/\d{2}/\d{4})',details),
                    product_format=first(r'Sold As\s*:\s*(BOX|CASE|PACK|DECK|SET)\b',details),
                    _extractor='SOUTHERN_PUBLIC_PRODUCT')]
        links=[];listings=[]
    elif domain=='phdgames.com' and product_url(url):
        products, issues = phd_products(url, text, diagnostics)
        links=[];listings=[]
    return products,links,listings,issues



def article_url(url):
    """Remove Lotus's local SKU fragment before fetching the real article."""
    p=urlsplit(url)
    return urlunsplit((p.scheme,p.netloc,p.path,p.query,''))


def phd_sku_fragment(url):
    p=urlsplit(url)
    if hostname(url)=='phdgames.com' and product_url(url) and re.fullmatch(r'lotus-sku=[A-Z0-9_-]{1,100}',p.fragment):
        return p.fragment
    return ''


def phd_products(url, text, diagnostics=None):
    """Parse adjacent title/Publisher/Item Code blocks, with per-block dates.

    SKU fragments are Lotus record identifiers, not publisher-provided anchors.
    Requests always use the original article URL. Single-SKU URLs stay unchanged
    to preserve earlier item identities.
    """
    def report(reason, block=None, sku=None, context=''):
        if diagnostics is not None and len(diagnostics)<21:
            diagnostics.append(dict(url=article_url(url),reason=reason,block=block,
                sku=sku,context=' '.join(context.split())[:220]))
    text=re.split(r'(?im)^Recent posts\s*$',text,maxsplit=1)[0]
    markers=list(re.finditer(r'(?im)^Item Code\s*:\s*([^\n]+)',text))
    products=[];issues=[];blocks=[]
    if len(markers)>100:
        report('ARTICLE_HAS_MORE_THAN_100_ITEM_CODES')
        return [],['PHD_ARTICLE_PRODUCT_LIMIT']
    previous_end=0
    for block_number,m in enumerate(markers,1):
        before=text[previous_end:m.start()]
        pubs=list(re.finditer(r'(?im)^Publisher\s*:\s*([^\n]+)',before))
        if not pubs:
            report('MISSING_PUBLISHER_BEFORE_ITEM_CODE',block_number,context=m[0])
            issues.append('PHD_PRODUCT_BLOCK_AMBIGUOUS');previous_end=m.end();continue
        pub=pubs[-1]
        prefix=before[:pub.start()].rstrip()
        title=prefix.splitlines()[-1] if prefix else ''
        sku_match=re.fullmatch(r'([A-Z0-9][A-Z0-9_-]{0,99})(?:\s+\([^\n]*\))?\s*',m[1],re.I)
        if not title or not sku_match:
            report('MISSING_PRODUCT_TITLE' if not title else 'ITEM_CODE_NOT_A_SINGLE_SKU',block_number,context=m[0])
            issues.append('PHD_PRODUCT_BLOCK_AMBIGUOUS');previous_end=m.end();continue
        start=previous_end+len(prefix)-len(title)
        blocks.append((start,m.end(),title,sku_match[1].upper(),pub[1].strip()))
        previous_end=m.end()
    for i,(start,end,title,sku,maker) in enumerate(blocks):
        # Never read through even a malformed following SKU block.
        next_marker=next((m.start() for m in markers if m.start()>=end),len(text))
        stop=min(blocks[i+1][0] if i+1<len(blocks) else len(text),next_marker)
        description=text[start:stop]
        dates=set(re.findall(r'(?i)\bReleases\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})',description))
        row_issues=[]
        if len(dates)>1: row_issues.append('PHD_RELEASE_DATE_CONFLICT')
        if not dates: row_issues.append('PHD_RELEASE_DATE_MISSING')
        products.append(dict(name=title,sku=sku,url=article_url(url)+(('#lotus-sku='+sku) if len(markers)>1 else ''),
            description=description,manufacturer=maker,
            release_date=next(iter(dates)) if len(dates)==1 else None,
            _extractor='PHD_PUBLIC_ANNOUNCEMENT',_issues=row_issues))
    unique={};conflicts=set()
    for row in products:
        old=unique.get(row['sku'])
        if old and any(old[k]!=row[k] for k in ('name','release_date','manufacturer')):
            conflicts.add(row['sku'])
        else: unique[row['sku']]=row
    if conflicts:
        issues.append('PHD_DUPLICATE_SKU_CONFLICT')
        for sku in sorted(conflicts): report('DUPLICATE_SKU_HAS_CONFLICTING_DETAILS',sku=sku)
    return [row for sku,row in unique.items() if sku not in conflicts],sorted(set(issues))
