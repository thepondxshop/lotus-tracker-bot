"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.3.3'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Case product alerts now share the case channel, including discoveries, restocks and price drops.',
    'Qualifying cases retain Below MSRP and Deal labels in the same channel.',
    'Sealed products become eligible for sold-market comparisons 30 days after their verified release date; MSRP comparisons remain active.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
