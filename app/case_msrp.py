"""Calculate case MSRP only from explicit, reviewed product-specific evidence."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit


def calculated_case_amount(row, now=None):
    d = row.get('derivation')
    if not isinstance(d, dict) or d.get('method') != 'UNIT_MSRP_TIMES_CASE_QUANTITY':
        raise ValueError('Case derivation method required')
    if row.get('kind') != 'MSRP' or str(row.get('product_type', '')).upper() not in {'CASE', 'SEALED CASE', 'BOOSTER CASE'}:
        raise ValueError('Calculated case MSRP requires a sealed case')
    unit, pack = d.get('unit_reference'), d.get('case_contents')
    if not isinstance(unit, dict) or not isinstance(pack, dict):
        raise ValueError('Both unit MSRP and case contents evidence required')
    now = now or datetime.now(timezone.utc)
    for evidence in (unit, pack):
        if evidence.get('reviewed') is not True:
            raise ValueError('Case evidence must be reviewed')
        u = urlsplit(str(evidence.get('source', '')))
        if u.scheme != 'https' or not u.hostname:
            raise ValueError('Case evidence source required')
        try:
            captured = datetime.fromisoformat(evidence['captured_at'])
            expires = datetime.fromisoformat(evidence['expires_at'])
            if captured.tzinfo is None or expires.tzinfo is None or not captured <= now < expires:
                raise ValueError('Case evidence expired or future dated')
        except (KeyError, TypeError):
            raise ValueError('Case evidence dates required') from None
    if any(not isinstance(unit.get(k), str) or not unit[k].strip() for k in ('product_id', 'product_name', 'unit_type')):
        raise ValueError('Exact contained product identity required')
    if unit.get('unit_type') not in {'BOOSTER_BOX', 'BOOSTER_BUNDLE', 'BOOSTER_PACK', 'DECK', 'ETB', 'DOUBLE_PACK'}:
        raise ValueError('Unsupported contained unit')
    if any(unit.get(k) != row.get(k) for k in ('game', 'product_family', 'currency', 'region')):
        raise ValueError('Contained product region/currency/family mismatch')
    if pack.get('case_product_url') != row.get('product_url') or pack.get('unit_product_id') != unit['product_id']:
        raise ValueError('Case contents do not match exact case and unit')
    quantity = pack.get('quantity')
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 10000:
        raise ValueError('Positive integer case quantity required')
    try:
        price = Decimal(str(unit['amount']))
        if not price.is_finite() or not 0 < price < Decimal('1e15'):
            raise ValueError('Invalid unit MSRP')
    except (KeyError, InvalidOperation):
        raise ValueError('Unit MSRP required') from None
    return price * quantity
