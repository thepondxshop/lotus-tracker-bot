"""
Lotus Tracker Bot / PonDeX Trackers
Official Product Feed Registry
Version 1.0.0

Step 6J-3F12 — reusable official-feed source selection.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.affiliate_feeds.linkconnector import LinkConnectorProductFeed


def normalize_domain(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path).lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host.strip("./")


def get_official_feed_source(
    domain: Any,
    *,
    store_name: str | None = None,
):
    """
    Return a configured official feed source for a retailer when Lotus has an
    approved source integration. The Store.platform remains its storefront
    platform (e.g. Shopware); this layer augments discovery/price intelligence.
    """
    normalized = normalize_domain(domain)

    if normalized == "miniaturemarket.com":
        return LinkConnectorProductFeed(
            merchant_name="Miniature Market",
            merchant_id_env="LINKCONNECTOR_MINIATURE_MARKET_MERCHANT_ID",
            enabled_env="LINKCONNECTOR_MINIATURE_MARKET_FEED_ENABLED",
        )

    return None


async def probe_official_feed(
    domain: Any,
    *,
    store_name: str | None = None,
) -> dict[str, Any]:
    source = get_official_feed_source(domain, store_name=store_name)
    if source is None:
        return {
            "supported": False,
            "provider": None,
            "enabled": False,
            "configured": False,
            "last_error": "NO_OFFICIAL_FEED_INTEGRATION_FOR_DOMAIN",
        }

    probe = await source.probe()
    result = probe.to_dict()
    result["supported"] = True
    return result
