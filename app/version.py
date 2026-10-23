"""Public release identity. Change this file for each shipped release."""
import os
VERSION = '1.7.7'
RELEASE_KIND = 'regular'
ANNOUNCEMENT_CHANNEL_ID = 1541869401220055201
RELEASE_NOTES = (
    'Community XP: random 10–20 XP per active minute, progressive levels and public bot-command rankings.',
    'Added private numbered support tickets, inactivity reminders and automatic closure.',
    'Added automatic Free-role assignment for new members and level-up notices in the levels channel.',
    'Added World of Tanks, Vibes and Shadowverse Evolve identities and discovery searches.',
    'Corrected the reported Ascended Heroes mini-tin display and added admin-reviewed game status notices.',
)


def build_id():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA', 'unknown')[:12]

def announcement():
    if RELEASE_KIND not in {'patch', 'regular', 'major'}:
        raise ValueError('Invalid release kind')
    prefix = '@everyone\n' if RELEASE_KIND == 'major' else ''
    return prefix + f'🪷 Lotus Tracker Bot v{VERSION} — {RELEASE_KIND.title()} update\n\n' + '\n'.join('• '+note for note in RELEASE_NOTES)
