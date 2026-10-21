"""Check installed alert wiring without a database connection or Discord sends."""
import ast
import asyncio
import json
from pathlib import Path
from app.cart_buttons import build_cart_view
from app.case_identity import shipping_case_event
from app.tcg_identity import non_tcg_stationery

async def main():
    path=Path(__file__).resolve().parent/'app'/'worker.py'
    tree=ast.parse(path.read_text())
    route=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='route_event_to_discord')
    wired=any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='send'
        and any(k.arg=='embed' for k in n.keywords)
        and any(k.arg=='view' and isinstance(k.value,ast.Call) and getattr(k.value.func,'id',None)=='build_cart_view' for k in n.keywords)
        for n in ast.walk(route))
    view=build_cart_view(dict(source_type='shopify',product_url='https://example.com/products/test',
                             cart_base_url='https://example.com',variant_id='123',purchase_limit=5))
    checks=dict(worker_send_has_cart_view=wired,limit_five_buttons=[b.label for b in view.children],
        dice_case_blocked=not shipping_case_event(dict(product_name='One Piece Dice and Case',product_type='Case')),
        frenda_suppressed=non_tcg_stationery('Pokemon Frenda Folder 18-Pick Organizer Case'))
    ok=wired and checks['limit_five_buttons']==['Add 1','Add 2','Add 4','Add 5'] and checks['dice_case_blocked'] and checks['frenda_suppressed']
    print(json.dumps(dict(state='PASS' if ok else 'FAIL',**checks,alerts_sent=0,live_delivery_verified=False)))
    if not ok:raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
