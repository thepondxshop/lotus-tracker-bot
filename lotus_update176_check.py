"""Verify the changed Python files in 1.7.6 without starting the bot."""
import ast
import hashlib
import json
from pathlib import Path

EXPECTED={
    'app/member_xp.py':'27f20c3a98920844a944848e985485beb6a588c668e04c1dec9462fe15609136',
    'app/riot_news.py':'28225907e6a6bfae4b6d341775e07e1e1ce0092236d4c1f65e051883c01f1c11',
    'app/riot_drawing_notices.py':'fba01f5f97c8b468f6764cdb5e2c3bbae1c1c9a30864093f0975855f353f5f70',
    'app/version.py':'de52b11a5fc4cb35af60985102f203581b71f92112be81475719da6df20c19fb',
    'lotus_launch_audit.py':'28f0367e96d7363c83f31f4800a168c69da64463a6ad0936e88c45f6d15d862b',
    'lotus_riot_drawing_check.py':'71c6bee1212e2817a1a7af6e08c9bfd49018126f4627d3972f1dc9d47e58d811',
    'tests/test_launch176.py':'3adf27a32361373c1800aee309907bbfc521dca5c66bc2b7e092276b79a6fa62',
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
    return dict(version='1.7.6',scope='CHANGED_FILES_ONLY',state='FAIL' if failures else 'PASS',
                files_checked=len(EXPECTED),failures=failures,alerts_sent=0,live_delivery_verified=False)

if __name__=='__main__':
    result=check(Path(__file__).resolve().parent)
    print(json.dumps(result,indent=2));raise SystemExit(bool(result['failures']))
