"""Identity and packaging of individual English One Piece product pages."""
import re
from urllib.parse import urlsplit

PRODUCT_PATH = re.compile(r'^/products/(?:(?:boosters|decks|other)/)?([a-z0-9_-]+)\.(?:html|php)$', re.I)
CODE_PATH = re.compile(r'^(peb|prb|op|eb|st|sd|dp|df|ts|ib)(\d{1,3})$', re.I)
TITLE_CODE = re.compile(r'\[([A-Z]{2,4})[ -]?(\d{1,3})\]', re.I)
BOOSTERS = {'OP', 'EB', 'PRB', 'PEB'}


def product_path(url):
    p = urlsplit(url)
    match = PRODUCT_PATH.fullmatch(p.path)
    if p.hostname != 'en.onepiece-cardgame.com' or p.scheme != 'https' or not match:
        return None
    if match[1].lower() in ('index', 'products', 'boosters', 'decks', 'other'):
        return None
    return match


def main_title(value):
    value = re.split(r'\||｜|\s[−–]\s*PRODUCTS', str(value), maxsplit=1)[0]
    value = re.sub(r'^GOODS\s+', '', value, flags=re.I)
    return ' '.join(value.split()).strip()


def comparable(value):
    return ' '.join(re.findall(r'[a-z0-9]+', main_title(value).lower()))


def packaging(title):
    text = title.lower()
    if re.search(r'double\s+pack|devil\s+fruits?\s+collection|\btins?\b|mini\s+case\s+set|card\s+collection|playmat\s*(?:&|and)\s*card|gift\s+(?:box|collection|set)|anniversary\s+set|special\s+set', text):
        return 'SET'
    if re.search(r'sleeves?|play\s*mat|storage\s+box|deck\s+(?:box|case)|card\s+(?:case|binder)|\bbinder\b', text):
        return 'ACCESSORY'
    if re.search(r'(?:starter|ultimate)\s+deck|set\s+sail\s+deck|deck\s+set', text):
        return 'DECK'
    if re.search(r'booster\s+(?:box|display)|illustration\s+box', text):
        return 'BOX'
    if re.search(r'booster\s+pack|(?:premium\s+extra|extra|premium)\s+booster', text):
        return 'PACK'
    return 'UNKNOWN'


def product_identity(page):
    path = product_path(page.get('url', ''))
    title = main_title(page.get('title', ''))
    if not path or not 5 <= len(title) <= 180:
        return None
    if re.search(r'page not found|404|access denied|captcha|tournament\s+(?:entry|registration)|event\s+ticket', title, re.I):
        return None
    path_code = CODE_PATH.fullmatch(path[1])
    codes = {(m[1].upper(), int(m[2])) for m in TITLE_CODE.finditer(title)}
    wanted = (path_code[1].upper(), int(path_code[2])) if path_code else None
    if len(codes) > 1 or (wanted and codes and codes != {wanted}):
        return None
    form = packaging(title)
    if wanted and wanted[0] in BOOSTERS:
        # Codes in body text or related products do not identify this booster.
        if codes != {wanted} or form not in ('PACK', 'BOX'):
            return None
    else:
        # Codeless products need a matching main heading and product details.
        headings = page.get('headings', [])[:3] + page.get('detail_headings', [])[:3]
        if not any(comparable(h) == comparable(title) for h in headings):
            return None
        primary = main_text(page)
        if not re.search(r'\b(?:Contents|MSRP|Product Details|Product Name)\b', primary, re.I):
            return None
    # Do not invent a code from an image filename or URL (e.g. sleeve045).
    own_code = next(iter(codes)) if codes else None
    return {'title': title, 'product_format': form,
            'set_code': f'{own_code[0]}-{own_code[1]:02d}' if own_code else None}


def main_text(page):
    text = page.get('text', '')
    if not product_path(page.get('url', '')):
        return text
    title = main_title(page.get('title', ''))
    # Start at this product where possible; never borrow navigation dates.
    start = text.casefold().find(title.casefold())
    if start >= 0:
        text = text[start:]
    end = re.search(r'\bRELATED\b|What is\s+(?:a |an )?(?:Starter Deck|Booster Pack)', text, re.I)
    return text[:end.start()] if end else text
