"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.3.1'
RELEASE_KIND = 'patch'  # patch, regular, major
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'eBay no longer treats zero or omitted lot size as automatic evidence of a multi-item lot.',
    'Added multi-box title and 151 pack-count checks; identity and other eligibility checks remain required.',
    'Listing review diagnostics now show identity, lot, packaging and price comparison separately.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
