"""Named destinations for planned pipelines; registration does not enable scans."""
import os

DESTINATIONS = {
    'forwarders': ('CHANNEL_FORWARDER_OPPORTUNITIES', None),
    'landed_cost': ('CHANNEL_LANDED_COST_DEALS', None),
    'ebay': ('CHANNEL_EBAY_INTELLIGENCE', 'Premium'),
    'mercari_us': ('CHANNEL_MERCARI_INTELLIGENCE', 'Premium'),
    'buyee_jp': ('CHANNEL_BUYEE_INTELLIGENCE', 'Premium+'),
    'market_prices': ('CHANNEL_MARKET_PRICES', None),
}

def configuration():
    result = {}
    for key, (variable, tier) in DESTINATIONS.items():
        value = os.getenv(variable, '').strip()
        result[key] = {'variable': variable,
                       'configured': value.isascii() and value.isdigit() and int(value) > 0,
                       'minimum_tier': tier,
                       'pipeline_enabled': False}
    return result
