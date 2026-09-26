"""US English Pokemon product-gallery identity; never retailer availability."""
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

INDEX = 'https://www.pokemon.com/us/pokemon-tcg/product-gallery'
ROOT = '/us/pokemon-tcg/product-gallery'


def norm(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).casefold().split())


def title(value):
    return ' '.join(re.split(r'\||｜', str(value), maxsplit=1)[0].split()).strip()


def comparable(value):
    normalized = re.sub(r'(?<=[a-z0-9])(?=pokemon\s+(?:tcg|trading card game))', ' ', norm(title(value)))
    return ' '.join(re.findall(r'[a-z0-9]+', normalized))


def _path(url):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname not in ('www.pokemon.com', 'pokemon.com') or p.port not in (None, 443) or p.username or p.password:
            return None
        return p
    except (ValueError, TypeError):
        return None


def product_url(url):
    p = _path(url)
    if not p:
        return None
    match = re.fullmatch(re.escape(ROOT) + r'/([a-z0-9][a-z0-9-]*)/?', p.path, re.I)
    if not match or match[1].isdigit() or match[1].lower() in ('index', 'all', 'search'):
        return None
    return INDEX + '/' + match[1].lower()


def index_url(url):
    p = _path(url)
    if not p:
        return None
    match = re.fullmatch(re.escape(ROOT) + r'(?:/(20\d{2}))?/?', p.path)
    if not match:
        return None
    # Old-year archives are not a source of new product announcements.
    year = datetime.now(timezone.utc).year
    if match[1] and int(match[1]) not in (year, year + 1):
        return None
    page = parse_qs(p.query).get('page', ['1'])[0]
    if not page.isdigit() or not 1 <= int(page) <= 100:
        return None
    path = ROOT + ('/' + match[1] if match[1] else '')
    return urlunsplit(('https', 'www.pokemon.com', path, urlencode({'page': int(page)}) if int(page) > 1 else '', ''))


def packaging(value):
    text = norm(value)
    if re.search(r'elite trainer box|build\s*(?:&|and)\s*battle|booster (?:box|display)', text):
        return 'BOX'
    if re.search(r'collection|collector chest|booster bundles?|\btins?\b|toolkit|tool kit|gift set|battle academy', text):
        return 'SET'
    if re.search(r'\b(?:deck box|deck case|sleeves?|playmat|binder|portfolio)\b', text):
        return 'ACCESSORY'
    if re.search(r'\b(?:battle|theme|starter|trainer|championships?)\b.*\bdecks?\b', text):
        return 'DECK'
    if re.search(r'\bbox\b', text):
        return 'BOX'
    if re.search(r'booster pack|sleeved booster|blister', text):
        return 'PACK'
    return 'UNKNOWN'


def main_text(page):
    text = page.get('text', '')
    if not product_url(page.get('url', '')):
        return text
    wanted = comparable(page.get('title', ''))
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if comparable(line) == wanted:
            text = '\n'.join(lines[index:])
            break
    end = re.search(r'\bReturn to Gallery\b|\bRelated Products\b|\bYou May Also Like\b|\bRecommended Products\b', text, re.I)
    return text[:end.start()] if end else text


def date_text(page):
    # Gallery pages label their own date "Launch:". Incidental dates in prose,
    # preorder windows and related cards do not become this product's date.
    from .official_parser import DATE_RE
    text = main_text(page)
    dates = []
    for marker in re.finditer(r'\bLaunch[ \t]*:[ \t]*(?:\n[ \t]*)?', text, re.I):
        match = DATE_RE.match(text, marker.end())
        if match:
            dates.append('Launch: ' + match.group())
    return '\n'.join(dates)


def rejection_reason(page):
    """Explain a rejected page without weakening product identity checks."""
    url = product_url(page.get('url', ''))
    name = title(page.get('title', ''))
    if not url:
        return 'UNSUPPORTED_PRODUCT_URL'
    if not 5 <= len(name) <= 180:
        return 'TITLE_LENGTH_OUT_OF_RANGE'
    normalized = norm(name)
    has_brand = re.search(r'\bpokemon\s+(?:tcg|trading card game)\b', normalized)
    if not has_brand and (packaging(name) == 'UNKNOWN' or not re.search(r'pokemon\s+(?:tcg|trading card game)', norm(main_text(page)))):
        return 'TCG_IDENTITY_MISSING'
    if re.search(r'access denied|captcha|page not found|404|tcg (?:live|pocket)|registration|event ticket', normalized):
        return 'NOT_A_PHYSICAL_PRODUCT_OR_ERROR_PAGE'
    if not any(comparable(h) == comparable(name) for h in page.get('headings', [])[:3]):
        return 'TITLE_HEADING_MISMATCH'
    body = main_text(page)
    if not re.search(r'\bLaunch\s*:|\bincludes?\b|\bcontains?\b|\bMSRP\b', body, re.I):
        return 'PRODUCT_DETAILS_MISSING'
    return None


def product_identity(page):
    if rejection_reason(page):
        return None
    url = product_url(page.get('url', ''))
    name = title(page.get('title', ''))
    normalized = norm(name)
    # Keep a publisher's combined page intact; do not invent individual SKUs
    # or imply that alternative products are sold as a single bundle.
    group = (len(re.findall(r'pokemon\s+(?:tcg|trading card game)', normalized)) > 1
             or bool(re.search(r'\b(?:decks|bundles|tins|collections)\b', normalized))
             or (len(re.findall(r'battle deck|elite trainer box|collection', normalized)) > 1
                 and bool(re.search(r'\band\b|&|/', normalized))))
    return {'url': url, 'title': name, 'game': 'Pokemon', 'language': 'English',
            'region': 'US', 'product_format': 'UNKNOWN' if group else packaging(name),
            'set_code': None, 'publisher_scope': 'PRODUCT_GROUP' if group else 'PRODUCT'}
