"""Verify changed release files without accessing services or changing settings."""
import hashlib
import json
from pathlib import Path
EXPECTED = {'app/version.py': 'b4a4240655c1ade7f270445d727e9281e853f0932ad39b14d0129c619594c106', 'tests/test_listing1717.py': 'dd9df55c318fa3601776dee8222d734adda73e0a92ae542f70efb9ade4ea4bad', 'app/marketplaces/ebay_listing_alerts.py': 'b54ec4cce9176927fc3d0a8717315a8a00bbe98338c4fa44254e54836a833d5c'}

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
    print(json.dumps({'version':'1.7.17','scope':'CHANGED_FILES_ONLY','state':'FAIL' if failures else 'PASS',
        'files_checked':len(EXPECTED),'failures':failures,'alerts_sent':0,'database_modified':False,'live_delivery_verified':False},indent=2))
    return bool(failures)
if __name__=='__main__':raise SystemExit(main())
