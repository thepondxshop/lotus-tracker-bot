"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.4.3'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Successful Shopify collection requests no longer clear a blocked general-catalog endpoint.',
    'General-catalog recovery uses a separate 15/30/60-minute probe schedule while collection polling continues.',
    'Dragon Ball Super TCG: Fusion World titles now map to the existing Fusion World game.',
)


def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
