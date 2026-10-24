"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.14'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
# A nonempty list forces a major release, even if the manual kind is wrong.
# List only newly supported games (or an explicit catch-up announcement).
NEW_GAMES = ()
RELEASE_NOTES = (
    'Excluded franchise board games and dice games from distributor release ingestion and queued release-radar delivery.',
    'The same exclusion applies to member release calendars; genuine TCG products and dice accessories remain eligible.',
    'Shopify pacing and XP progression remain unchanged.',
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
