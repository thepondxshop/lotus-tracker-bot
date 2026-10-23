"""Offline reminder preview; no source fetch, DB access or Discord sends."""
import argparse
import json
from datetime import datetime,timezone
from app.riot_drawing_notices import due_notices

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--at',help='Timezone-aware ISO timestamp for a simulated preview')
    args=parser.parse_args()
    now=datetime.fromisoformat(args.at.replace('Z','+00:00')) if args.at else datetime.now(timezone.utc)
    if now.tzinfo is None:parser.error('--at requires an explicit timezone')
    print(json.dumps(dict(preview_only=True,simulated=bool(args.at),at=now.isoformat(),
        notices=[dict(product=r['product']['title'],kind=r['kind'],image=r['product']['image'])
                 for r in due_notices(now)],source_rechecked=False,stock_verified=False,alerts_sent=0),indent=2))
