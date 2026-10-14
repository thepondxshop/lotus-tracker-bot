"""Validate one locally reviewed marketplace opportunity; never sends alerts."""
import argparse
import json
from pathlib import Path
from app.marketplaces.opportunity import evaluate
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed',type=Path,required=True)
    args=parser.parse_args()
    if args.feed.stat().st_size>1048576: raise SystemExit('Feed exceeds 1 MB')
    row=json.loads(args.feed.read_text())
    if not isinstance(row,dict): raise SystemExit('Expected one JSON object')
    print('LOTUS OPPORTUNITY REVIEW | '+json.dumps(evaluate(row)))
