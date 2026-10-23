"""Changed-files verification only; no network, database or Discord writes."""
import ast,hashlib,importlib.util,json
from pathlib import Path
EXPECTED = {'main.py': '338b2497bb2ae21ac1357e0df469a87ac9cf7c9d1e3d742d3b74e04e2c216bb8', 'requirements.txt': '33779c93d18a71c1c3997aee3741e2577ddcf0d0abf35b485b2afedc9acbc9ef', 'START_HERE_1.7.7.md': '3669f5bb26d1cb87c9ff73a28820459b52f41ed1b50db30917107788d3d62d24', 'Lotus-Master-Milestones.md': 'b9b0b363b2b08b6009084f01593ded46ca351bb42a90b523b60492bc1dc1211a', 'tests/test_launch176.py': 'a440706a6bf57210348e5fd1a589992145499968990afa6b1a6909732f8eed5e', 'tests/test_community177.py': '4c6f9db7f7ad1858e9fbd505759db6697786379ac021c829d374a177025af73d', 'tests/test_launch_batch.py': '3684a6a00e241ad4658d7bb6d9e7e5dcf1cb1a90638fba0b283f086b01e26aaa', 'app/registered_games.py': 'b5f9274a1b04f9ecd75bc359196ee03249b938a9e86cc5e041943ddb55bcf908', 'app/distributor_references.py': '5ba5140598dacbecbf9557dd03968aa0037fb8ba6cb10d75e72e1f80db1d7946', 'app/config.py': 'e70f309f52693826093e94b567c2bf7cdcd45b7da0c67742db3d90a8a4d64c47', 'app/game_lifecycle.py': 'fc22c566f639415262dc6620cd00106199d3a2463cef7aa6ae217de01438fa20', 'app/collection_priority.py': 'e6a91bb5e9cdbed79258f082e3297bfb03dd1886e117bb61e49a3b716800e1a7', 'app/worker.py': '4752c17fc2e844493f5ff262c184239de641d1dd3976a5af429755c8dc95438b', 'app/member_xp.py': '0fdbd3bbe4ba99c6dd3787e12a03bf5f88de903ea558b99620f44111dbac65fc', 'app/community_support.py': 'e9abe7307e44253d88b47ba0cb4d9366e81a34219923c149cd1200eca9967d53', 'app/version.py': '2248650ac8e480f7cd32b93fab1aace3f4cd4b75dd5cc7d6e4f53bdb337b4b07', 'app/case_identity.py': 'c639798da0027e8d7555a9631cc8627260195c6b9d7bfbe6e79a62bd5f72be0d', 'app/marketplaces/ebay_search_plan.py': 'f0ccc28523ca788e3b2b1d221ab66874c1c34d4f2733fff1fcc6662a7e81d0a4'}
root=Path(__file__).resolve().parent
failures=[]
for name,expected in EXPECTED.items():
    p=root/name
    if not p.exists():failures.append(dict(file=name,reason='MISSING'));continue
    content=p.read_text().replace('\r\n','\n').rstrip()+'\n'
    if hashlib.sha256(content.encode()).hexdigest()!=expected:failures.append(dict(file=name,reason='DIFFERENT_VERSION'))
    if p.suffix=='.py':
        try:ast.parse(content)
        except SyntaxError:failures.append(dict(file=name,reason='SYNTAX_ERROR'))
for module in ('discord','sqlalchemy','asyncpg','aiohttp','bs4'):
    if importlib.util.find_spec(module) is None:failures.append(dict(module=module,reason='DEPENDENCY_MISSING'))
print(json.dumps(dict(version='1.7.7',scope='CHANGED_FILES_ONLY',state='FAIL' if failures else 'PASS',files_checked=len(EXPECTED),failures=failures,alerts_sent=0,database_modified=False,live_delivery_verified=False),indent=2))
raise SystemExit(bool(failures))
