"""Print destination readiness without tokens, messages or live network requests."""
import json
from app.international_channels import configuration
from app.operations_status import CHANNELS, channel_id

if __name__ == '__main__':
    print('LOTUS OPS CHANNELS | ' + json.dumps({key:bool(channel_id(key)) for key in CHANNELS}))
    print('LOTUS PLANNED CHANNELS | ' + json.dumps(configuration()))
    print('Configuration only; permissions and message delivery are not tested.')
