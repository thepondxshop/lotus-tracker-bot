"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.4.5'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'GTS MSRP requires explicit matching price-unit evidence; generic Each/default prices are blocked.',
    'Cached and queued GTS references without verified units no longer qualify as below-MSRP deals.',
    'Repeated identical reference evidence is deduplicated during enrichment.',
)


def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
