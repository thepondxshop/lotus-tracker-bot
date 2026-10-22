"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.3'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Official Riot/Riftbound announcement monitoring, with drawing notices kept separate from stock alerts.',
    'Riot Merch public category page/price adapter added behind validation and promotion gates.',
    'Member XP opt-out, progress erasure and opt-in controls.',
    'Includes the prior launch batch; retailer access and marketplace live gates remain enforced.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
