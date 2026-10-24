"""Verify changed release files without accessing services or changing settings."""
import hashlib
import json
from pathlib import Path
EXPECTED = {'lotus_ebay_listing_status.py': '3f37ef91d641652a988a696770226fdcc3dd611502c5c97a943f47c43c5a741f', 'app/version.py': 'e9dfcd133d18baa8e9fdfa49a5969c2ebdd86bf291a429a599ddb9eb5d3c3f2c', 'tests/test_listing1716.py': 'ac4110a5651b35d7c8915f7daed4798015585dcb4ea62e37014c356c92bfa920', 'app/marketplaces/ebay_live.py': '88c9bc5232c0185bce0d0c316029f9867f110773721f186d63e7855a4711bdd7', 'app/marketplaces/ebay_live_policy.py': '164c6a317fdd0617fcb17a77a1e3bb5933b7310fa889b4071b78171cb073332d', 'app/marketplaces/ebay_listing_alerts.py': '2d1481bac6ecf931307ec2d564aa9d90efc1c9b4ff55e30fc7441f5233627557'}

def main():
    root=Path(__file__).resolve().parent
    failures=[]
    for name, expected in EXPECTED.items():
        path=root/name
        if not path.is_file():
            failures.append({'file':name,'reason':'MISSING'}); continue
        data=path.read_bytes().replace(b'\r\n',b'\n').rstrip(b'\n')+b'\n'
        if hashlib.sha256(data).hexdigest()!=expected:
            failures.append({'file':name,'reason':'DIFFERENT_VERSION'})
    print(json.dumps({'version':'1.7.16','scope':'CHANGED_FILES_ONLY','state':'FAIL' if failures else 'PASS',
        'files_checked':len(EXPECTED),'failures':failures,'alerts_sent':0,'database_modified':False,'live_delivery_verified':False},indent=2))
    return bool(failures)
if __name__=='__main__':raise SystemExit(main())
