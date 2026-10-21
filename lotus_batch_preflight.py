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
        if hashlib.sha256(raw).hexdigest()!=expected:failures.append({'file':name,'reason':'DIFFERENT_VERSION'})
        if name.endswith('.py'):
            try:ast.parse(raw,filename=name)
            except SyntaxError:failures.append({'file':name,'reason':'SYNTAX_ERROR'})
    return dict(state='FAIL' if failures else 'PASS',files_checked=len(manifest['files']),failures=failures,
                live_delivery_verified=False,alerts_sent=0,settings_changed=False)

if __name__=='__main__':
    result=check(Path(__file__).resolve().parent)
    print(json.dumps(result,indent=2));raise SystemExit(1 if result['failures'] else 0)
