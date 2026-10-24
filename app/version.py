"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.16'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
# A nonempty list forces a major release, even if the manual kind is wrong.
# List only newly supported games (or an explicit catch-up announcement).
NEW_GAMES = ()
RELEASE_NOTES = (
    'Added opt-in eBay fixed-price listing alerts, separate from benchmark-backed deal alerts.',
    'Listing alerts retain product, seller, packaging, availability, channel-access and durable deduplication checks.',
    'Added separate listing shadow validation and configuration approval; Shopify and XP are unchanged.',
)



def release_kind():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    return 'major' if NEW_GAMES else RELEASE_KIND



def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    kind = release_kind()
    prefix = '@everyone\n' if kind == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {kind.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
