"""Product-title exclusions shared by release ingestion and member calendars.

A franchise name and the word box do not establish a trading-card product.
Use the product title only: descriptions can mention unrelated merchandise.
"""
import re
import unicodedata


def non_tcg_reason(title):
    text = ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(title or ''))
                           if not unicodedata.combining(c)).casefold().split())
    text = text.replace('–', '-').replace('—', '-')
    # Digital redemption products are not physical cards or sealed releases.
    # Do not exclude ordinary booster boxes just because they include a code.
    if re.search(r'^codes?\s+pour\s+(?:un\s+|des\s+|le\s+)?boosters?\b', text) or re.search(
            r'\b(?:digital\s+(?:booster\s+|redeem\s+|redemption\s+)?codes?|'
            r'(?:ptcgl|ptcgo)\s+(?:online\s+)?codes?|'
            r'code\s+cards?\s+(?:only|digital)|codes?\s+(?:ptcgl|ptcgo))\b', text):
        return 'DIGITAL_REDEMPTION_CODE'
    # Named figure lines do not necessarily contain the standalone word figure.
    if re.search(r'\b(?:tamashii\s+nations|s\s*\.?\s*h\s*\.?\s*figuarts|'
                 r'figuarts\s*zero|s\s*\.?\s*h\s*\.?\s*figurearts)\b', text):
        return 'NON_TCG_COLLECTIBLE_LINE'
    if re.search(r'\b(?:nyaruto|mega\s*cat\s*project|shokugan|funko|nanoblock|gunpla|lego)\b', text):
        return 'NON_TCG_COLLECTIBLE_LINE'
    if re.search(r'\b(?:blind[- ]?boxes?|blind[- ]?box|mystery[- ]?figures?|model[- ]?kits?|plastic[- ]?models?)\b', text):
        return 'NON_TCG_BLIND_BOX_OR_MODEL'
    # Card-game boxes that include a figure are real TCG products, e.g.
    # Pokemon TCG: Pikachu VMAX Premium Figure Collection.
    tcg_figure_collection = bool(
        re.search(r'\b(?:tcg|trading card game|card game)\b', text)
        and re.search(r'\b(?:figure|figurine)\s+(?:premium\s+)?collection\b', text))
    if not tcg_figure_collection and re.search(
            r'\b(?:figures?|figurines?|statues?|plush(?:ies|es)?|puzzles?|keychains?|keyrings?|'
            r'acrylic\s+stands?|vinyl\s+toys?)\b', text):
        return 'NON_TCG_MERCHANDISE'
    return None
