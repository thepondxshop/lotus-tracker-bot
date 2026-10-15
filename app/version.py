"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.1.0'
RELEASE_KIND = 'regular'  # patch, regular, major
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Added Final Fantasy TCG and CookieRun: Braverse game preferences and recognition.',
    'Corrected classification of MTG scene-box sets and commander-deck sets.',
    'Added diagnostic explanations for price-drop versus deal routing.',
    'Added versioned release announcements with duplicate-send protection.',
)
def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
