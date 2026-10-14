"""PRICE1 channel/config simulation only. No delivery or permissions checks."""
import json
from app.price_policy import destination
from app.international_channels import configuration
for region in ('US','JP'):
    base=dict(event_type='PRICE_DROP',price=99.99,old_price=100,currency='USD',region=region,product_family='GLOBAL_STANDARD',in_stock=True)
    for kind in ('PRICE_DROP','DEAL','CASE_DEAL','PRICE_INCREASE'):
        e=dict(base)
        if kind in {'DEAL','CASE_DEAL'}:
            e.update(price=90,reference_evidence=dict(amount=100,currency='USD',scope='EXACT_PRODUCT',confidence='HIGH',kind='MSRP',source='CHECK_FIXTURE',region=region,family='GLOBAL_STANDARD'))
        if kind=='CASE_DEAL': e['product_type']='CASE'
        if kind=='PRICE_INCREASE': e.update(event_type='PRICE_INCREASE',price=101)
        print('LOTUS PRICE POLICY CHECK | '+json.dumps({'region':region,'fixture':kind,**destination(e)}))
print('LOTUS MARKETPLACE CHANNELS | '+json.dumps(configuration()))
