"""MARKET3: local, reviewed Mercari US / Buyee records. Never scrapes or sends alerts."""
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
import re
from app.marketplaces.foundation import normalize_listing, landed_cost


def identity(url, market):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise ValueError('PUBLIC_HTTPS_REQUIRED')
    hostname = (p.hostname or '').lower().removeprefix('www.')
    if market == 'mercari_us' and hostname == 'mercari.com':
        match = re.fullmatch(r'/us/item/(m\d+)/?', p.path)
        source = 'mercari_us'
    elif market == 'buyee_jp' and hostname == 'buyee.jp':
        match = re.fullmatch(r'/(?:item/mercari|mercari/item)/(m\d+)/?', p.path)
        source = 'mercari_jp'
        if not match:
            match = re.fullmatch(r'/item/yahoo/auction/([A-Za-z0-9]+)/?', p.path)
            source = 'yahoo_auctions_jp'
    else:
        raise ValueError('MARKETPLACE_URL_MISMATCH')
    if not match:
        raise ValueError('UNSUPPORTED_LISTING_URL')
    native_id = match.group(1)
    return source + ':' + native_id, urlunsplit(('https', hostname, p.path.rstrip('/') + '/', '', ''))


def review_rows(rows, now=None):
    now = now or datetime.now(timezone.utc)
    accepted, rejected = {}, []
    for index, raw in enumerate(rows):
        try:
            key, url = identity(raw.get('url', ''), raw.get('marketplace'))
            at = datetime.fromisoformat(str(raw.get('observed_at', '')).replace('Z', '+00:00'))
            if at.tzinfo is None:
                raise ValueError('OBSERVATION_TIMEZONE_REQUIRED')
            age = (now - at).total_seconds()
            if age < 0:
                raise ValueError('OBSERVATION_IN_FUTURE')
            row = normalize_listing({**raw, 'url': url, 'listing_id': key})
            row.update(source_listing_key=key, observed_at=at.isoformat(),
                       stale=age > 900, review_required=True, automatic_alert_eligible=False)
            if raw.get('cost_components') is not None:
                if not isinstance(raw['cost_components'], dict):
                    raise ValueError('INVALID_COST_COMPONENTS')
                row['landed_cost'] = landed_cost(raw['cost_components'], row['currency'])
            # Preserve newest observation; alternate proxy URLs cannot double-count it.
            previous = accepted.get((row['marketplace'], key))
            if previous is None or at > datetime.fromisoformat(previous['observed_at']):
                accepted[(row['marketplace'], key)] = row
        except (ValueError, TypeError, AttributeError, OverflowError):
            rejected.append({'index': index, 'reason': 'INVALID_IDENTITY_PRICE_OR_OBSERVATION'})
    return {'version': 'MARKET3', 'accepted': len(accepted), 'rejected': rejected,
            'review_candidates': list(accepted.values()), 'alerts_sent': 0,
            'network_requests': 0, 'live_pipeline_enabled': False}
