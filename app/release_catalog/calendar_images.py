"""Resolve retained product artwork without HTTP or changing release facts."""
import json
import re
from pathlib import Path
from .service import CatalogError, public_source_url
from .publisher_artwork import unsuitable, HEROINES_PAGE, HEROINES_IMAGE
from .calendar_identity import product_key, edition

ASSETS = Path(__file__).parent / 'assets' / 'calendar'
JP_ASSETS = {'heroines-precious-box-jp.png', 'heroines-playmat-jp.png'}
BUNDLED = {
    ('EB05', 'PACK'): ('eb05-en-pack.png', 'OFFICIAL'),
    ('EB05', 'BOX'): ('eb05-en-box.png', 'OFFICIAL'),
    ('OP18', 'PACK'): ('op18-en-pack.webp', 'OFFICIAL'),
    ('OP18', 'BOX'): ('op18-en-box.webp', 'OFFICIAL'),
    ('OP19', 'BOX'): ('op19-en-box-mockup.webp', 'MOCKUP'),
}


def details(value):
    if isinstance(value, dict): return value
    try:
        return json.JSONDecoder().raw_decode(value[value.index('{'):])[0] if isinstance(value, str) else {}
    except (ValueError, TypeError): return {}


def valid_url(value):
    try: return public_source_url(value, required=True) if isinstance(value, str) else None
    except (CatalogError, TypeError, ValueError): return None


def image_urls(data):
    if not isinstance(data, dict): return []
    result = []
    def add(value):
        if isinstance(value, list):
            for item in value[:8]: add(item)
        elif isinstance(value, dict): add(value.get('url') or value.get('contentUrl'))
        else:
            url = valid_url(value)
            if url and not unsuitable(url) and url not in result: result.append(url)
    for key in ('image_url', 'image_urls', 'image', 'images'): add(data.get(key))
    return result


def bundled(row):
    if str(row.get('game', '')).casefold().replace(' ', '') != 'onepiece': return None
    language = str(row.get('language') or 'UNKNOWN').casefold()
    region = str(row.get('region') or 'UNKNOWN').casefold()
    title = re.sub(r'[^a-z0-9]+', ' ', str(row.get('title', '')).casefold()).strip()
    form = str(row.get('product_format') or '').upper()
    # Exact Japanese edition/product matching. Never attach these to the English gift set.
    if region in ('jp', 'japan') and language in ('ja', 'jp', 'japanese'):
        name = None
        if title in ('one piece heroines precious box japanese', 'one piece heroines precious box',
                     'heroines precious box') and form == 'SET':
            name = 'heroines-precious-box-jp.png'
        if title in ('official playmat nami robin with nico robin p 111 promo',
                     'official playmat nami robin') and form == 'ACCESSORY':
            name = 'heroines-playmat-jp.png'
        if name and (ASSETS / name).is_file():
            return {'image_url':'attachment://' + name, 'image_asset':name,
                    'image_kind':'OFFICIAL', 'image_label':'Japanese product artwork • supplied and confirmed by admin'}

    region = str(row.get('region') or 'UNKNOWN').casefold()
    if language not in ('unknown', 'en', 'eng', 'english', ''): return None
    if region in ('jp', 'japan', 'kr', 'korea', 'cn', 'china'): return None
    # Reject ambiguous titles; never assign pack art to a case/box or vice versa.
    codes = {f'{m[0]}{int(m[1]):02d}' for m in re.findall(
        r'\b(EB|OP)[ -]?(\d{1,3})\b', str(row.get('title', '')).upper())}
    explicit = re.fullmatch(r'(EB|OP)[ -]?(\d{1,3})', str(row.get('set_code') or '').upper())
    if explicit: codes.add(f'{explicit[1]}{int(explicit[2]):02d}')
    if len(codes) != 1: return None
    item = BUNDLED.get((next(iter(codes)), str(row.get('product_format', '')).upper()))
    if not item or not (ASSETS / item[0]).is_file(): return None
    name, kind = item
    label = 'Official English artwork • provided by admin' if kind == 'OFFICIAL' else 'Mockup — final artwork pending; not official packaging'
    if language in ('', 'unknown'): label += ' • Catalog language unverified'
    return {'image_url': 'attachment://' + name, 'image_asset': name,
            'image_kind': kind, 'image_label': label}


def remote(url, label, kind='SOURCE'):
    if re.search(r'\[temp\]|placeholder|mockup', url, re.I):
        label, kind = 'Source placeholder — final artwork pending', 'PLACEHOLDER'
    return {'image_url': url, 'image_asset': None, 'image_kind': kind, 'image_label': label}


def resolve_image(row, sources, check=None, override=None):
    url = valid_url(override)
    if url: return remote(url, 'Admin-selected product image')
    bundle = bundled(row)
    if bundle and bundle['image_kind'] == 'OFFICIAL': return bundle
    # Repair the cached Bandai social banner without changing any release facts.
    # This is exact-product and English-page scoped, never inferred from a date.
    evidence_rows = (check or {}).get('evidence', [])
    page_urls = [s.get('url') for s in sources if s.get('kind') == 'PUBLISHER']
    page_urls += [e.get('url') for e in evidence_rows if e.get('match_scope') == 'PRODUCT']
    repair_heroines = (product_key(row) == 'one-piece-gc2026-heroines'
        and edition(row.get('language')) in ('', 'english')
        and edition(row.get('region')) not in ('japanese', 'kr', 'korea', 'cn', 'china')
        and HEROINES_PAGE in page_urls)
    for evidence in (check or {}).get('evidence', []):
        if evidence.get('match_scope') == 'PRODUCT':
            urls = image_urls(evidence)
            if urls: return remote(urls[0], 'Publisher product-page image', 'PUBLISHER')
    if repair_heroines:
        return remote(HEROINES_IMAGE, 'Official Bandai product packaging • verified 2026-10-02', 'PUBLISHER')
    # Linked sources retain newer images even when the original report is old.
    ordered = sorted(enumerate(sources), key=lambda pair:
                     (pair[1].get('kind') == 'PUBLISHER', pair[0]), reverse=True)
    fallback = None
    for _, source in ordered:
        data = details(source.get('note'))
        if not isinstance(data, dict) or data.get('match_scope') == 'GAME_LAUNCH': continue
        urls = image_urls(data)
        if urls:
            art = remote(urls[0], f"{str(source.get('kind') or 'Source').title()}-supplied product image")
            if art['image_kind'] != 'PLACEHOLDER': return art
            fallback = fallback or art
    for url in image_urls(details(row.get('reported_details'))):
        art = remote(url, 'Source-supplied product image')
        if art['image_kind'] != 'PLACEHOLDER': return art
        fallback = fallback or art
    if bundle: return bundle
    if fallback: return fallback
    return {'image_url': None, 'image_asset': None, 'image_kind': 'PLACEHOLDER',
            'image_label': 'Illustrative placeholder — product artwork pending'}


def asset_path(name):
    # Only deployed manifest assets may be opened, never a source-supplied path.
    if name not in ({item[0] for item in BUNDLED.values()} | JP_ASSETS): return None
    path = ASSETS / name
    return path if path.is_file() else None
