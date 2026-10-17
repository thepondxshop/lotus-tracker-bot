"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.3.0'
RELEASE_KIND = 'regular'  # patch, regular, major
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Retailer deals support reviewed MSRP and sold-market comparisons without requiring a prior price drop.',
    'Reviewed Shopify products are checked for current-price deals on each observation.',
    'eBay supports expiring review of individual listings that omit GTINs; other eligibility checks still apply.',
    'Registered TCGplayer for Premium and Cardmarket for Premium+; their live adapters are not enabled.',
    'Automatic sold-data retrieval and distributor reference ingestion still require connected evidence sources.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
