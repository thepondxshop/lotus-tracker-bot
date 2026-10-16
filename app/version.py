"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.2.1'
RELEASE_KIND = 'patch'  # patch, regular, major
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Added reviewed aggregate sold-price snapshots to the eBay pilot.',
    'Weighted comparisons preserve units sold, reporting window and evidence expiration.',
    'Aggregate and individual-sale evidence are kept separate to prevent double counting.',
    'Automatic sold-data retrieval remains unavailable; live alerts still require shadow review.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
