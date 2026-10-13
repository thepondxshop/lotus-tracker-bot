"""Conservative listing identity and cost completeness for future marketplace adapters."""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

MINIMUM_TIERS = {'ebay': 'Premium', 'mercari_us': 'Premium', 'buyee_jp': 'Premium+'}
COST_COMPONENTS = ('item', 'domestic_shipping', 'international_shipping', 'proxy_fee', 'tax', 'duty')


def amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def normalize_listing(raw):
    """For reviewed feed rows only. UNKNOWN fields never imply language or stock."""
    market = raw.get('marketplace')
    if market not in MINIMUM_TIERS:
        raise ValueError('Unsupported marketplace')
    listing_id = str(raw.get('listing_id') or '').strip()
    title = str(raw.get('title') or '').strip()
    url = str(raw.get('url') or '').strip()
    parsed = urlsplit(url)
    if not listing_id or not title or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Listing requires identity, title and public HTTPS URL')
    currency = str(raw.get('currency') or '').strip().upper()
    price = amount(raw.get('price'))
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha() or price is None:
        raise ValueError('Listing requires nonnegative price and currency code')
    return {
        'marketplace': market, 'listing_id': listing_id, 'title': title, 'url': url,
        'minimum_tier': MINIMUM_TIERS[market], 'price': str(price), 'currency': currency,
        'price_basis': 'ASKING', 'stock_state': 'UNKNOWN',
        'game': str(raw.get('game') or 'UNKNOWN'), 'language': str(raw.get('language') or 'UNKNOWN'),
        'edition': str(raw.get('edition') or 'UNKNOWN'), 'condition': str(raw.get('condition') or 'UNKNOWN'),
        'source_region': str(raw.get('source_region') or 'UNKNOWN'),
        'provenance': str(raw.get('provenance') or 'MANUAL_REVIEW_REQUIRED'),
    }


def deduplicate_listings(rows):
    """Same marketplace + listing ID only; titles across editions never collapse."""
    unique = {}
    for row in rows:
        normalized = normalize_listing(row)
        key = (normalized['marketplace'], normalized['listing_id'])
        unique[key] = normalized
    return list(unique.values())


def landed_cost(components, currency):
    """All six components must be explicit, including verified zeros. No FX guessing."""
    known, missing = {}, []
    for name in COST_COMPONENTS:
        component = components.get(name)
        value = amount(component.get('amount')) if isinstance(component, dict) else None
        if value is None or component.get('currency') != currency:
            missing.append(name)
        else:
            known[name] = value
    return {'currency': currency, 'complete': not missing, 'missing': missing,
            'known_subtotal': str(sum(known.values(), Decimal('0'))),
            'estimated_total': None if missing else str(sum(known.values(), Decimal('0'))),
            'is_quote': False}
