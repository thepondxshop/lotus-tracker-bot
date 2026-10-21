"""Link-only Shopify cart controls; no automatic purchase or stock assertion."""
import re
from urllib.parse import urlsplit
import discord
from app.smart_cart import build_smart_cart

QUANTITIES = (1, 2, 4, 5, 10, 12)

def safe_url(value):
    try:
        p = urlsplit(str(value or ''))
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return None
        return p
    except ValueError:
        return None

def cart_options(event):
    if str(event.get('source_type', '')).lower() != 'shopify':
        return {}
    product = safe_url(event.get('product_url'))
    base = safe_url(event.get('cart_base_url'))
    variant = str(event.get('variant_id') or '')
    if not product or not base or product.hostname.lower() != base.hostname.lower():
        return {}
    if not re.fullmatch(r'[1-9][0-9]*', variant):
        return {}
    limit = event.get('purchase_limit')
    if limit is not None:
        if isinstance(limit, bool) or not re.fullmatch(r'[1-9][0-9]*', str(limit)):
            return {}
        limit = int(limit)
    quantities = tuple(q for q in QUANTITIES if limit is None or q <= limit)
    result = build_smart_cart(product_url=event['product_url'], cart_base_url=event['cart_base_url'],
                              variant_id=variant, purchase_limit=limit, requested_quantities=quantities)
    # The legacy helper adds the exact limit too; retain only the requested shortcuts.
    return {q: url for q, url in result.cart_links.items() if q in quantities}

def build_cart_view(event):
    options = cart_options(event)
    if not options:
        return None
    view = discord.ui.View(timeout=None)
    for index, (quantity, url) in enumerate(options.items()):
        view.add_item(discord.ui.Button(label=f'Add {quantity}', style=discord.ButtonStyle.link,
                                       url=url, row=index // 5))
    return view
