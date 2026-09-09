"""Major-retailer catalog for Lotus Step 6K-2A."""

from .base import MajorRetailerDefinition
from .registry import register_major_retailer_definition

VERSION = "1.2.0"

# Definitions only. Nothing here activates a retailer or performs network requests.
BUILTIN_MAJOR_RETAILERS = (
    MajorRetailerDefinition(
        key="target",
        display_name="Target",
        domain="target.com",
        region="US",
        enabled=False,
        notes="Target integration parked pending an approved official feed/partner path.",
    ),
    MajorRetailerDefinition(
        key="walmart",
        display_name="Walmart",
        domain="walmart.com",
        region="US",
        enabled=False,
    ),
    MajorRetailerDefinition(
        key="best_buy",
        display_name="Best Buy",
        domain="bestbuy.com",
        region="US",
        enabled=False,
    ),
    MajorRetailerDefinition(
        key="gamestop",
        display_name="GameStop",
        domain="gamestop.com",
        region="US",
        enabled=False,
    ),
    MajorRetailerDefinition(
        key="premium_bandai",
        display_name="Premium Bandai",
        domain="p-bandai.com",
        region="US",
        enabled=False,
        notes=(
            "Official Bandai direct storefront. Dedicated adapter planned for "
            "TCG/collectibles preorders, limited releases, closing-soon windows, "
            "page-live detection, and verified availability."
        ),
    ),
    MajorRetailerDefinition(
        key="boxlunch",
        display_name="BoxLunch",
        domain="boxlunch.com",
        region="US",
        enabled=False,
        notes="Dedicated collectibles retailer adapter planned; remains inactive until silent validation passes.",
    ),
    MajorRetailerDefinition(
        key="hot_topic",
        display_name="Hot Topic",
        domain="hottopic.com",
        region="US",
        enabled=False,
        notes="Dedicated collectibles retailer adapter planned; remains inactive until silent validation passes.",
    ),
    MajorRetailerDefinition(
        key="costco",
        display_name="Costco",
        domain="costco.com",
        region="US",
        enabled=False,
    ),
    MajorRetailerDefinition(
        key="sams_club",
        display_name="Sam's Club",
        domain="samsclub.com",
        region="US",
        enabled=False,
    ),
    MajorRetailerDefinition(
        key="amazon_us",
        display_name="Amazon US",
        domain="amazon.com",
        region="US",
        enabled=False,
        affiliate_provider="amazon_associates",
        notes="Dedicated Amazon architecture planned; not treated as a generic big-box adapter.",
    ),
    MajorRetailerDefinition(
        key="amazon_jp",
        display_name="Amazon Japan",
        domain="amazon.co.jp",
        region="JP",
        enabled=False,
        affiliate_provider="amazon_associates_jp",
        notes="Dedicated Japan-region Amazon architecture planned.",
    ),
)


def load_builtin_major_retailer_definitions() -> None:
    for definition in BUILTIN_MAJOR_RETAILERS:
        register_major_retailer_definition(definition)
