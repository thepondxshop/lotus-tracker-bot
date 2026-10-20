"""Conservative catalog identity for alert update A1. No network requests.

An explicit title identity outranks retailer tags and shared set codes.
Unrecognized games stay discoverable under a neutral label, not another role.
"""
import re
import unicodedata

VERSION = "1.0.6-IDENTITY2"
NEW_TCG = "New TCG — identity unverified"
JURASSIC_TCG = "Jurassic Park TCG"
FUSION_WORLD_GAME = "Dragon Ball Fusion World"
FUSION_WORLD_PATTERN = re.compile(
    r"\b(?:(?:dragon\s*ball(?:\s+super)?(?:\s+(?:card\s+game|tcg|ccg))?|dbs(?:cg)?)"
    r"\s+(?:fusion\s*world|fw)|fusion\s*world\s+(?:tcg|card\s+game))\b"
)
DISCOVERY_GAMES = frozenset({NEW_TCG, JURASSIC_TCG})


def _text(value):
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(v) for v in value)
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = value.replace("é", "e")
    return re.sub(r"\s+", " ", re.sub(r"[-_:®™]+", " ", value)).strip()


def has_fusion_world_identity(value):
    """Accept catalog spelling/punctuation variants, including the explicit DragonBall FW abbreviation.

    Dragon Ball Super or Masters alone is not Fusion World evidence.
    """
    text = _text(value)
    if re.search(r"\bmasters\b", text):
        return False
    explicit = bool(FUSION_WORLD_PATTERN.search(text))
    # FB01 is the official Fusion World booster code. Retailers sometimes
    # omit the line name; require Dragon Ball card-game context, never FB alone.
    contextual_code = bool(
        re.search(r"\bdragon\s*ball(?:\s+super)?\b", text)
        and re.search(r"\b(?:card\s+game|tcg|ccg)\b", text)
        and re.search(r"\bfb\s*0?1\b", text)
    )
    return explicit or contextual_code


_TCG = re.compile(r"\b(?:tcg|ccg|trading card game|collectible card game|card game)\b")
_PHYSICAL = re.compile(
    r"\b(?:booster(?:s| box| pack| display| bundle)?|starter deck|structure deck|"
    r"deck set|single card|tcg single|singles|promo card|collection box|display box)\b"
)
_NOT_CARDS = re.compile(
    r"\b(?:plush\w*|funko|figure|figurine|statue|shirt|hoodie|poster|"
    r"keychain|keyring|mug|board game|boardgame|miniatures|model kit|"
    r"sleeves?|playmat|deck box|binder|digital|online code)\b"
)
_GAME_PATTERNS = tuple((game, re.compile(pattern)) for game, pattern in (
    ("One Piece", r"\bone piece\b"),
    ("Pokemon", r"\bpokemon\b"),
    ("MTG", r"\b(?:mtg|magic the gathering)\b"),
    ("Gundam", r"\bgundam\b"),
    (FUSION_WORLD_GAME, FUSION_WORLD_PATTERN.pattern),
    ("Riftbound", r"\briftbound\b"),
    ("Palworld", r"\bpalworld\b"),
    ("Naruto", r"\bnaruto\b"),
    ("Cyberpunk TCG", r"\bcyberpunk\b"),
    ("Azuki TCG", r"\bazuki\b"),
    ("Hellbreak TCG", r"\bhellbreak\b"),
    ("Cataclysm Arcade", r"\bcataclysm[\s-]+arcade\b"),
    (JURASSIC_TCG, r"\bjurassic park\b"),
))
# Keep intentionally excluded game lines excluded; this update does not
# turn unrelated tabletop catalogs into supported games.
_EXCLUDED = re.compile(
    r"\b(?:yu gi oh|yugioh|lorcana|digimon|weiss schwarz|union arena|"
    r"flesh and blood|star wars unlimited|warhammer|games workshop)\b"
)


def graded_pokemon_title(title):
    text = _text(title)
    # Require the character, collector number, grading company and numeric grade.
    # Character merchandise, raw cards and other games cannot satisfy this rule.
    return bool(re.search(r"\bpikachu\b", text)
        and re.search(r"\b\d{1,4}/\d{1,4}\b", text)
        and re.search(r"\b(?:psa|bgs|cgc|sgc)\s+(?:10|[1-9](?:\.5)?)\b", text)
        and not _NOT_CARDS.search(text))


