"""MERCH1: explicit building products must not borrow licensed TCG identities."""
import re

def building_product(title=None, product_type=None):
    # Deliberately inspect title/type only, not broad retailer navigation/tags.
    text=f'{title or ""} {product_type or ""}'
    return bool(re.search(r'\blego\b|\bbuilding[ -](?:blocks?|bricks?|sets?)\b',text,re.I))
