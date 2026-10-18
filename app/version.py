"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.4.0'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Public ACD, GTS and PHD MSRP and release-date evidence now refreshes into persistent storage.',
    'Exact retailer matches feed the existing strict MSRP/30-day market policy; ambiguous packaging and conflicting prices remain blocked.',
    'Expanded eBay search coverage and added narrow multi-field matching for GTIN-less English 151 bundles.',
    'New distributor coverage and eBay price diagnostics show remaining data gaps; live activation gates remain in place.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
