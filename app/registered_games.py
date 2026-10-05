"""GAMES1: explicit card-game identity; no region/language assumptions."""
import re
import unicodedata

GAMES = frozenset({'Jurassic Park TCG', 'Godzilla TCG', 'Wuthering Waves', 'Union Arena'})
PATTERNS = (
    ('Jurassic Park TCG', r'\bjurassic park\b|쥬라기공원|쥬라기 공원'),
    ('Godzilla TCG', r'\bgodzilla\b|ゴジラ'),
    ('Wuthering Waves', r'\bwuthering waves\b|\bwuwa\b|鳴潮|鸣潮|명조'),
    ('Union Arena', r'\bunion arena\b|ユニオンアリーナ'),
)

def text(value):
    if isinstance(value, (list, tuple, set)):
        value = ' '.join(str(x) for x in value)
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return re.sub(r'\s+', ' ', re.sub(r'[-_:™®]+', ' ', value)).strip()

def registered_title(title):
    value = text(title)
    # A Godzilla/Jurassic crossover in MTG remains an MTG product.
    if re.search(r'\b(?:mtg|magic:? the gathering|secret lair|universes beyond)\b', value):
        return False
    return any(re.search(pattern, value) for _, pattern in PATTERNS)

def registered_identity(product):
    title = text(product.get('title'))
    if not registered_title(title):
        return None
    matches = {game for game, pattern in PATTERNS if re.search(pattern, title)}
    if len(matches) != 1:
        return None
    if re.search(r'\b(?:figure|figurine|statue|funko|plush\w*|poster|shirt|hoodie|'
                 r'keychain|acrylic|board game|video game|proxy|proxies|fan translation|'
                 r'translated cards|digital|online code|code card)\b', title):
        return None
    evidence = title + ' ' + text(product.get('product_type')) + ' ' + text(product.get('tags'))
    physical = re.search(r'\b(?:boosters?|starter decks?|structure decks?|display box|'
                         r'single card|singles|promo card|deck set|booster box|booster pack)\b|'
                         r'ブースター|スタートデッキ|スターターデッキ|補充包|补充包|부스터', evidence)
    explicit_tcg = re.search(r'\b(?:tcg|ccg|card game|trading card game)\b|'
                             r'カードゲーム|トレーディングカード|集换式|集換式', evidence)
    accessory = re.search(r'\b(?:playmat|play mat|sleeves|deck box|binder)\b', title)
    game = next(iter(matches))
    # Union Arena is itself a specific card-game name. The other franchise
    # names require an explicit TCG label, Battle/Showdown identity or card-game
    # title in the native language. Bare BP01/SD01 never identifies a game.
    specific = (game == 'Union Arena' or explicit_tcg or
                (game == 'Wuthering Waves' and re.search(r'\bbattle\b|\bshowdown\b|対決|对决|對決', evidence)))
    return game if specific and (physical or (accessory and explicit_tcg)) else None

def explicit_family(product):
    value = text(' '.join(str(product.get(k) or '') for k in
                         ('title','product_type','tags','language','product_language','variant_title')))
    matches = set()
    for pattern, family in (
        (r'\b(?:japanese|jpn)\b|日本語|日文|日版', 'JP'),
        (r'\b(?:korean|kor)\b|한국어|韓文|韩文|韓国語', 'KR'),
        (r'\b(?:simplified chinese|chinese)\b|简体|簡体|中文版', 'CN'),
        (r'\benglish\b|英語|英文', 'GLOBAL_STANDARD'),
    ):
        if re.search(pattern, value): matches.add(family)
    # Existing family schema does not distinguish Traditional Chinese.
    if re.search(r'\btraditional chinese\b|繁體|繁体', value): return 'UNKNOWN'
    for k in ('language','product_language'):
        family = {'ja':'JP','jp':'JP','ko':'KR','kr':'KR','zh':'CN','zh hans':'CN',
                  'cn':'CN','en':'GLOBAL_STANDARD'}.get(text(product.get(k)))
        if family: matches.add(family)
    if product.get('game') == 'Wuthering Waves' or re.search(PATTERNS[2][1], value):
        # No verified English retail edition yet; English copy is not evidence.
        matches.discard('GLOBAL_STANDARD')
    return next(iter(matches)) if len(matches) == 1 else 'UNKNOWN'
