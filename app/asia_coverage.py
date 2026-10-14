"""ASIA3: database coverage inventory; freshness is not availability or delivery."""
from datetime import datetime,timezone
from urllib.parse import urlsplit

TARGETS={
 'jumpichiban.com':'Jump Ichiban', 'meccha-japan.com':'Meccha Japan',
 'plazajapan.com':'Plaza Japan','japan-figure.com':'Japan Figure',
 'c-labo-online.jp':'Card Labo','1999.co.jp':'Hobby Search',
 'amiami.com':'AmiAmi','amazon.co.jp':'Amazon Japan',
 'nekotwo.com':'Nekotwo', 'kimstcgstore.com':"Kim’s TCG Store",
 'cardkingdom.co.kr':'CardKingdom Korea','pokemoncardcn.com':'Trendy Playing Cards',
 'rakuten.co.jp':'Rakuten Japan',
}

def host(value):
    try:
        p=urlsplit(value if '://' in str(value) else 'https://'+str(value))
        return (p.hostname or '').lower().removeprefix('www.')
    except ValueError: return ''

def summarize(records, now=None):
    now=now or datetime.now(timezone.utc)
    output=[]
    for domain,name in TARGETS.items():
        matches=[r for r in records if host(r.get('domain'))==domain]
        if not matches:
            output.append(dict(domain=domain,name=name,state='NOT_IN_STORE_REGISTRY'))
            continue
        for row in matches:
            at=row.get('last_product_seen')
            if isinstance(at,str):
                try: at=datetime.fromisoformat(at.replace('Z','+00:00'))
                except ValueError: at=None
            if isinstance(at,datetime) and at.tzinfo is None: at=at.replace(tzinfo=timezone.utc)
            age=(now-at).total_seconds() if isinstance(at,datetime) else None
            state=('INACTIVE' if not row.get('active') else
                   'NO_PRODUCT_RECORDS' if not row.get('product_count') else
                   'RECENT_PRODUCT_RECORD' if age is not None and 0<=age<=300 else 'STALE_OR_UNKNOWN_PRODUCT_RECORD')
            output.append({**row,'domain':domain,'state':state,'last_product_seen':at.isoformat() if isinstance(at,datetime) else None,'product_age_seconds':round(age,1) if age is not None else None})
    return output
