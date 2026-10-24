"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.10'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Configured Beyblade X role 1563394352531775618.',
    'Paced Shopify request starts across stores and staggered rate-limit recovery.',
    'Added a shared quiet period after throttling across five stores; per-store Retry-After remains respected.',
    'This reduces synchronized retries; live recovery and detection latency require production verification.',
)



def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
