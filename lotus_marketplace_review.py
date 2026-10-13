"""Validate locally supplied Mercari/Buyee observations; no network or Discord messages."""
import argparse
import json
from pathlib import Path
from app.marketplaces.review import review_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.feed.stat().st_size > 1048576:
            raise ValueError('FEED_TOO_LARGE')
        rows = json.loads(args.feed.read_text(encoding='utf-8'))
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('INVALID_FEED')
        print('LOTUS MARKETPLACE REVIEW | ' + json.dumps(review_rows(rows), ensure_ascii=True))
    except (ValueError, OSError, TypeError) as error:
        print('LOTUS MARKETPLACE REVIEW ERROR | ' + json.dumps({'type': type(error).__name__}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
