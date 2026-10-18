"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.4.1'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Seller diagnostics now distinguish missing or invalid feedback from below-minimum feedback.',
    'English item specifics satisfy the 151 bundle language check without repeating English in the title.',
    'Distributor matching normalizes packaging labels and preorder/sealed wording; coverage diagnostics expose unmatched examples.',
)


def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]
def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
