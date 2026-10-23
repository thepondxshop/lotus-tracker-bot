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
    # Mixed sealed collections remain sealed products, even if they include sleeves.
    if CARD_FORMAT.search(title) and re.search(r'\b(?:with|includes?|and|\+)\b', title, re.I):
        return False
    return bool(ACCESSORY.search(title) or typ in ACCESSORY_TYPES
                or str(event.get('product_category') or '').upper() in {'ACCESSORY', 'ACCESSORIES'})

def normalize_accessory_event(event):
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
