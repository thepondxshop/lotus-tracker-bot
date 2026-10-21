"""Inspect approved-link configuration without exposing tracking links or sending alerts."""
import json
from collections import Counter
from datetime import datetime, timezone
from app.affiliate_registry import registry_path,validate
if __name__=='__main__':
    try:
        p=registry_path()
        if not p.exists():print(json.dumps(dict(state='NOT_CONFIGURED',approved_links=0,alerts_sent=0)))
        else:
            if p.stat().st_size>2*1024*1024:raise ValueError('FILE_TOO_LARGE')
            rows=validate(json.loads(p.read_text()));now=datetime.now(timezone.utc)
            print(json.dumps(dict(state='VALID',approved_links=len(rows),unexpired=sum(r['expires']>now for r in rows.values()),by_provider=dict(Counter(r['provider'] for r in rows.values())),alerts_sent=0)))
    except Exception as exc:
        print(json.dumps(dict(state='INVALID',error_type=type(exc).__name__,alerts_sent=0)));raise SystemExit(1)
