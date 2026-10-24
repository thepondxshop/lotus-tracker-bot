"""Verify changed release files without accessing services or changing settings."""
import hashlib
import json
from pathlib import Path
EXPECTED = {'lotus_ebay_setup.py': '0f1ef88eb43cfd2ad2edc6535700391dffd744a153dd61ee04ce09b5ada43c0e', 'app/version.py': 'ae1e013ac7bd8fa9f33755dd25c622f5810f43eebbde9fd1d05dd87f81e5bddb', 'tests/test_ebay1715.py': '92b42cc92216e055dfb742a4bf50c2bba66ad18c1773b9eca12e55f0bb201441'}

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
    print(json.dumps({'version':'1.7.15','scope':'CHANGED_FILES_ONLY','state':'FAIL' if failures else 'PASS',
        'files_checked':len(EXPECTED),'failures':failures,'alerts_sent':0,'database_modified':False,'live_delivery_verified':False},indent=2))
    return bool(failures)
if __name__=='__main__':raise SystemExit(main())