def non_tcg_stationery(title):
    text = _text(title)
    return bool(re.search(r"\b(?:a[345]\s+clear\s+file|clear\s+file|stationery|pencil\s+case|pen\s+case)\b", text))


def title_identity(title):
    """Return a named identity, a neutral TCG candidate, or no evidence.

Two competing names are ambiguous (including crossover products). Known
games retain their existing physical-product checks in the adapter.
"""
    text = _text(title)
    if non_tcg_stationery(title): return None
    if graded_pokemon_title(title): return "Pokemon"
    if _EXCLUDED.search(text):
        return None
    matches = {game for game, pattern in _GAME_PATTERNS if pattern.search(text)}
    if has_fusion_world_identity(text):
        matches.add(FUSION_WORLD_GAME)
    elif re.search(r"\bmasters\b", text):
        matches.discard(FUSION_WORLD_GAME)
    if len(matches) == 1:
        return next(iter(matches))
    if len(matches) > 1 or _TCG.search(text):
        return NEW_TCG
    return None


def has_named_tcg_title(title):
    """Distinguish 'Nebula TCG' from a generic 'TCG Booster Box' title."""
    probe = _text(title)
    marker = _TCG.search(probe)
    if not marker:
        return False
    prefix = probe[:marker.start()]
    prefix = re.sub(r"\b(?:pre\s*order|new|english|japanese|korean|sealed|"
                    r"booster|box|pack|starter|deck|the|a)\b", " ", prefix)
    return bool(re.search(r"[a-z]{2,}", prefix))


def discovery_identity(product):
    """Accept new games only with card-format and explicit TCG evidence.

Descriptions, store region, currency, vendor names and bare set codes do
not establish a new game's identity. Title conflicts cannot borrow tags.
"""
    title = _text(product.get("title"))
    raw_type = _text(product.get("product_type"))
    tags = _text(product.get("tags"))
    combined = " ".join((title, raw_type, tags))
    if graded_pokemon_title(title) or non_tcg_stationery(title): return None
    if _EXCLUDED.search(title) or _NOT_CARDS.search(title):
        return None
    if not _PHYSICAL.search(" ".join((title, raw_type))) or not _TCG.search(combined):
        return None
    identity = title_identity(title)
    if identity == JURASSIC_TCG or (identity == NEW_TCG and has_named_tcg_title(title)):
        return identity
    if identity and identity != NEW_TCG:
        return None
    # A retailer's explicit Jurassic taxonomy can establish a title that
    # only contains the expansion name. Multiple identities remain neutral.
    identities = {game for game, pattern in _GAME_PATTERNS if pattern.search(combined)}
    if identities == {JURASSIC_TCG}:
        return JURASSIC_TCG
    if identities or _EXCLUDED.search(combined):
        return None
    return NEW_TCG


def explicit_discovery_family(product):
    """Do not infer a new game's language from an English name or US store."""
    probe = _text([product.get(key) or "" for key in (
        "title", "product_type", "tags", "language", "product_language", "variant_title"
    )])
    families = set()
    for pattern, family in (
        (r"\benglish\b", "GLOBAL_STANDARD"),
        (r"\bjapanese\b", "JP"),
        (r"\bkorean\b", "KR"),
        (r"\bsimplified chinese\b", "CN"),
        (r"\b(?:french|german|italian|spanish|portuguese|traditional chinese)\b", "UNKNOWN"),
    ):
        if re.search(pattern, probe):
            families.add(family)
    for key in ("language", "product_language"):
        code = _text(product.get(key))
        mapped = {"en": "GLOBAL_STANDARD", "eng": "GLOBAL_STANDARD",
                  "ja": "JP", "jp": "JP", "jpn": "JP", "ko": "KR",
                  "kr": "KR", "kor": "KR", "zh hans": "CN"}.get(code)
        if mapped:
            families.add(mapped)
    return next(iter(families)) if len(families) == 1 else "UNKNOWN"
