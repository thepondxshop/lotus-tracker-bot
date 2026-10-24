import hashlib
import json
from pathlib import Path
EXPECTED = {'app/version.py': '8c4853c9ffebdbcd3676400fd1778d4798d808c892946cd7dee4d0caed315e02', 'tests/test_radar1714.py': '3fa57dde128902213359381c6c866e87f56ec85ace2a6b3aa68d50b68a7b06e5', 'app/release_catalog/tcg_scope.py': 'feb463634d09b1639d29562f695225060a28fd28f26841ed1e63211aa517ea0d'}
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
    print(json.dumps(dict(version='1.7.14',scope='CHANGED_FILES_ONLY',state='FAIL' if failures else 'PASS',files_checked=len(EXPECTED),failures=failures,alerts_sent=0,database_modified=False,live_delivery_verified=False),indent=2))
    raise SystemExit(bool(failures))
