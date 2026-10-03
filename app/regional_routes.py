"""Optional regional destinations for ordinary paid stock alerts only."""
import os

GROUPS = {
    'CA': 'CANADA', 'CANADA': 'CANADA',
    'JP': 'JAPAN', 'JAPAN': 'JAPAN',
    'CN': 'CHINA', 'CHINA': 'CHINA',
}
for _country in ('GB','UK','DE','FR','IT','ES','SE','NO','FI','DK','NL','BE','AT','CH','IE','PT','PL','CZ','GR','LV','LT','EE','EU'):
    GROUPS[_country] = 'EUROPE'
for _country in ('KR','KOREA','SOUTH KOREA','TW','HK','SG','MY','TH','ID','PH','VN','AU','NZ'):
    GROUPS[_country] = 'ASIA_PACIFIC'

def regional_channel(event, alert_type, minimum_tier, environ=None):
    env = os.environ if environ is None else environ
    if env.get('REGIONAL_DROPS_ENABLED', '').lower() != 'true': return None
    if alert_type not in {'shopify', 'international'} or minimum_tier != 'Premium': return None
    if event.get('event_type') not in {'STOCK_AVAILABLE','RESTOCK','SOLD_OUT'}: return None
    group = GROUPS.get(str(event.get('region') or '').strip().upper())
    value = env.get('CHANNEL_DROPS_' + group, '') if group else ''
    return int(value) if str(value).isdigit() and int(value) > 0 else None
