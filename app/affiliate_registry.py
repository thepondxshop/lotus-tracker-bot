"""Reviewed exact product links. No invented IDs, network requests or cart rewriting."""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HOSTS={'skimlinks':{'go.skimresources.com','go.redirectingat.com'},'sovrn':{'sovrn.co','redirect.viglink.com'},
       'linkconnector':{'www.linkconnector.com','linkconnector.com'},'ebay':{'rover.ebay.com'}}
_cache={'at':0.,'path':None,'rows':{}}

def valid_url(raw):
    if not isinstance(raw,str):return False
    try:
        p=urlsplit(raw)
        return isinstance(raw,str) and len(raw)<=2048 and p.scheme=='https' and bool(p.hostname) and not p.username and not p.password and p.port in (None,443) and not any(c.isspace() for c in raw)
    except (ValueError,TypeError):return False

def validate(rows):
    if not isinstance(rows,list) or len(rows)>10000:raise ValueError('AFFILIATE_ROWS_INVALID')
    result={}
    for row in rows:
        if not isinstance(row,dict):raise ValueError('AFFILIATE_ROW_INVALID')
        src,dst=row.get('product_url'),row.get('affiliate_url')
        if not valid_url(src) or not valid_url(dst):raise ValueError('AFFILIATE_URL_INVALID')
        provider=row.get('provider');host=urlsplit(dst).hostname
        if not isinstance(provider,str):raise ValueError('AFFILIATE_PROVIDER_INVALID')
        if provider=='direct':
            if host!=urlsplit(src).hostname:raise ValueError('DIRECT_DOMAIN_MISMATCH')
        elif host not in HOSTS.get(provider,set()):raise ValueError('AFFILIATE_PROVIDER_HOST_INVALID')
        if row.get('approved') is not True or row.get('discord_approved') is not True or not isinstance(row.get('store_name'),str) or not row['store_name'].strip():
            raise ValueError('AFFILIATE_APPROVAL_REQUIRED')
        try:
            expires=datetime.fromisoformat(row['expires_at'].replace('Z','+00:00'))
            if expires.tzinfo is None:raise ValueError()
        except (KeyError,TypeError,ValueError,AttributeError):raise ValueError('AFFILIATE_EXPIRY_REQUIRED')
        key=(src,row['store_name'].strip().casefold())
        if key in result:raise ValueError('AFFILIATE_DUPLICATE_PRODUCT')
        result[key]={**row,'expires':expires}
    return result

def registry_path():return Path(os.getenv('LOTUS_AFFILIATE_LINKS_FILE','app/affiliate-links.json'))

def load():
    path=registry_path();now=time.monotonic()
    if _cache['path']==str(path) and now-_cache['at']<60:return _cache['rows']
    rows={}
    try:
        if path.stat().st_size>2*1024*1024:raise ValueError('AFFILIATE_FILE_TOO_LARGE')
        rows=validate(json.loads(path.read_text()))
    except FileNotFoundError:pass
    except Exception as exc:print('LOTUS AFFILIATE | State=REGISTRY_REJECTED | Error='+type(exc).__name__,flush=True)
    _cache.update(at=now,path=str(path),rows=rows)
    return rows

def lookup(original_url,store_name):
    row=load().get((original_url,str(store_name or '').strip().casefold()))
    if row and datetime.now(timezone.utc)<row['expires']:
        return row['affiliate_url'],True
    return original_url,False
