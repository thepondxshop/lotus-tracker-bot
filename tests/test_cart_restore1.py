import ast
import unittest
from pathlib import Path
from app.cart_buttons import cart_options, build_cart_view

class CartTests(unittest.IsolatedAsyncioTestCase):
    def event(self, **kw):
        return dict(dict(source_type='shopify', product_url='https://shop.example/products/test', cart_base_url='https://shop.example', variant_id='123', purchase_limit=None), **kw)
    async def test_default_buttons_and_rows(self):
        view=build_cart_view(self.event())
        self.assertEqual([b.label for b in view.children], ['Add 1','Add 2','Add 4','Add 5','Add 10','Add 12'])
        self.assertEqual([b.row for b in view.children], [0,0,0,0,0,1])
        self.assertTrue(view.children[-1].url.endswith('/cart/123:12'))
    async def test_limits(self):
        for limit, expected in [(1,[1]),(3,[1,2]),(4,[1,2,4]),(5,[1,2,4,5]),(10,[1,2,4,5,10]),(12,[1,2,4,5,10,12])]:
            self.assertEqual(list(cart_options(self.event(purchase_limit=limit))),expected)
    async def test_invalid_or_non_shopify(self):
        for change in [dict(source_type='ebay'),dict(variant_id=None),dict(variant_id='0'),dict(purchase_limit=True),dict(purchase_limit=1.5),dict(purchase_limit=0),dict(cart_base_url='https://other.example'),dict(cart_base_url='https://user:pass@shop.example'),dict(cart_base_url='http://shop.example')]:
            self.assertIsNone(build_cart_view(self.event(**change)))
    async def test_actual_primary_send_attaches_view(self):
        tree=ast.parse(Path('app/worker.py').read_text())
        sends=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='send' and any(k.arg=='embed' for k in n.keywords)]
        self.assertTrue(any(any(k.arg=='view' and isinstance(k.value,ast.Call) and getattr(k.value.func,'id',None)=='build_cart_view' for k in n.keywords) for n in sends))
