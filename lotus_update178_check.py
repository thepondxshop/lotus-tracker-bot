"""Verify the 1.7.8 changed-files patch, without touching runtime state."""
import hashlib
import json
from pathlib import Path
EXPECTED = {'app/accessory_routes.py': 'dc7fbdd3653456f6db745b908b414238a3886577a83d937f551b553a9615c6db', 'app/collection_priority.py': 'fb35bde9f681fd9fedeb5422a39f92dfa9c87db317403142ead062fc6e2527ef', 'app/config.py': 'ab2f9019bc4e02344c6fd3af22298f6c58b734058376a9aa67c52e61c2b41388', 'app/distributor_references.py': '480c6e38af5bab132922abcba422eb576fb60af997c59692882b25e71a1c8d67', 'app/game_lifecycle.py': 'ce5669f4a2707b269f0350f9bebb2b7ab9ead8aff53bd8d049c1ca0ede243ecc', 'app/marketplaces/ebay_search_plan.py': 'e363cb4b946fd6489547fd6b9effd8ce439f1f941d2444ff6ca54a376abc9689', 'app/registered_games.py': '557827664f4373c19fd4f0fcae3515a3eeeb2d7e59afe90b0a0adc419a609345', 'app/version.py': '301532a9992c01a012edbbbd73ed65795eb006f9b183aa8ecf8a95dc8f3ff21d', 'tests/test_accessory178.py': 'cccb35bd41d364b33c0e231c93016a88cf8e4eb81719199bc30e9c14f0dbe710', 'tests/test_games178.py': '5ac290ac693b48baf8a50f3ffd6b6762bdbaf4e9396702e2ef374f458ce45b63'}
DOCS = ('START_HERE_1.7.7.md', 'START_HERE_1.7.8.md', 'Lotus-Master-Milestones.md')

def check(root):
    failures=[]
    for name, expected in EXPECTED.items():
        path=root/name
        if not path.is_file():
            failures.append(dict(file=name,reason='MISSING'))
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            failures.append(dict(file=name,reason='DIFFERENT_VERSION'))
    warnings=[dict(file=name,reason='DOCUMENTATION_MISSING') for name in DOCS if not (root/name).is_file()]
    return dict(version='1.7.8',scope='CHANGED_FILES_ONLY',state='FAIL' if failures else 'PASS',
                files_checked=len(EXPECTED),failures=failures,warnings=warnings,
                alerts_sent=0,database_modified=False,live_delivery_verified=False)

if __name__=='__main__':
    result=check(Path(__file__).resolve().parent)
    print(json.dumps(result,indent=2))
    raise SystemExit(1 if result['failures'] else 0)
