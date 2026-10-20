"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.6.0'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Premium Bandai public US card catalog connected for page and price monitoring; stock remains unverified.',
    'Added optional public product-page watchlists for major retailers without partner credentials.',
    'Expanded eBay game discovery and reviewed-target capacity; improved detail rotation within the request budget.',
    'Increased cross-store Shopify scan capacity while preserving domain cooldowns.',
)



def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
