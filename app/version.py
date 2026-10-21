"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.2'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Optional community XP, rank and leaderboard commands with activity limits.',
    'Approved exact-product affiliate links with expiry and disclosure.',
    'Reviewed eBay target searches rotate pages with bounded request settings.',
    'Major retailer access-failure cooldowns and deployment integrity checks.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
