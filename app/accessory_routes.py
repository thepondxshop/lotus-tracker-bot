"""TCG accessory destinations and explicit non-card merchandise exclusion."""
import os
import re

DEFAULTS = {
    'CHANNEL_ACCESSORIES_DROPS': '1562959977377955860',
    'CHANNEL_GLOBAL_ACCESSORIES_DROPS': '1562960120152064010',
}
ACCESSORY = re.compile(r'\b(?:play\s*mats?|sleeves?|deck\s+(?:boxes|box|cases?)|card\s+(?:storage|cases?)|binders?|portfolios?|card\s+protectors?|acrylic\s+(?:cases?|holders?)|dice|damage\s+counters?)\b', re.I)
TOY = re.compile(r'\b(?:mega\s+cat\s+project|nyan\s+piece|funko|plush(?:ies|ie)?|figurines?|action\s+figures?|statues?|model\s+kits?|building\s+blocks?|lego)\b', re.I)
TOY_TYPES = {'toy', 'toys', 'toys and collectible', 'toys and collectibles',
             'figure', 'figures', 'figurine', 'plushies', 'statue', 'model kit'}
ACCESSORY_TYPES = {'accessory', 'accessories', 'accessory case', 'card case',
                   'deck case', 'deck box', 'sleeves', 'playmat', 'binder', 'portfolio'}
CARD_FORMAT = re.compile(r'\b(?:booster|elite trainer|starter deck|commander deck|single card)\b', re.I)

# Product contents take precedence over stale retailer/category labels.
SINGLE = re.compile(r'\b(?:FB\d{2}-\d{3})\b|\[[^\]]*release event cards?\]', re.I)
INCLUDED_CARDS = re.compile(
    r'\b(?:with|includes?|contains?|including)\s+(?:\d+\s+)?(?:(?:exclusive|bonus|promo|promotional)\s+)*cards?\b'
    r'|(?:\+|&)\s*(?:(?:bonus|promo|promotional)\s+)?cards?\b'
    r'|\band\s+(?:bonus|promo|promotional)\s+cards?\b', re.I)
NO_CARDS = re.compile(r'\b(?:no|without|does not include|not including)\s+(?:(?:bonus|promo|promotional)\s+)?cards?\b|\bcards?\s+not\s+included\b', re.I)

def card_contents(event):
    title = str(event.get('product_name') or event.get('title') or '')
    # Explicit accessories bearing a card number are still accessories.
    typ = str(event.get('product_type') or '').strip().casefold()
    if (SINGLE.search(title) or typ in {'single card', 'singles', 'dragon ball super: fusion world single'}) and not ACCESSORY.search(title):
        return 'SINGLE'
    description = re.sub(r'<[^>]+>', ' ', str(event.get('product_description') or event.get('description') or ''))
    for evidence in (title, description):
        # "Includes card sleeves/protectors" describes an accessory, not cards.
        evidence = re.sub(r'\bcards?\s+(?:sleeves?|protectors?|holders?|storage|cases?|boxes?)\b', 'accessories', evidence, flags=re.I)
        if not NO_CARDS.search(evidence) and INCLUDED_CARDS.search(evidence):
            return 'COLLECTION'
    return None

def merchandise_event(event):
    title = str(event.get('product_name') or event.get('title') or '')
    typ = str(event.get('product_type') or '').strip().casefold()
    if TOY.search(title):
        return True
    return typ in TOY_TYPES and not (ACCESSORY.search(title) or CARD_FORMAT.search(title))

def accessory_event(event):
    if merchandise_event(event):
        return False
    title = str(event.get('product_name') or event.get('title') or '')
    typ = str(event.get('product_type') or '').strip().casefold()
    if card_contents(event):
        return False
    # Mixed sealed collections remain sealed products, even if they include sleeves.
    if CARD_FORMAT.search(title) and re.search(r'\b(?:with|includes?|and|\+)\b', title, re.I):
        return False
    return bool(ACCESSORY.search(title) or typ in ACCESSORY_TYPES
                or str(event.get('product_category') or '').upper() in {'ACCESSORY', 'ACCESSORIES'})

def normalize_accessory_event(event):
    contents = card_contents(event)
    if contents:
        result = dict(event, product_category=contents,
                      product_type='Single Card' if contents == 'SINGLE' else 'Collection Box')
        if (str(event.get('product_category') or '').upper() != contents
                or event.get('product_type') != result['product_type']):
            result.pop('reference_evidence', None)
        return result
    if not accessory_event(event):
        return event
    result = dict(event, product_category='ACCESSORY')
    if str(event.get('product_type') or '').lower() not in ACCESSORY_TYPES:
        result['product_type'] = 'Accessory'
        result.pop('reference_evidence', None)
    return result

def accessory_destination(event, environ=None):
    if not accessory_event(event):
        return None
    env = os.environ if environ is None else environ
    region = str(event.get('region') or '').strip().upper()
    variable = ('CHANNEL_ACCESSORIES_DROPS' if region in
                {'US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA'}
                else 'CHANNEL_GLOBAL_ACCESSORIES_DROPS')
    value = str(env.get(variable, DEFAULTS[variable])).strip()
    cid = int(value) if value.isascii() and value.isdigit() and int(value) > 0 else None
    return dict(channel_id=cid, variable=variable, reason='TCG_ACCESSORY', version='ACCESSORY1')
