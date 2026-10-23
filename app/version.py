"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.4'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Fixed Fusion World release-event singles incorrectly labeled and routed as accessories.',
    'Playmat/card sets and products explicitly including bonus or promo cards stay in their game channels.',
    'Accessory routing retains sleeves, playmats, deck boxes and protective cases sold without cards.',
    'Release-day default-on preferences were delivered in the preceding patch; saved opt-outs remain respected.',
)

def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
