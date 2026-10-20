"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.6.1'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Shopify recovery alternates collection heads with deeper pages without increasing requests.',
    'Avoided duplicate general page-one fetches after a completed short catalog head.',
    'Retailer readiness now includes redacted error and disable reasons.',
)



def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
