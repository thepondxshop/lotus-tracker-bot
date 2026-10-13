"""Read-only signing readiness. No network requests or secret output."""
import argparse
import json
from app.store_signing_status import signing_status

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('domains', nargs='+', help='Exact domains from /shopifystatus')
    args = parser.parse_args()
    for domain in args.domains:
        print('LOTUS STORE SIGNING | ' + json.dumps({'store': domain, **signing_status(domain)}))
