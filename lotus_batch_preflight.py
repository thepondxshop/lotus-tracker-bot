"""Check this update's exact deployed files without importing or starting the bot."""
import ast
import hashlib
import json
from pathlib import Path

def check(root):
    manifest=json.loads((root/'launch-batch-manifest.json').read_text())
    failures=[]
    for name,expected in manifest['files'].items():
        path=root/name
        if not path.is_file():failures.append({'file':name,'reason':'MISSING'});continue
        raw=path.read_bytes()
        actual=hashlib.sha256(raw).hexdigest()
        if actual!=expected:
            failures.append({'file':name,'reason':'DIFFERENT_VERSION',
                             'expected_sha256':expected,'actual_sha256':actual,
                             'crlf_present':b'\r\n' in raw,
                             'lf_sha256':hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()})
        if name.endswith('.py'):
            try:ast.parse(raw,filename=name)
            except SyntaxError:failures.append({'file':name,'reason':'SYNTAX_ERROR'})
    return dict(state='FAIL' if failures else 'PASS',root=str(root.resolve()),files_checked=len(manifest['files']),failures=failures,
                live_delivery_verified=False,alerts_sent=0,settings_changed=False)

if __name__=='__main__':
    result=check(Path(__file__).resolve().parent)
    print(json.dumps(result,indent=2));raise SystemExit(1 if result['failures'] else 0)
