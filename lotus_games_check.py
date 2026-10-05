"""Read-only registry check: no Discord messages, network calls or scans."""
import json
from app.config import GAME_ROLES, GAME_DATA
from app.registered_games import GAMES

def main():
    menu = {row[0] for row in GAME_DATA}
    rows = {game: {'menu': game in menu,
                   'role_configured': str(GAME_ROLES.get(game) or '').isdigit()
                                      and int(GAME_ROLES.get(game) or 0) > 0}
            for game in sorted(GAMES)}
    print('LOTUS GAME REGISTRY | ' + json.dumps({'version':'GAMES1','games':rows}))
    return 0 if all(row['menu'] and row['role_configured'] for row in rows.values()) else 1

if __name__ == '__main__':
    raise SystemExit(main())
