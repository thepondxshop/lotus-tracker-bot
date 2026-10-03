"""Read-only Railway configuration check. No network requests or secrets printed."""
import json
import os
from app.regional_routes import routing_status

print('LOTUS REGIONAL CONFIG | ' + json.dumps(routing_status()))
result = {'enabled': os.getenv('LOTUS_BOT_AUTH_ENABLED', '').strip().lower() == 'true',
          'origin_present': bool(os.getenv('LOTUS_BOT_AUTH_ORIGIN', '').strip()),
          'private_key_present': bool(os.getenv('LOTUS_BOT_AUTH_PRIVATE_KEY', '').strip()),
          'stores': {}}
try:
    from lotus_bot_auth import allowed_stores, operator_request_headers
    hosts = allowed_stores()
    for host in ('sagaconcepts.com','hobbiesville.com','dragoneyegaming.net',
                 'flipsidegaming.com','store.401games.ca'):
        entry = {'allowlisted': host in hosts}
        try:
            headers = operator_request_headers('https://' + host + '/products.json', host)
            entry['signature_headers_attached'] = bool(headers.get('Signature') and headers.get('Signature-Input'))
        except Exception as error:
            entry['error_type'] = type(error).__name__
        result['stores'][host] = entry
except Exception as error:
    result['error_type'] = type(error).__name__
print('LOTUS SIGNING CONFIG | ' + json.dumps(result))
