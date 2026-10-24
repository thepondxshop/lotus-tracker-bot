import hashlib
import json
from pathlib import Path
EXPECTED = {'tests/test_release1713.py': 'c367233017f99959827a36a33b2ab41b13e9078fcdd4ac7b049414a8315af846', 'app/version.py': '8ebd06a8d953356d3e37affb2dcbea0242680807bdec418210cb7f9cb36cd460', 'app/release_announcements.py': 'f71140a56d59d5344cfd7d781283ace5a00931829496cdd42cecf4c16811c368'}
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
    print(json.dumps(dict(version='1.7.13',scope='CHANGED_FILES_ONLY',state='FAIL' if failures else 'PASS',files_checked=len(EXPECTED),failures=failures,alerts_sent=0,database_modified=False,live_delivery_verified=False),indent=2))
    raise SystemExit(bool(failures))
