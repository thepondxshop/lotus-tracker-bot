"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.13'
RELEASE_KIND = 'major'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
# A nonempty list forces a major release, even if the manual kind is wrong.
# List only newly supported games (or an explicit catch-up announcement).
NEW_GAMES = ('World of Tanks TCG', 'Vibes TCG', 'Shadowverse Evolve',
             'Beyblade X TCG — Blader League')
RELEASE_NOTES = (
    'New-game support catch-up: World of Tanks TCG, Vibes TCG, Shadowverse Evolve and Beyblade X TCG — Blader League.',
    'Their game-role options are registered. Beyblade X is announced for 2027; an exact release date is not set.',
    'New game support does not guarantee product availability or complete source coverage.',
    'Next priority: get marketplaces and major retailers operational while preserving the recovered Shopify pacing baseline.',
    'Marketplace and retailer access, price-reference freshness and live delivery still require verification.',
)


def release_kind():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    return 'major' if NEW_GAMES else RELEASE_KIND



def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    kind = release_kind()
    prefix = '@everyone\n' if kind == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {kind.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
