"""Check or atomically import reviewed exact-product references. No alerts."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from app.deal_references import load

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--import-file')
    args = p.parse_args()
    dest = Path(os.getenv('LOTUS_DEAL_REFERENCES_FILE', '/app/app/deal-references.json'))
    rows = load(args.import_file or dest)
    if args.import_file:
        if dest.exists() and json.loads(dest.read_text()) != rows:
            backup = dest.with_name(dest.name + '.backup-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f'))
            backup.write_bytes(dest.read_bytes())
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=dest.parent, delete=False) as f:
            json.dump(rows, f, indent=2); f.write('\n'); temp = f.name
        os.replace(temp, dest)
    now = datetime.now(timezone.utc)
    print(json.dumps({'path': str(dest), 'exists': dest.exists(), 'references': len(rows),
        'unexpired': sum(datetime.fromisoformat(r['expires_at']) > now for r in rows),
        'alerts_sent': 0, 'automatic_distributor_feed': 'DATABASE_BACKED_CHECK_WITH_lotus_distributor_sync_check.py', 'distributor_sync_enabled': os.getenv('LOTUS_DISTRIBUTOR_SYNC_ENABLED','true').lower() in {'true','1','yes'}}, indent=2))
