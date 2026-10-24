"""C19: select one recovery feed per pass, with fair discovery slots."""
import re
import time

_PROVEN = {}
_TURNS = {}
WAITING = set()


def explicit_tcg(handle, title=""):
    probe = re.sub(r"[-_]+", " ", f"{handle} {title}".lower())
    return bool(re.search(r"\b(?:tcg|ccg|trading cards?|card games?|pokemon|pokémon|one piece|riftbound|magic the gathering|mtg|lorcana|union arena|weiss|azuki|horo beat|fusion world|dragon ball|final fantasy|cookie run|cookierun|gundam|world of tanks|vibes|shadowverse|beyblade x tcg|blader league)\b", probe))


def tcg_candidate(handle, title=""):
    probe = re.sub(r"[-_]+", " ", f"{handle} {title}".lower())
    if explicit_tcg(handle,title):return True
    return not re.search(r"\b(?:comics?|graphic novels?|manga|dungeons (?:and |& )?dragons|dnd|role playing|rpg|funko|board games?|warhammer|miniatures?|model kits?|jigsaw puzzles?)\b", probe)


def record(domain, handle, page, tcg_count):
    key = (domain, handle)
    if tcg_count:
        _PROVEN[key] = time.monotonic()
    elif page == 1:
        _PROVEN.pop(key, None)


def choose(domain, rows, last_check, deferred, now):
    ready = [r for r in rows if tcg_candidate(r[1], r[2] if len(r) > 2 else "")
             and deferred.get((domain, r[1]), 0) <= now]
    WAITING.discard(domain)
    if not ready:
        if rows:
            WAITING.add(domain)
        return []
    # Positive evidence expires so a once-useful collection cannot stay hot forever.
    hot = [r for r in ready if now - _PROVEN.get((domain, r[1]), -float('inf')) < 3600]
    cold = [r for r in ready if r not in hot]
    turn = _TURNS.get(domain, 0)
    pool = cold if cold and (not hot or turn % 3 == 2) else hot or cold
    # Explore explicit TCG feeds before generic preorder/mixed feeds.
    focused = [r for r in pool if explicit_tcg(r[1],r[2] if len(r)>2 else '')]
    pool = focused or pool
    row = min(pool, key=lambda r: last_check.get((domain, r[1]), -1))
    _TURNS[domain] = turn + 1
    key = (domain, row[1])
    previous = last_check.get(key)
    last_check[key] = now
    age = round(now - previous, 1) if previous is not None else None
    print(f'SHOPIFY RECOVERY SELECTION | Store={domain} | Collection={row[1]} | '
          f'Class={"PROVEN_TCG" if row in hot else "DISCOVERY"} | RevisitSeconds={age} | '
          f'ReadyProven={len(hot)} | ReadyDiscovery={len(cold)} | Version=C19')
    return [row]
