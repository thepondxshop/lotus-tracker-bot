"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.2.2'
RELEASE_KIND = 'patch'  # patch, regular, major
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'eBay identity checks now read explicit UPC/EAN/GTIN item specifics as well as the main GTIN field.',
    'Diagnostics distinguish missing, invalid, conflicting and mismatched product identifiers.',
    'Product, seller and deal checks remain enforced; the revised policy requires fresh shadow validation.',
    'Automatic sold-data retrieval remains unavailable.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
