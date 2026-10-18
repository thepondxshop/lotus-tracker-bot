"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.3.4'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Corrected sealed pricing: MSRP applies only before release plus 30 days; thereafter only verified market deals qualify.',
    'No MSRP fallback after the cutoff when market evidence is unavailable.',
    'Added explicit reference-window diagnostics and public distributor MSRP extraction checks.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
