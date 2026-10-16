"""EBAY-LIVE2: strict reviewed-target matching. No network or publication."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from app.marketplaces.opportunity import evaluate, number, timestamp
from app.marketplaces.ebay_evidence import evaluate_item_only


def load_targets(path):
    p = Path(path)
    if p.stat().st_size > 262144:
        raise ValueError('Target file too large')
    rows = json.loads(p.read_text())
    if not isinstance(rows, list) or len(rows) > 10:
        raise ValueError('Expected at most ten reviewed targets')
    seen = set()
    for t in rows:
        if not isinstance(t, dict) or not re.fullmatch(r'[a-z0-9_-]{1,60}', str(t.get('id', ''))):
            raise ValueError('Invalid target ID')
        if t['id'] in seen:
            raise ValueError('Duplicate target ID')
        seen.add(t['id'])
        if (t.get('reviewed') is not True or t.get('game') in (None, '', 'UNKNOWN')
                or not re.fullmatch(r'\d{8,14}', str(t.get('gtin', '')))
                or not str(t.get('condition_id', '')).isdigit()
                or not isinstance(t.get('required_terms'), list) or not t['required_terms']
                or not all(isinstance(x, str) and x.strip() for x in t['required_terms'])
                or not isinstance(t.get('aspects'), dict) or not t['aspects']
                or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k,v in t['aspects'].items())
                or not isinstance(t.get('excluded_terms', []), list)
                or not all(isinstance(x, str) and x for x in t.get('excluded_terms', []))
                or t.get('quantity') != 1 or isinstance(t.get('quantity'), bool)):
            raise ValueError('Target needs reviewed identity, GTIN, condition, terms, aspects and quantity=1')
        if t.get('comparison_mode') == 'ITEM_ONLY':
            if t.get('currency') != 'USD' or not isinstance(t.get('sold_records', []), list):
                raise ValueError('Item-only pilot requires USD and a sold-record list')
        else:
            if t.get('currency') != 'USD' or not re.fullmatch(r'\d{5}', str(t.get('destination_zip', ''))):
                raise ValueError('Legacy target requires USD and an explicit US delivery ZIP')
            rate = number(t.get('tax_rate'))
            if rate is None or rate > 1 or t.get('costs_reviewed') is not True:
                raise ValueError('Reviewed destination tax rate required')
        ref = t.get('comparison', {})
        # No fake default market values; missing/expired evidence remains blocked.
        if not isinstance(ref, dict):
            raise ValueError('Comparison must be an object')
    return rows


def folded(s):
    return re.sub(r'\s+', ' ', str(s).casefold()).strip()


def gtin_status(item, target):
    """Match explicit identifiers only; never infer a GTIN from a search or title."""
    expected = str(target['gtin']).lstrip('0')
    fields = [('gtin', item.get('gtin'))]
    product = item.get('product') or {}
    catalog_codes = product.get('gtins') if isinstance(product, dict) else None
    if catalog_codes is not None:
        if isinstance(catalog_codes, list):
            fields.extend(('product.gtins', code) for code in catalog_codes)
        else:
            # A malformed catalog value cannot silently become identity evidence.
            fields.append(('product.gtins', 'invalid catalog GTIN array'))
    for aspect in item.get('localizedAspects') or []:
        if isinstance(aspect, dict) and folded(aspect.get('name')) in {'upc', 'ean', 'gtin', 'gtin-12', 'gtin-13', 'gtin-14'}:
            fields.append(('aspect:' + folded(aspect['name']), aspect.get('value')))
    codes, sources = set(), set()
    malformed = False
    placeholders = {'', 'none', 'n/a', 'na', 'does not apply', 'not applicable', 'unknown'}
    for source, value in fields:
        if value is None or folded(value) in placeholders:
            continue
        # Allow formatting spaces/hyphens, not arbitrary embedded numbers or lists.
        normalized = re.sub(r'[\s-]', '', str(value))
        if not re.fullmatch(r'[0-9]{8}|[0-9]{12,14}', normalized) or not normalized.strip('0'):
            malformed = True
            continue
        codes.add(normalized.lstrip('0'))
        sources.add(source)
    if len(codes) > 1:
        reason = 'GTIN_CONFLICT'
    elif malformed:
        reason = 'GTIN_INVALID'
    elif not codes:
        reason = 'GTIN_MISSING'
    elif expected not in codes:
        reason = 'GTIN_MISMATCH'
    else:
        reason = 'GTIN_MATCH'
    return {'reason': reason, 'expected_gtin': str(target['gtin']),
            'observed_gtins': sorted(codes), 'identifier_sources': sorted(sources),
            'product_container_present': isinstance(item.get('product'), dict)}


def assess(item, target, now=None):
    now = now or datetime.now(timezone.utc)
    def block(reason): return {'eligible': False, 'reason': reason}
    title = folded(item.get('title', ''))
    if not all(folded(x) in title for x in target['required_terms']):
        return block('TITLE_MISMATCH')
    # Neither item specifics nor a GTIN alone establish box/pack/lot identity.
    blocked = ['empty box', 'box only', 'digital code', 'proxy', 'replica', 'repack', 'mystery', 'break spot'] + target.get('excluded_terms', [])
    if any(folded(x) in title for x in blocked):
        return block('EXCLUDED_PRODUCT')
    identity = gtin_status(item, target)
    if identity['reason'] != 'GTIN_MATCH':
        return dict(eligible=False, **identity)
    if str(item.get('conditionId')) != target['condition_id']:
        return block('CONDITION_MISMATCH')
    aspects = {folded(a.get('name')): folded(a.get('value')) for a in item.get('localizedAspects', []) if isinstance(a, dict)}
    if any(aspects.get(folded(k)) != folded(v) for k,v in target['aspects'].items()):
        return block('ASPECT_MISMATCH')
    if item.get('itemGroupType') or item.get('itemGroupHref') or item.get('itemGroupId'):
        return block('VARIATION_GROUP')
    if (str(item.get('lotSize', '1')) != '1' or re.search(r'\b(?:lot|set|case) of [2-9]\d*\b|\b[2-9]\d*\s*[x×]\s*|\b[2-9]\d*\s+booster bundles?\b', title)):
        return block('MULTI_UNIT_LOT')
    if item.get('itemLocation', {}).get('country') != 'US':
        return block('IMPORT_COSTS_NOT_SUPPORTED_IN_PILOT')
    seller = item.get('seller') or {}
    score, percentage = number(seller.get('feedbackScore')), number(seller.get('feedbackPercentage'))
    if not seller.get('username') or score is None or score < 100 or percentage is None or percentage < Decimal('98'):
        return block('SELLER_EVIDENCE_INSUFFICIENT')
    options = item.get('buyingOptions') or []
    auction = 'AUCTION' in options
    if not auction and 'FIXED_PRICE' not in options:
        return block('UNSUPPORTED_BUYING_OPTION')
    ends = timestamp(item.get('itemEndDate'))
    if ends and ends <= now:
        return block('ENDED')
    if auction and (not ends or not 0 < (ends-now).total_seconds() <= 600):
        return block('OUTSIDE_FINAL_TEN_MINUTES')
    if auction and item.get('reservePriceMet') is not True:
        return block('RESERVE_NOT_VERIFIED_MET')
    if not auction and not any(a.get('estimatedAvailabilityStatus') == 'IN_STOCK' for a in item.get('estimatedAvailabilities', [])):
        return block('AVAILABILITY_UNKNOWN')
    price = item.get('minimumPriceToBid' if auction else 'price') or {}
    if price.get('currency') != target['currency']:
        return block('CURRENCY_MISMATCH')
    # Only a fixed shipping quote returned for the requested US destination.
    quotes = []
    for shipping in item.get('shippingOptions', []):
        cost = shipping.get('shippingCost') or {}
        value = number(cost.get('value'))
        if shipping.get('shippingCostType') == 'FIXED' and cost.get('currency') == target['currency'] and value is not None:
            quotes.append(value)
    if target.get('comparison_mode') == 'ITEM_ONLY':
        shipping = min(quotes) if quotes else None
        result = evaluate_item_only(price.get('value'), target, auction, now)
    else:
        if not quotes:
            return block('SHIPPING_UNKNOWN')
        shipping = min(quotes)
        ref = target.get('comparison') or {}
        if ref.get('cost_basis') != 'ITEM_PLUS_SHIPPING_AND_DESTINATION_TAX' or ref.get('destination_zip') != target['destination_zip']:
            return block('COMPARISON_COST_BASIS_MISMATCH')
        row = {'marketplace': 'ebay', 'auction': auction, 'currency': target['currency'],
               'price': price.get('value'), 'minimum_next_bid': price.get('value'),
               'ends_at': item.get('itemEndDate'), 'observed_at': now.isoformat(), 'comparison': ref,
               'purchase_costs': {'fixed': str(shipping * (1 + number(target['tax_rate']))),
                   'tax_rate': target['tax_rate'], 'verified': True, 'complete': True,
                   'currency': target['currency'], 'mode': 'SHIP_HOME'}}
        result = evaluate(row, now)
    if not result['eligible']:
        return result
    url = urlsplit(str(item.get('itemWebUrl', '')))
    if url.scheme != 'https' or url.hostname not in {'www.ebay.com', 'ebay.com'} or url.username or url.password:
        return block('INVALID_LISTING_URL')
    result.update(title=str(item['title'])[:230], url=item['itemWebUrl'], auction=auction,
                  price=str(price['value']), shipping=str(shipping) if shipping is not None else None, tax_rate=target.get('tax_rate'),
                  destination_zip=target.get('destination_zip'), ends_at=item.get('itemEndDate'),
                  observed_at=now.isoformat(), game=target['game'], currency=target['currency'])
    return result
