"""Listing confidence from recorded sources; separate from date/stock state."""
import json
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from .service import CatalogError, ReleaseSource, public_source_url, snapshot

LABELS = {'CONFIRMED': '✅ Confirmed listing', 'LEAKED': '🟠 Leak • unverified',
          'RUMORED': '⚠️ Rumored listing', 'ARCHIVED': 'Archived listing'}
URL = re.compile(r'https?://[^\s<>"\]\}]+')
MEDIA_KEYS = {'image', 'images', 'image_url', 'image_urls', 'attachments', 'supporting_url',
              'supporting_urls', 'evidence_url', 'evidence_urls'}


def valid_url(value):
    try:
        return public_source_url(value, required=True)
    except (CatalogError, TypeError, ValueError):
        return None


def structured(value):
    if isinstance(value, dict):
        return value
    try:
        out = json.loads(value or '{}')
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


def support_urls(value, primary=None):
    """Recorded material only; a link/image does not authenticate the claim."""
    found = set()
    def visit(node, explicit=False):
        if isinstance(node, dict):
            for key, val in node.items():
                visit(val, explicit or key.casefold() in MEDIA_KEYS)
        elif isinstance(node, list):
            for val in node:
                visit(val, explicit)
        elif isinstance(node, str) and explicit:
            for match in URL.findall(node):
                url = valid_url(match.rstrip('.,);'))
                if url and (explicit or url != primary):
                    found.add(url)
    parsed = structured(value)
    if parsed:
        visit(parsed)
    elif isinstance(value, str):
        for match in URL.findall(value):
            url = valid_url(match.rstrip('.,);'))
            if url and url != primary:
                found.add(url)
    return sorted(found)


def classify(row, sources):
    if row.get('status') == 'ARCHIVED':
        return {'state': 'ARCHIVED', 'label': LABELS['ARCHIVED'], 'reason': 'Archived record.'}
    authorities = []
    supporting = set()
    for source in sources:
        url = valid_url(source.get('url'))
        note = source.get('note', '')
        data = structured(note)
        kind = str(source.get('kind', '')).upper()
        # Game-wide launch evidence is not itself a listing of this product.
        if kind in ('DISTRIBUTOR', 'PUBLISHER') and url and data.get('match_scope') != 'GAME_LAUNCH':
            authorities.append(kind)
        if url and re.search(r'\.(?:png|jpe?g|webp|gif)(?:$)', urlsplit(url).path, re.I):
            supporting.add(url)
        supporting.update(support_urls(note, url))
    if authorities:
        kind = 'publisher' if 'PUBLISHER' in authorities else 'distributor'
        return {'state': 'CONFIRMED', 'label': LABELS['CONFIRMED'],
                'reason': f'Listed in recorded {kind} evidence. Dates, packaging and availability retain their own evidence.'}
    # Images/material may also have been retained in extraction details.
    primary_urls = {s.get('url') for s in sources}
    supporting.update(u for u in support_urls(row.get('reported_details', '')) if u not in primary_urls)
    if supporting:
        return {'state': 'LEAKED', 'label': LABELS['LEAKED'],
                'reason': 'Supporting material is recorded, but the claim is not confirmed by a distributor or publisher.'}
    return {'state': 'RUMORED', 'label': LABELS['RUMORED'],
            'reason': 'No distributor/publisher listing or supporting material is recorded.'}


async def attach(session, rows):
    data = [snapshot(row) if not isinstance(row, dict) else dict(row) for row in rows]
    ids = [row['id'] for row in data]
    groups = {}
    if ids:
        sources = (await session.scalars(select(ReleaseSource).where(ReleaseSource.release_id.in_(ids)))).all()
        for source in sources:
            groups.setdefault(source.release_id, []).append(snapshot(source))
    for row in data:
        row['listing_confidence'] = classify(row, groups.get(row['id'], []))
    return data


def confidence(row):
    if row.get('listing_confidence'):
        return row['listing_confidence']
    if row.get('status') == 'CONFIRMED':
        return {'state': 'CONFIRMED', 'label': LABELS['CONFIRMED'], 'reason': 'Catalog confirmation is recorded.'}
    return classify(row, [])
