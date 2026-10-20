"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.0'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Corrected accessory case routing, stationery exclusions and graded Pikachu identity.',
    'Added exact-mapped Pokemon public market references with source freshness checks.',
    'Added public-source diagnostics; source availability does not imply live stock coverage.',
)




def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
