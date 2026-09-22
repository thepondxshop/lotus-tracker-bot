"""Exclude event admission, not tournament-branded cards or sealed products."""
import re
import unicodedata
from urllib.parse import urlsplit, unquote

VERSION = '1.0.0'


def normalized(value):
    return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', str(value or '')).encode('ascii','ignore').decode().lower()).strip()


def is_event_listing(title='', product_type='', url=''):
    kind = normalized(product_type)
    if kind in {'event','events','tournament','tournaments','event ticket','event tickets',
                'tournament entry','tournament registration','event registration','admission'}:
        return True
    try:
        path = unquote(urlsplit(str(url or '')).path)
    except ValueError:
        path = str(url or '')
    text = normalized(str(title or '') + ' ' + path)
    if not text:
        return False
    # Explicit admission wording remains decisive even if entry includes a pack.
    if re.search(r'\b(?:tournament|event|league|prerelease|pre release) (?:registration|entry|admission|ticket|tickets|sign up)\b',text):
        return True
    if re.search(r'\b(?:register for|entry to|entry fee|admission to)\b',text):
        return True
    # These terms describe real merchandise; do not suppress tournament packs,
    # World Championship decks, winner promos, or cards called Event/League.
    merchandise = bool(re.search(r'\b(?:pack|packs|booster|box|display|deck|decks|sleeve|sleeves|playmat|collection|promo|promotional|winner|foil|card|cards)\b',text))
    event_context = bool(re.search(r'\b(?:tournament|tournaments|locals|meet up|meetup|league|prerelease|pre release)\b',text))
    if event_context and re.search(r'\b(?:\d+ seats?|\d{1,2} \d{2} (?:am|pm)|\d{1,2} (?:am|pm))\b',text):
        return True
    if event_context and not merchandise and re.search(r'\b(?:20\d{2} \d{1,2} \d{1,2}|\d{1,2} \d{1,2} 20\d{2})\b',text):
        return True
    return event_context and not merchandise and bool(re.search(r'\b(?:tournament|tournaments|locals|meet up|meetup)\b',text))


def raw_event_listing(product):
    return is_event_listing(product.get('title') or product.get('name'),
                            product.get('product_type') or product.get('type'),
                            product.get('handle') or product.get('url'))
