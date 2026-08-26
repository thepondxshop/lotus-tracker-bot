# =========================================================
# LOTUS AFFILIATE LINK SERVICE
# PonDeX Trackers
# Version 0.5.1
#
# IMPORTANT:
# Right now this is PASS-THROUGH ONLY.
#
# Later, supported retailer URLs will be converted into
# approved affiliate URLs here.
# =========================================================


AFFILIATE_DISCLOSURE = (
    "Affiliate link — PonDeX Trackers may earn a "
    "commission from qualifying purchases at no "
    "additional cost to you."
)


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

    affiliate_used is False until an approved
    affiliate integration exists for the retailer.
    """

    if not original_url:
        return original_url, False

    # =====================================================
    # FUTURE EXAMPLES
    #
    # Amazon Associates
    # eBay Partner Network
    # Impact
    # CJ Affiliate
    # Rakuten Advertising
    # Direct retailer affiliate programs
    #
    # Do not simply append arbitrary tracking codes.
    # Each retailer/network gets its own approved logic.
    # =====================================================

    final_url = original_url

    affiliate_used = False

    return (
        final_url,
        affiliate_used,
    )