"""Verify RELEASE-DEFAULT1 only. Does not certify earlier batches or live delivery."""
import ast
import hashlib
import json
from pathlib import Path

EXPECTED = {
 "app/release_catalog/calendar_commands.py": "50463dfe68f2ddf051e7985a590e45571fc9cd6500f1e67f7b7033381b3600fc",
 "app/release_catalog/calendar_runtime.py": "e235e10239b94d239149e13f6a7e64bd31efcba229d37f6def36a8936c67a785",
 "app/release_catalog/calendar_store.py": "94e74d36632465ef2ab14ab0959651941e7bd6bd199e56aa67e9066a0541bade",
 "app/release_catalog/calendar_ui.py": "8ea0ade598684f570da86f08bac2e77c14a18f69aeb53ef84056fe1b941a21a2",
 "tests/test_release_default.py": "b3f46cd62c103d3610ef04b87c4cc7df99b2074746b92273e4e824e380aff5a1",
 "tests/test_schedule_worker.py": "a956cc9fc911634301ac218270d7005f1f26ee9a06ee8f0736532b08ee4fb230"
}
def check(root):
    failures=[]
    for name,expected in EXPECTED.items():
        path=root/name
        if not path.is_file():
            failures.append(dict(file=name,reason='MISSING'));continue
        raw=path.read_bytes()
        normalized=raw.replace(b'\r\n',b'\n').rstrip()+b'\n'
        if hashlib.sha256(normalized).hexdigest()!=expected:
            failures.append(dict(file=name,reason='DIFFERENT_VERSION'))
        try:ast.parse(raw,filename=name)
        except SyntaxError:failures.append(dict(file=name,reason='SYNTAX_ERROR'))
    return dict(state='FAIL' if failures else 'PASS',scope='RELEASE-DEFAULT1_ONLY',
                files_checked=len(EXPECTED),failures=failures,live_delivery_verified=False,
                alerts_sent=0,settings_changed=False)
if __name__=='__main__':
    result=check(Path(__file__).resolve().parent)
    print(json.dumps(result,indent=2))
    raise SystemExit(bool(result['failures']))
