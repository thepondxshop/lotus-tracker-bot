"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.6'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Added source-checked Riot drawing schedule reminders with persistent duplicate prevention.',
    'Added saved XP channel setup, audited XP corrections and cosmetic level-role rewards.',
    'Fixed XP opt-out access while XP awarding is disabled.',
    'Added a consolidated launch audit and updated the milestone checkpoint.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
