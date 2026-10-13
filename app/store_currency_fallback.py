"""Use operator-verified store currency at cold start; live cart metadata can refresh it."""
import json
import os
import re


def currency_for_store(domain, default):
    try:
        configured = json.loads(os.getenv('SHOPIFY_CURRENCY_FALLBACKS', '{}'))
        if not isinstance(configured, dict): return default
        normalized = str(domain).lower().removeprefix('www.').rstrip('/')
        value = configured.get(normalized)
        return value if isinstance(value, str) and re.fullmatch('[A-Z]{3}', value) else default
    except (ValueError, TypeError):
        return default
