"""Azuki's public product catalog: product identities, not retailer stock."""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qs, urljoin

ROOT = 'https://tcg.azuki.com/'
INDEX = ROOT + 'products'
VERSION = '1.6.9-AZ1'


def parsed_url(value):
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.hostname != 'tcg.azuki.com'
                or p.port not in (None, 443) or p.username or p.password):
            return None
        return p
    except (TypeError, ValueError):
        return None


def product_url(value):
    p = parsed_url(value)
    if not p or not re.fullmatch(r'/products/[a-z0-9]+(?:-[a-z0-9]+)*', p.path.rstrip('/')):
        return None
    if p.path.rstrip('/').split('/')[-1] in {'category', 'page', 'search'}:
        return None
    return urlunsplit(('https', 'tcg.azuki.com', p.path.rstrip('/'), '', ''))


def index_url(value):
    p = parsed_url(value)
    if not p or p.path.rstrip('/') != '/products':
        return None
    params = parse_qs(p.query)
    # Category filters are unnecessary: the complete catalog includes every type.
    if set(params) - {'page'}:
        return None
    pages = params.get('page', ['1'])
    if len(pages) != 1 or not pages[0].isdigit() or not 1 <= int(pages[0]) <= 50:
        return None
    n = int(pages[0])
    return INDEX + (f'?page={n}' if n > 1 else '')


def image_url(page, title):
    """Use the actual product image, never Azuki's generic Open Graph logo."""
    for image in page.get('images', []):
        alt = ' '.join(image.get('alt', '').split())
        if not alt.casefold().startswith(title.casefold() + ' product image'):
            continue
        value = urljoin(page['url'], image.get('src', ''))
        p = parsed_url(value)
        if p and p.path == '/_next/image':
            value = parse_qs(p.query).get('url', [''])[0]
        try:
            p = urlsplit(value)
            if (p.scheme == 'https' and p.hostname == 'static-content.azuki.com'
                    and p.port in (None, 443) and not p.username and not p.password
                    and p.path.startswith('/tcg/products/')):
                return value
        except ValueError:
            pass
    return None


def identity(page):
    url = product_url(page.get('url', ''))
    if not url:
        return None
    title = next(iter(page.get('headings', [])), '').strip()
    if not 5 <= len(title) <= 200 or re.search(r'404|not found|registration|event ticket|tournament entry', title, re.I):
        return None
    body = page.get('text', '')
    skus = set(re.findall(r'^SKU\s*:\s*([A-Z0-9_-]+)\s*$', body, re.I | re.M))
    if len(skus) != 1 or not re.search(r'^(?:Release date|Includes|Configuration)\s*:', body, re.I | re.M):
        return None
    codes = set(re.findall(r'\bAZK[ -]?(\d+)\b', title, re.I))
    explicit = re.search(r'^Set\s*:\s*AZK[ -]?(\d+)\s*$', body, re.I | re.M)
    if explicit:
        codes.add(explicit[1])
    if len(codes) > 1:
        return None
    from .publisher_products import packaging
    form = packaging(title)
    # The website category says "Deck boxes" even though this is sealed TCG.
    includes = re.search(r'^Includes\s*:\s*(.*)', body, re.I | re.M | re.S)
    packs = promos = None
    if includes:
        p = re.search(r'\b(\d+)\s+boosters?\s+packs?\b', includes[1], re.I)
        c = re.search(r'\b(\d+)\s+promo\s+cards?\b', includes[1], re.I)
        packs, promos = (int(p[1]) if p else None), (int(c[1]) if c else None)
    if re.search(r'\brelic hunter box\b', title, re.I) and packs and promos:
        form = 'SET'
    def field(name):
        m = re.search(r'^' + name + r'\s*:\s*([^\n]{1,40})$', body, re.I | re.M)
        return m[1].strip() if m else 'UNKNOWN'
    item = dict(url=url, game='Azuki TCG', title='Azuki TCG: ' + title,
                set_code='AZK-' + next(iter(codes)) if codes else None,
                sku=next(iter(skus)), product_format=form, publisher_scope='PRODUCT',
                region=field('Region'), language=field('Language'), image_url=image_url(page, title))
    if packs is not None:
        item['contained_booster_packs'] = packs
    if promos is not None:
        item['promo_cards'] = promos
    for key, pattern in (
        ('boxes_per_case', r'cases contain\s+(\d+)\s+boxes'),
        ('packs_per_box', r'boxes contain\s+(\d+)\s+packs'),
        ('cards_per_pack', r'packs contain\s+(\d+)\s+cards'),
    ):
        m = re.search(pattern, body, re.I)
        if m:
            item[key] = int(m[1])
    return item
