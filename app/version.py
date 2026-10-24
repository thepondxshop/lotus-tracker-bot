"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.12'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Reaching each tenth level costs 50% extra for that level-up only.',
    'Members now start at level 0; level 1 needs 100 XP, then each next level costs 100 XP more.',
    'Existing XP totals preserved; random 10–20 XP awards and no daily cap remain unchanged.',
    'Cosmetic XP reward settings support levels through 300; no maximum earning level is imposed.',
)



def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
