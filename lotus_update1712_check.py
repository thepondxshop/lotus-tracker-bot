import hashlib
import json
from pathlib import Path
EXPECTED = {'tests/test_community177.py': 'c2a472c0a03ac3220d275a2097bd6ad9450318fa93a5f92b815c15dd35730950', 'tests/test_launch_batch.py': 'bf1b3a00fcd5d7017f432f7e0124e5dbe5f50aae05d737c1135d6cdf678b0ef0', 'tests/test_launch176.py': 'ca74b1b3d4a3f08a64aef72e8d27cfe81713046217b9e7f3fc7b5f386067908b', 'tests/test_xp1712.py': '63ddd85a4d504e00b995ecbcd31d94954d70778ee5702f601c82b2d6254e6911', 'app/version.py': 'a2f95eaeb13c44e485afcf85e24a08813b73310fb05cada87d42b63c46295784', 'app/member_xp.py': '930d98f919243736b4a53c065b48397d7eb3ae2cb93af3293626fdcd1dc1495f'}
def normalize(data):
    return data.replace(b'\r\n',b'\n').rstrip(b'\n')+b'\n'
if __name__=='__main__':
    root=Path(__file__).resolve().parent
    failures=[]
    for name,expected in EXPECTED.items():
        p=root/name
        if not p.is_file(): failures.append(dict(file=name,reason='MISSING'))
        elif hashlib.sha256(normalize(p.read_bytes())).hexdigest()!=expected:
            failures.append(dict(file=name,reason='DIFFERENT_VERSION'))
    print(json.dumps(dict(version='1.7.12',scope='CHANGED_FILES_ONLY',state='FAIL' if failures else 'PASS',files_checked=len(EXPECTED),failures=failures,alerts_sent=0,database_modified=False,live_delivery_verified=False),indent=2))
    raise SystemExit(bool(failures))
