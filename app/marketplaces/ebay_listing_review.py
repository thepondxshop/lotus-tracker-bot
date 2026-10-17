"""Explicit, expiring review for one GTIN-less listing; never fuzzy matching."""
import hashlib
import json
from datetime import datetime, timezone
from app.marketplaces.ebay_evidence import identity_key


def fingerprint(item):
    # No seller identifiers, price, or raw description retained.
    fields = {k: item.get(k) for k in ('itemId', 'title', 'conditionId', 'lotSize',
        'itemGroupType', 'itemGroupHref', 'itemGroupId')}
    fields['aspects'] = sorted((str(a.get('name')), str(a.get('value')))
        for a in item.get('localizedAspects', []) if isinstance(a, dict))
    fields['country'] = (item.get('itemLocation') or {}).get('country')
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def approved(item, target, now=None):
    now = now or datetime.now(timezone.utc)
    for r in target.get('reviewed_listings', []):
        try:
            end = datetime.fromisoformat(r['expires_at'])
            reviewed = datetime.fromisoformat(r['reviewed_at'])
            if (r.get('reviewed') is True and r['item_id'] == item.get('itemId')
                    and r['identity_key'] == identity_key(target)
                    and r['fingerprint'] == fingerprint(item)
                    and reviewed.tzinfo and end.tzinfo
                    and reviewed <= now < end and 0 < (end-reviewed).total_seconds() <= 7*86400):
                return True
        except (KeyError, ValueError, TypeError):
            continue
    return False
