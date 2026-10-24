import hashlib
import json
from pathlib import Path
EXPECTED = {'app/version.py': '3a7a30b869719571c9e7919d22b520bdfd6a3e5a8de2334e98b9738e0121195b', 'app/shopify_request_gate.py': '3ac186c4a6286f96a62d0af76b8ed2c697bb930120bdd712892ba5650f9dcd6b', 'app/config.py': '075dc472fa949d3530bd04ea34e321335f3328591c6b6a7a09aa74e07bc76e5b', 'app/shopify_adapter.py': '2de6edc3bbde571c0d00a3726a1f0af622b75b96a3d625ca67c5c218239be352', 'tests/test_shopify179.py': 'b51f0129b5593d9b8835d54f5fdd7bcf289f749292a524041db886a53a4c0c13'}
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
    print(json.dumps(dict(version='1.7.10',scope='CHANGED_FILES_ONLY',state='FAIL' if failures else 'PASS',files_checked=len(EXPECTED),failures=failures,alerts_sent=0,database_modified=False,live_delivery_verified=False),indent=2))
    raise SystemExit(bool(failures))
