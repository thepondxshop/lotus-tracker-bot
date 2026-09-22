"""Bounded direct checks share the adapter's domain lock and rate-limit cooldown."""
import math
import re
from urllib.parse import urlsplit

# Explicit owner-requested priority. Add handles here for other critical products.
PINNED_HANDLES = {
    'hobbiesville.com': ['one-piece-trading-cards-peb-01-premium-extra-booster-pre-order'],
}
DIRECT_CHECKS_PER_PASS = 2
AUTO_PRIORITY_LIMIT = 12
AUTO_PRIORITY_CACHE_SECONDS = 60
_cursor = {}


def handle_from_url(url, domain):
    try:
        p=urlsplit(url)
        if (p.hostname or '').lower().removeprefix('www.') != domain: return None
        match=re.fullmatch(r'/products/([a-zA-Z0-9_-]+)/?',p.path)
        return match.group(1) if match else None
    except (ValueError,TypeError): return None


def choose_handles(domain, automatic):
    pinned=list(dict.fromkeys(PINNED_HANDLES.get(domain,[])))
    automatic=[h for h in dict.fromkeys(automatic) if h not in pinned]
    # One pinned slot and one automatic slot, both round-robin if lists grow.
    chosen=[]
    for kind,values,slots in [('pinned',pinned,1),('automatic',automatic,1 if pinned else DIRECT_CHECKS_PER_PASS)]:
        if not values: continue
        start=_cursor.get((domain,kind),0)%len(values)
        count=min(slots,len(values))
        chosen.extend(values[(start+i)%len(values)] for i in range(count))
        _cursor[(domain,kind)]=(start+count)%len(values)
    return [h for h in chosen if re.fullmatch(r'[a-zA-Z0-9_-]+',h)]


def ajax_product(data, expected_handle):
    """Adapt public Ajax cents/prices without inventing unavailable variant state."""
    if not isinstance(data,dict) or data.get('handle')!=expected_handle or not data.get('id'): return None
    variants=data.get('variants')
    if not isinstance(variants,list) or not variants or len(variants)>=250: return None
    prepared=[]
    for v in variants:
        if not isinstance(v,dict) or type(v.get('available')) is not bool or not v.get('id'): return None
        price=v.get('price')
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<0: return None
        row=dict(v);row['price']=str(price/100)
        compare=row.get('compare_at_price')
        if isinstance(compare,(int,float)) and not isinstance(compare,bool) and math.isfinite(compare): row['compare_at_price']=str(compare/100)
        prepared.append(row)
    result=dict(data)
    result['variants']=prepared
    result['body_html']=data.get('description') or ''
    result['product_type']=data.get('type') or ''
    result['images']=[{'src':x} if isinstance(x,str) else x for x in data.get('images',[]) if isinstance(x,(str,dict))]
    return result
