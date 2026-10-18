"""Require explicit GTS price-unit evidence; Each/default SKU is not consumer-unit proof."""
from urllib.parse import urlsplit
from decimal import Decimal, InvalidOperation
import re

LABELS={'single starter deck':'STARTER DECK','1 starter deck':'STARTER DECK',
        'single commander deck':'COMMANDER DECK','1 commander deck':'COMMANDER DECK',
        'single booster pack':'BOOSTER PACK','1 booster pack':'BOOSTER PACK',
        'booster box':'BOOSTER BOX','1 booster box':'BOOSTER BOX',
        'sealed case':'CASE','1 sealed case':'CASE',
        'booster bundle':'BOOSTER BUNDLE','1 booster bundle':'BOOSTER BUNDLE',
        'elite trainer box':'ELITE TRAINER BOX','1 elite trainer box':'ELITE TRAINER BOX'}

def is_gts(row):
    try:host=(urlsplit(str(row.get('source',''))).hostname or '').lower().removeprefix('www.')
    except ValueError:host=''
    return row.get('source_kind')=='GTS' or host=='gtsdistribution.com'

def label_type(label):
    return LABELS.get(' '.join(str(label or '').lower().split()))

def unit_valid(row,product_type=None):
    if not is_gts(row):return True
    e=row.get('unit_evidence')
    if not isinstance(e,dict) or e.get('schema')!='GTS_UOM1':return False
    typ=str(product_type or row.get('product_type','')).upper().replace('_',' ')
    if label_type(e.get('label'))!=typ or e.get('source')!=row.get('source'):return False
    if e.get('field')!='UomName' or row.get('derivation') is not None:return False
    try:
        x=Decimal(str(e.get('amount')));y=Decimal(str(row.get('amount')))
        return x.is_finite() and x>0 and x==y
    except (InvalidOperation,ValueError,TypeError):return False
