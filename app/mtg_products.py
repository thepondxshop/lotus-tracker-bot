"""MTG retailer identity and packaging. No network requests or stock inference."""
import re
import unicodedata
from app.event_listing_filter import is_event_listing

VERSION = "1.0.0"
GAME = "MTG"


def text(value):
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(v) for v in value)
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"\s+", " ", re.sub(r"[-_:®™]+", " ", value)).strip()


def has_mtg_identity(value):
    return bool(re.search(r"\b(?:mtg|magic\s+the\s+gathering)\b", text(value)))


_MERCH = re.compile(
    r"\b(?:plush\w*|funko|figurine|statue|hoodie|shirt|sweatshirt|mug|"
    r"keychain|keyring|lanyard|wallet|backpack|poster|miniatures|"
    r"model kit|action figure|board game|boardgame|arena code|digital code)\b"
)
_CONFLICT = re.compile(
    r"\b(?:pokemon|pokémon|one piece|riftbound|gundam|fusion world|"
    r"palworld|naruto|hellbreak|azuki|cataclysm[\s-]+arcade|yugioh|yu gi oh|lorcana|digimon|"
    r"flesh and blood|star wars unlimited)\b"
)


def mtg_product_details(title, raw_type=None, tags=None):
    """Return category/type only with explicit MTG identity and physical format.

    Bare 'Magic', 'Commander', set codes, Wizards vendor and descriptions do
    not establish the game. Accessories precede packaging; explicit single
    metadata precedes set names. Unknown card names remain unclassified.
    """
    combined = text([title or "", raw_type or "", text(tags)])
    if not has_mtg_identity(combined):
        return None
    if _MERCH.search(text(title)) or _CONFLICT.search(combined):
        return None
    if is_event_listing(title, raw_type):
        return None
    accessories = (
        (r"\b(?:card\s+)?sleeves?\b", "Sleeves"),
        (r"\bplay\s*mat\b", "Playmat"),
        (r"\bdeck\s+box\b", "Deck Box"),
        (r"\b(?:binder|portfolio)\b", "Binder"),
    )
    for pattern, label in accessories:
        if re.search(pattern, combined):
            return "ACCESSORY", label
    single_probe = re.split(r"\b(?:with|includes|including|featuring)\b", combined, maxsplit=1)[0]
    if text(raw_type) in {"single", "singles", "single card", "tcg single", "individual card", "promo card"} or re.search(
        r"\b(?:single card|tcg single|individual card|singles|promo card)\b", single_probe
    ):
        return "SINGLE", "Single Card"
    # Number plus condition is useful for singles; foil alone also describes packs.
    if re.search(r"(?:#\s*\d+|\b\d+\s*/\s*\d+\b)", combined) and re.search(
        r"\b(?:near mint|lightly played|moderately played|heavily played|nm|lp|mp|hp)\b", combined
    ):
        return "SINGLE", "Single Card"
    if re.search(r"\bcase\b", text(title)):
        return "SEALED", "Case"
    formats = (
        (r"\bcommander\s+decks?\b", "Commander Deck"),
        (r"\b(?:pre\s*release|prerelease)\s+(?:kit|pack|box)\b", "Prerelease Kit"),
        (r"\b(?:starter\s+(?:kit|deck)|beginner\s+box)\b", "Starter Kit"),
        (r"\b(?:gift\s+)?bundle\b", "Bundle"),
        (r"\b(?:play|collector|draft|set|jumpstart)\s+boosters?\s+(?:box|display)\b", "Booster Box"),
        (r"\bbooster\s+(?:box|display)\b", "Booster Box"),
        (r"\b(?:play|collector|draft|set|jumpstart)\s+boosters?\b", "Booster Pack"),
        (r"\bbooster\s+pack\b", "Booster Pack"),
    )
    for pattern, label in formats:
        if re.search(pattern, combined):
            return "SEALED", label
    return None


def classify_mtg(title, raw_type=None, tags=None):
    return GAME if mtg_product_details(title, raw_type, tags) else None


def explicit_mtg_family(product):
    """Use explicit language fields/tags; prices and currency are irrelevant."""
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    values = [product.get("language"), product.get("product_language"), *tags]
    aliases = {"japanese": "JP", "jpn": "JP", "jp": "JP",
               "korean": "KR", "kor": "KR", "kr": "KR",
               "simplified chinese": "CN", "cn": "CN",
               "english": "GLOBAL_STANDARD", "eng": "GLOBAL_STANDARD", "en": "GLOBAL_STANDARD",
               **dict.fromkeys(("french", "german", "italian", "spanish", "portuguese", "russian",
                                "traditional chinese", "chinese"), "UNKNOWN")}
    found = set()
    for value in values:
        normalized = re.sub(r"^language\s+", "", text(value))
        if normalized in aliases:
            found.add(aliases[normalized])
    return next(iter(found)) if len(found) == 1 else "UNKNOWN" if found else None
