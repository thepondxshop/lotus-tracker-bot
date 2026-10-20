"""Cross-store capacity only; per-domain pacing remains authoritative."""
import os

def shopify_scan_capacity(environ=None):
    env=os.environ if environ is None else environ
    try: value=int(env.get('SHOPIFY_MAX_CONCURRENT_STORES','8'))
    except (ValueError,TypeError): value=8
    return max(1,min(12,value))
