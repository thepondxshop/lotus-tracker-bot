"""REG3: destination selection only; existing alert entitlements are retained."""
import os

GROUPS = {'CA':'CANADA','CANADA':'CANADA','JP':'JAPAN','JAPAN':'JAPAN',
          'CN':'CHINA','CHINA':'CHINA'}
for _country in ('GB','UK','UNITED KINGDOM','DE','FR','IT','ES','SE','NO','FI','DK',
                 'NL','BE','AT','CH','IE','PT','PL','CZ','GR','LV','LT','EE','EU',
                 'HU','RO','BG','HR','SI','SK','LU','MT','CY','IS'):
    GROUPS[_country] = 'EUROPE'
for _country in ('KR','KOREA','SOUTH KOREA','TW','HK','SG','MY','TH','ID','PH','VN','AU','NZ'):
    GROUPS[_country] = 'ASIA_PACIFIC'
EARLY = {'DISCOVERED','PAGE_LIVE','COMING_SOON'}
DEALS = {'PRICE_DROP','PRICE_INCREASE','PRICE_ERROR'}
STOCK = {'STOCK_AVAILABLE','RESTOCK','SOLD_OUT'}
VARIABLES = tuple('CHANNEL_DROPS_' + g for g in sorted(set(GROUPS.values()))) + (
    'CHANNEL_GLOBAL_EARLY_PAGE_DETECTION', 'CHANNEL_GLOBAL_DEALS')

def enabled(env):
    return env.get('REGIONAL_DROPS_ENABLED','true').strip().lower() in {'true','1','yes','on'}

def channel_id(value):
    value = str(value or '').strip()
    return int(value) if value.isascii() and value.isdigit() and int(value)>0 else None

def route_decision(event, alert_type, minimum_tier, environ=None):
    env = os.environ if environ is None else environ
    result = {'version':'REG3', 'channel_id':None, 'variable':None}
    def finish(reason):
        return {**result, 'reason':reason}
    if not enabled(env): return finish('DISABLED')
    if minimum_tier != 'Premium': return finish('KEEP_EXISTING_TIER_ROUTE')
    region = str(event.get('region') or '').strip().upper()
    if region in {'US','USA','UNITED STATES','UNITED STATES OF AMERICA'}:
        return finish('US_EXISTING_ROUTE')
    group = GROUPS.get(region)
    if not group: return finish('UNMAPPED_REGION_EXISTING_ROUTE')
    event_type = event.get('event_type')
    if event_type in EARLY and alert_type in {'page_live','international'}:
        variable = 'CHANNEL_GLOBAL_EARLY_PAGE_DETECTION'
    elif event_type in DEALS and alert_type in {'deal','international'}:
        variable = 'CHANNEL_GLOBAL_DEALS'
    elif event_type in STOCK and alert_type in {'shopify','international'}:
        variable = 'CHANNEL_DROPS_' + group
    else:
        return finish('KEEP_SPECIALIZED_ROUTE')
    result['variable'] = variable
    result['channel_id'] = channel_id(env.get(variable))
    return finish('OVERRIDE' if result['channel_id'] else 'MISSING_DESTINATION_EXISTING_ROUTE')

def regional_channel(event, alert_type, minimum_tier, environ=None):
    return route_decision(event, alert_type, minimum_tier, environ)['channel_id']

def routing_status(environ=None):
    env = os.environ if environ is None else environ
    return {'version':'REG3','enabled':enabled(env),
            'destinations':{v:bool(channel_id(env.get(v))) for v in VARIABLES}}

if __name__ == '__main__':
    import json
    print('LOTUS REGIONAL CONFIG | ' + json.dumps(routing_status()))
