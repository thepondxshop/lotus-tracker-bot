"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.3.2'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Any verified price below MSRP now qualifies for a Below MSRP alert; discounts of 10% or more add the Deal label.',
    'Below Market deals still require at least 10% below a verified sold-market reference.',
    'Added calculated case MSRP from reviewed unit prices and product-specific case quantities.',
    'Individual-card MSRP references are excluded; stock and identity checks remain required.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
