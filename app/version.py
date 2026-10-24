"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.8'
RELEASE_KIND = 'patch'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Corrected Gundam ST14 Starter Deck Box Heavy Dominion to a sealed starter-deck display, not an accessory or shipping case.',
    'Verified uncapped daily XP; the 60-second eligible-message cooldown remains.',
    'Registered Beyblade X TCG — Blader League for its announced 2027 launch; exact release date remains TBA.',
    'Configured the supplied World of Tanks, Vibes and Shadowverse role IDs.',
    'Assigned a distinct crystal-ball emoji to Shadowverse and a tornado to Beyblade X.',
    'Added Blader League discovery and official-page status-watch configuration; restored missing update documentation.',
)


def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
