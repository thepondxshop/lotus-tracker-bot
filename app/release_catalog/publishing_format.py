"""Public release-lead rendering; never assert stock from a release source."""
import discord
from .service import CatalogError, public_source_url


def safe(value, limit=800):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value or 'Unknown')))[:limit]


def source_link(value):
    try:
        value = public_source_url(value, required=True)
        return '<' + value + '>' if len(value) < 500 else 'Source link available in catalog.'
    except CatalogError:
        return 'Source URL unavailable.'


def notice_embed(n):
    p = n['payload']; facts = p['facts']; review = n['review_state']
    listing = p.get('listing_confidence') or {'state': 'RUMORED', 'label': '⚠️ Rumored listing', 'reason': 'Source confidence has not been evaluated.'}
    if facts['status'] == 'ARCHIVED':
        heading, colour = '⚫ Release lead archived', 0x747F8D
    elif review == 'INCORRECT':
        heading, colour = '❌ Release alert disputed by admin', 0xE74C3C
    elif review == 'CORRECTED':
        heading, colour = '✏️ Release information corrected', 0x3498DB
    elif listing['state'] == 'CONFIRMED':
        heading, colour = '✅ Confirmed listing', 0x2ECC71
    elif listing['state'] == 'LEAKED':
        heading, colour = '🟠 Leak • unverified', 0xE67E22
    else:
        heading, colour = '⚠️ Rumored listing • details unverified', 0xF1C40F
    e = discord.Embed(title=heading, description='**' + safe(facts['title'], 220) + '**', colour=colour)
    e.add_field(name='Product', value=safe(f"{facts['game']} • {facts['product_format']}\n{facts['region']} / {facts['language']}", 230), inline=False)
    e.add_field(name='Listing confidence', value=safe(listing['label']+'\n'+listing['reason'], 300), inline=False)
    when = facts.get('reported_date')
    if when and str(when).upper() != 'UNKNOWN':
        label = {'ADMIN_REPORT': 'Admin-reported date • not publisher verification',
                 'SOURCE_REPORT': 'Source-reported date • unconfirmed'}.get(facts.get('date_origin'),
                 'Catalog date' if facts['status'] == 'CONFIRMED' else 'Reported date • unconfirmed')
        e.add_field(name=label, value=safe(when, 60), inline=False)
    else:
        e.add_field(name='Exact product release date', value='Not confirmed.', inline=False)
    if p['windows']:
        lines = []
        for w in p['windows'][:3]:
            lines.append(safe(f"{w['label']} • {w['precision']} • {w['scope']}", 180)
                + (' • evidence needs refresh' if w['stale'] else '') + '\n' + source_link(w['url']))
        e.add_field(name='Publisher release windows', value='\n'.join(lines)[:950], inline=False)
    if p['flags']:
        e.add_field(name='Details to verify', value='\n'.join('• ' + safe(x, 130) for x in p['flags'][:6])[:900], inline=False)
    sources = [safe(x['kind'] + ' • ' + x['label'], 120) + '\n' + source_link(x['url']) for x in p['sources'][:3]]
    e.add_field(name='Sources', value='\n'.join(sources)[:1000] or 'Original source not supplied.', inline=False)
    review_labels = {'PENDING': 'Not yet reviewed', 'CONFIRMED': '✅ Admin reviewed the displayed information',
        'CORRECTED': '✏️ Admin correction saved', 'INCORRECT': '❌ Marked incorrect; do not rely on this alert',
        'UNKNOWN': '⚠️ Reviewed; correct information is still unknown'}
    text = review_labels.get(review, 'Not yet reviewed')
    if n.get('review_note'):
        text += '\n' + safe(n['review_note'], 600)
    if p.get('admin_fields'):
        text += '\nSaved admin corrections: ' + safe(', '.join(p['admin_fields']), 180)
    e.add_field(name='Admin review', value=text[:1000], inline=False)
    e.add_field(name='Availability', value='Release/source discovery only. This is not a stock or purchasable-preorder confirmation.', inline=False)
    ref = f"Release #{n['release_id']}" if n.get('release_id') else 'Unmatched source lead'
    e.set_footer(text=f"Lotus Release Radar 1.6.5 • Alert #{n['id']} • {ref}")
    return e


def audience_event(n):
    f = n['payload']['facts']
    region = f.get('region')
    language = str(f.get('language') or '').casefold()
    category = 'ACCESSORY' if f['product_format'] == 'ACCESSORY' else ('UNKNOWN' if f['product_format'] == 'UNKNOWN' else 'SEALED')
    family = {'japanese': 'JP', 'korean': 'KR', 'chinese': 'CN', 'english': 'GLOBAL_STANDARD'}.get(language, 'UNKNOWN')
    return {'event_type': 'RELEASE_RADAR', 'game': f['game'], 'product_name': f['title'],
            'product_category': category, 'product_family': family,
            'region': '' if str(region).upper() == 'UNKNOWN' else region}
