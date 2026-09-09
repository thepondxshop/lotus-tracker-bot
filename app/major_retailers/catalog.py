"""Major-retailer catalog for Lotus Step 6K-2C • Bot release 1.0.6."""

from .base import MajorRetailerDefinition
from .registry import register_major_retailer_definition

VERSION = "1.0.6"
STEP = "6K-2C"

# Definitions are roadmap/identity records only. Runtime promotion is handled
# by pipeline.py after silent validation; nothing here activates polling.
BUILTIN_MAJOR_RETAILERS = (
    MajorRetailerDefinition(
        key="target",
        display_name="Target",
        domain="target.com",
        region="US",
        enabled=False,
        notes=(
            "Parked. Redsky is retired because Railway receives Target CAPTCHA/403. "
            "Production requires an approved official feed/partner source."
        ),
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
            "Official Bandai direct storefront. Planned for TCG/collectibles "
            "preorders, limited releases, closing windows, page-live detection, "
            "and verified availability."
        ),
    ),
    MajorRetailerDefinition(
        key="five_below",
        display_name="Five Below",
        domain="fivebelow.com",
        region="US",
        enabled=False,
        notes="Planned major retailer; online discovery first, local stock later if trustworthy.",
    ),
    MajorRetailerDefinition(
        key="dicks_sporting_goods",
        display_name="DICK'S Sporting Goods",
        domain="dickssportinggoods.com",
        region="US",
        enabled=False,
        notes="Planned major retailer; online inventory first, local-store inventory remains separate.",
    ),
    MajorRetailerDefinition(
        key="boxlunch",
        display_name="BoxLunch",
        domain="boxlunch.com",
        region="US",
        enabled=False,
        notes="Collectibles retailer adapter planned; inactive until silent validation passes.",
    ),
    MajorRetailerDefinition(
        key="hot_topic",
        display_name="Hot Topic",
        domain="hottopic.com",
        region="US",
        enabled=False,
        notes="Collectibles retailer adapter planned; inactive until silent validation passes.",
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
        key="bjs",
        display_name="BJ's Wholesale Club",
        domain="bjs.com",
        region="US",
        enabled=False,
        notes="Planned for online plus later capability-separated local inventory.",
    ),
    MajorRetailerDefinition(
        key="walgreens",
        display_name="Walgreens",
        domain="walgreens.com",
        region="US",
        enabled=False,
        notes="Planned for online plus later capability-separated local inventory.",
    ),
    MajorRetailerDefinition(
        key="dollar_general",
        display_name="Dollar General",
        domain="dollargeneral.com",
        region="US",
        enabled=False,
        notes="Later local/in-store inventory candidate; exact quantity only if verifiable.",
    ),
    MajorRetailerDefinition(
        key="family_dollar",
        display_name="Family Dollar",
        domain="familydollar.com",
        region="US",
        enabled=False,
        notes="Later local/in-store inventory candidate; exact quantity only if verifiable.",
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
    MajorRetailerDefinition(
        key="rakuten_jp",
        display_name="Rakuten Japan",
        domain="rakuten.co.jp",
        region="JP",
        enabled=False,
        notes=(
            "Japan marketplace planned for regional exclusives, V Jump/Saikyou Jump "
            "promo listings and related collectibles. Seller trust, US shipping/forwarder "
            "requirements and landed cost must remain explicit."
        ),
    ),
)


def load_builtin_major_retailer_definitions() -> None:
    for definition in BUILTIN_MAJOR_RETAILERS:
        register_major_retailer_definition(definition)
