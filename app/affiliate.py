# =========================================================
# LOTUS AFFILIATE LINK SERVICE
# PonDeX Trackers
# Version 0.6.0
#
# Step 6J-3F12 — Approved LinkConnector Feed Recognition
#
# Safety:
# - Never invent or append tracking parameters.
# - Only mark a URL as affiliate when it is already an approved
#   LinkConnector tracking URL supplied by the official feed.
# - All other retailer URLs remain pass-through.
# =========================================================

from urllib.parse import urlparse


AFFILIATE_DISCLOSURE = (
    "Affiliate link — PonDeX Trackers may earn a "
    "commission from qualifying purchases at no "
    "additional cost to you."
)


# =========================================================
# APPROVED NETWORK URL RECOGNITION
# =========================================================

def _is_linkconnector_tracking_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return False

    host = (parsed.netloc or "").lower().split(":", 1)[0]
    path = (parsed.path or "").lower()

    if host not in {"linkconnector.com", "www.linkconnector.com"}:
        return False

    # LinkConnector's tracking links commonly use ta.php. Keep this
    # deliberately strict so ordinary links are never mislabeled.
    return path.endswith("/ta.php") or path == "ta.php"


# =========================================================
# BUILD AFFILIATE URL
# =========================================================

def build_affiliate_url(
    original_url: str,
    store_name: str,
):
    """
    Returns:
        final_url
        affiliate_used

    The official LinkConnector product feed can return an already-built
    affiliate/tracking URL. Lotus preserves that exact URL and marks it for
    disclosure. It never fabricates tracking parameters itself.
    """

    if not original_url:
        return original_url, False

    final_url = str(original_url).strip()

    if _is_linkconnector_tracking_url(final_url):
        return final_url, True

    return final_url, False
