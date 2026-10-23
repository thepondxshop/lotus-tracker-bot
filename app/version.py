"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.5'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Fixed eBay detail rotation so each search page retains its own position.',
    'Added eBay page, cache-age and completed-detail diagnostics.',
    'Added an exported-log report for delivery timing, Shopify responses and access blockers.',
    'Updated the launch milestone ledger; unverified feeds and retailer access remain explicitly pending.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
