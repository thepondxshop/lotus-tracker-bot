"""Exact public product-page evidence; no account, private API, or stock claims."""
import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

HOSTS={'target':'target.com','walmart':'walmart.com','gamestop':'gamestop.com','best_buy':'bestbuy.com'}
PATHS={'target':r'/p/.+/-/A-\d+', 'walmart':r'/ip/(?:[^/]+/)?\d+',
       'gamestop':r'/.+/\d+\.html','best_buy':r'/(?:product/.+/[A-Za-z0-9]+|site/.+/\d+\.p)'}

def product_url(retailer,url):
    if retailer not in HOSTS or not isinstance(url,str): raise ValueError('UNSUPPORTED_RETAILER')
    p=urlsplit(url)
    if (p.scheme!='https' or p.hostname not in {HOSTS[retailer],'www.'+HOSTS[retailer]}
            or p.username or p.password or p.port not in (None,443)
            or not re.fullmatch(PATHS[retailer],p.path.rstrip('/'))):
        raise ValueError('EXACT_PUBLIC_PRODUCT_URL_REQUIRED')
    return urlunsplit(('https','www.'+HOSTS[retailer],p.path.rstrip('/'),'',''))

class JsonLD(HTMLParser):
    def __init__(self):
        super().__init__();self.active=False;self.parts=[];self.blocks=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script':
            self.active=dict(attrs).get('type','').lower()=='application/ld+json';self.parts=[]
    def handle_data(self,data):
        if self.active:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.blocks.append(''.join(self.parts));self.active=False

def nodes(value):
    if isinstance(value,list):
        for row in value:yield from nodes(row)
    elif isinstance(value,dict):
        yield value
        yield from nodes(value.get('@graph',[]))

def parse_product(retailer,url,body):
    url=product_url(retailer,url)
    parser=JsonLD();parser.feed(body)
    matches=[]
    for block in parser.blocks:
        try:data=json.loads(block)
        except (ValueError,RecursionError):continue
        for row in nodes(data):
            typ=row.get('@type');types=typ if isinstance(typ,list) else [typ]
            if 'Product' not in types:continue
            try:match=product_url(retailer,row.get('url'))==url
            except ValueError:match=False
            if match:matches.append(row)
    if len(matches)!=1:raise ValueError('EXACT_PRODUCT_JSONLD_MISSING_OR_AMBIGUOUS')
    row=matches[0];title=row.get('name')
    if not isinstance(title,str) or not title.strip():raise ValueError('PRODUCT_TITLE_MISSING')
    offers=row.get('offers');offers=offers if isinstance(offers,list) else [offers]
    # Multiple sellers/variants, AggregateOffer, membership prices and absent
    # seller evidence must not borrow a single apparently cheap price.
    if len(offers)!=1 or not isinstance(offers[0],dict):raise ValueError('AMBIGUOUS_OFFERS')
    offer=offers[0]
    if offer.get('@type')!='Offer':raise ValueError('DIRECT_OFFER_REQUIRED')
    seller=offer.get('seller',{})
    seller_name=seller.get('name','') if isinstance(seller,dict) else ''
    expected={'target':{'target'},'walmart':{'walmart','walmart.com'},
              'gamestop':{'gamestop'},'best_buy':{'best buy','bestbuy.com'}}[retailer]
    if str(seller_name).strip().lower() not in expected:raise ValueError('DIRECT_RETAILER_SELLER_UNVERIFIED')
    if offer.get('eligibleCustomerType') or offer.get('priceSpecification'):raise ValueError('CONDITIONAL_PRICE_NOT_SUPPORTED')
    if offer.get('priceCurrency')!='USD' or isinstance(offer.get('price'),bool):raise ValueError('PRICE_CURRENCY_INVALID')
    try:amount=Decimal(str(offer.get('price')))
    except InvalidOperation:raise ValueError('INVALID_PRICE')
    if not amount.is_finite() or not 0<amount<10000000:raise ValueError('INVALID_PRICE')
    return {'url':url,'title':title.strip(),'price':str(amount),'currency':'USD',
        'availability_known':False,'availability_state':'UNKNOWN','seller_verified':True,
        'note':'Public structured page price; online/local stock not verified'}
