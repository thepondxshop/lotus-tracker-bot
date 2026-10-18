"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.4.2'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Shopify recovery excludes comic-only and tabletop-only collections and prioritizes explicit TCG collections.',
    'TCG relevance now ranks ahead of generic preorder wording during collection discovery.',
    'Ambiguous pack/deck display MSRP is blocked, including previously cached distributor records.',
)


def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
