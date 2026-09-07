"""Planned major-retailer catalog for Lotus Step 6K-1A."""

from .base import MajorRetailerDefinition
from .registry import register_major_retailer_definition

VERSION = "1.0.0"

# These are definitions only. No retailer is activated by this file and no
# network requests are performed. Retailer-specific adapters are added and
# validated one milestone at a time.
BUILTIN_MAJOR_RETAILERS = (
    MajorRetailerDefinition(
        key="target",
        display_name="Target",
        domain="target.com",
        region="US",
        enabled=False,
        notes="First Step 6K production adapter; online/nationwide scope before local-store inventory.",
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
