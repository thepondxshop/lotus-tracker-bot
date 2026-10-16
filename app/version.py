"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.2.0'
RELEASE_KIND = 'regular'  # patch, regular, major
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Added an eBay pilot setup tool and reviewed sold-record CSV importer.',
    'Added item-only deal comparisons with shipping and taxes shown separately.',
    'Added shadow diagnostics and reviewed-configuration gates for fixed-price and auction delivery.',
    'Live alerts require qualifying sales evidence and successful shadow checks; automatic sold-data collection is not enabled.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
