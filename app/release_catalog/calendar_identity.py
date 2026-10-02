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
    # Normalize distributor packaging vocabulary, not fuzzy product names.
    # A booster pack display is one booster box. Cases and multipacks remain
    # different products; region/language/date/configuration are checked below.
    if game == 'azuki tcg':
        normalized = re.sub(r'^azuki\s+(?:tcg\s+)?', '', title)
        normalized = re.sub(r'\bseries\s*0?2\b|\bazk\s*0?2\b', ' ', normalized)
        normalized = re.sub(r'\b24\s*(?:ct|count)\b', ' ', normalized)
        normalized = re.sub(r'\bbooster\s+(?:pack\s+)?display\b', 'booster box', normalized)
        normalized = ' '.join(normalized.split())
        if words(row.get('set_code')) in ('', 'azk 2', 'azk 02', 'azk2', 'azk02'):
            if normalized == 'fractured domains relic hunter box':
                return 'azuki-azk02-relic-hunter-box'
            if normalized == 'fractured domains booster box':
                return 'azuki-azk02-booster-box'
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
            'japan': 'japanese', 'ja': 'japanese', 'jpn': 'japanese',
            'zh cn': 'simplified chinese', 'zh hans': 'simplified chinese',
            'zh tw': 'traditional chinese', 'zh hant': 'traditional chinese'}.get(v, v)


def scoped_edition(row, field):
    """An unknown field must not hide an explicit edition in the product title."""
    value = edition(row.get(field))
    if value or field != 'language': return value
    title = words(row.get('title'))
    for label in ('simplified chinese', 'traditional chinese', 'japanese', 'chinese', 'english', 'korean'):
        if re.search(r'\b' + label + r'\b', title): return label
    return ''


def configurations(row):
    packs = row.get('reported_packs_per_box')
    if product_key(row) == 'azuki-azk02-booster-box':
        match = re.search(r'\b(\d+)\s*(?:ct|count)\b', words(row.get('title')))
        if match: return str(int(match[1]))
    return str(packs) if packs is not None else ''


def artwork_rank(entry):
    usable = bool(entry.get('image_url') and entry.get('image_kind') not in ('PLACEHOLDER', 'MOCKUP'))
    return (not usable, entry.get('image_kind') not in ('OFFICIAL', 'PUBLISHER'),
            not str(entry.get('date_origin', '')).startswith('Publisher'), entry['id'])


def consolidate(entries):
    buckets, result = {}, []
    for entry in entries:
        key = product_key(entry)
        if not key or not entry.get('period'):
            result.append(entry); continue
        buckets.setdefault((entry.get('guild_id'), key), []).append(entry)
    for group in buckets.values():
        # Conflicting known editions or periods are deliberately left separate.
        scopes = [{scoped_edition(e, k) for e in group} - {''} for k in ('region', 'language')]
        scopes.append({configurations(e) for e in group} - {''})
        periods = {(e['period'].get('start'), e['period'].get('end'),
                    e['period'].get('precision'), e['period'].get('anchor'),
                    e['period'].get('tba'), e['period'].get('scope', 'PRODUCT')) for e in group}
        if len(group) < 2 or any(len(s) > 1 for s in scopes) or len(periods) != 1:
            result.extend(group); continue
        # Keep an eligible record as the representative so merging does not
        # promote a rumor or discard a valid announcement. Otherwise prefer
        # publisher presentation and stable ID; artwork is selected separately.
        chosen = min(group, key=lambda e: (not e.get('announceable'), *artwork_rank(e)))
        merged = dict(chosen)
        display = min(group, key=artwork_rank)
        # Use the publisher's illustrated product name even when an older,
        # explicitly confirmed row supplies the announcement eligibility.
        merged['title'] = display['title']
        merged['product_format'] = display['product_format']
        merged['calendar_members'] = [{'id': e['id'], 'announceable': e.get('announceable'),
                                      'release_date': e.get('release_date')} for e in group]
        merged['calendar_source_urls'] = sorted({e['source_url'] for e in group if e.get('source_url')})
        usable = [e for e in group if e.get('image_url') and e.get('image_kind') not in ('PLACEHOLDER', 'MOCKUP')]
        if usable:
            art = min(usable, key=artwork_rank)
            for k in ('image_url', 'image_asset', 'image_kind', 'image_label'): merged[k] = art.get(k)
        merged['notes'] = list(dict.fromkeys([*chosen.get('notes', []),
            'Combined calendar listings: ' + ', '.join('#' + str(e['id']) for e in sorted(group, key=lambda e: e['id'])) + '. Source records retained.']))
        result.append(merged)
    return sorted(result, key=lambda e: e['id'])
