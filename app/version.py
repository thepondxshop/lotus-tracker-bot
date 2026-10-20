"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.5.0'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Expanded distributor packaging checks and corrected coverage reporting.',
    'Recognizes the reported Dragon Ball Card Game FB01 listing as Fusion World.',
    'Added consolidated marketplace launch checks and saved eBay cycle diagnostics.',
    'Added read-only TCGplayer API and Cardmarket price-guide previews.',
    'Added reviewed sold-data imports for five marketplaces; automatic feeds remain separate.',
)


def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
