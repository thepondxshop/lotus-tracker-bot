"""Conservative calendar projection for reviewed cross-source product aliases.

Catalog rows and their evidence are retained. Unknown editions are grouped only
when all candidates have one unambiguous compatible edition and date.
"""
import re
import unicodedata


def words(value):
    return ' '.join(re.findall(r'[a-z0-9]+', unicodedata.normalize('NFKC', str(value or '')).casefold()))


def product_key(row):
    game, title = words(row.get('game')), words(row.get('title'))
    form = str(row.get('product_format') or 'UNKNOWN').upper()
    if form not in ('UNKNOWN', 'SET', 'BOX'): return None
    # Exact reviewed names only: never collapse cases/displays, bundles, or
    # different language editions merely because they mention the same set.
    if game == 'azuki tcg':
        titles = {'azuki tcg fractured domains relic hunter box',
                  'azuki tcg fractured domains azk 02 relic hunter box'}
        if title in titles and words(row.get('set_code')) in ('', 'azk 02', 'azk02'):
            return 'azuki-azk02-relic-hunter-box'
    if game == 'one piece':
        titles = {'one piece tcg gift collection heroines',
                  'gift collection one piece heroines gc 2026'}
        if title in titles and words(row.get('set_code')) in ('', 'gc 2026', 'gc2026'):
            return 'one-piece-gc2026-heroines'
    return None


def edition(value):
    v = words(value)
    return {'unknown': '', 'en': 'english', 'eng': 'english',
            'us': 'usa', 'united states': 'usa', 'jp': 'japanese',
            'japan': 'japanese'}.get(v, v)


def consolidate(entries):
    buckets, result = {}, []
    for entry in entries:
        key = product_key(entry)
        if not key or not entry.get('period'):
            result.append(entry); continue
        buckets.setdefault((entry.get('guild_id'), key), []).append(entry)
    for group in buckets.values():
        # Conflicting known editions or periods are deliberately left separate.
        scopes = [{edition(e.get(k)) for e in group} - {''} for k in ('region', 'language')]
        periods = {(e['period'].get('start'), e['period'].get('end'),
                    e['period'].get('precision'), e['period'].get('anchor'),
                    e['period'].get('tba'), e['period'].get('scope', 'PRODUCT')) for e in group}
        if len(group) < 2 or any(len(s) > 1 for s in scopes) or len(periods) != 1:
            result.extend(group); continue
        # Keep an eligible record as the representative so merging does not
        # promote a rumor or discard a valid announcement. Otherwise prefer
        # publisher presentation and stable ID; artwork is selected separately.
        chosen = min(group, key=lambda e: (not e.get('announceable'),
                     not str(e.get('date_origin', '')).startswith('Publisher'), e['id']))
        merged = dict(chosen)
        merged['calendar_members'] = [{'id': e['id'], 'announceable': e.get('announceable'),
                                      'release_date': e.get('release_date')} for e in group]
        merged['calendar_source_urls'] = sorted({e['source_url'] for e in group if e.get('source_url')})
        usable = [e for e in group if e.get('image_url') and e.get('image_kind') not in ('PLACEHOLDER', 'MOCKUP')]
        if usable:
            art = min(usable, key=lambda e: (e.get('image_kind') not in ('OFFICIAL', 'PUBLISHER'), e['id']))
            for k in ('image_url', 'image_asset', 'image_kind', 'image_label'): merged[k] = art.get(k)
        merged['notes'] = list(dict.fromkeys([*chosen.get('notes', []),
            'Combined calendar listings: ' + ', '.join('#' + str(e['id']) for e in sorted(group, key=lambda e: e['id'])) + '. Source records retained.']))
        result.append(merged)
    return sorted(result, key=lambda e: e['id'])
