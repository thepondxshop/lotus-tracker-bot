"""Narrow alternative identity evidence for the reviewed English 151 bundle pilot.
Never invent a GTIN. Only missing identifiers can use this path; conflicts cannot.
"""
import re
import unicodedata

def words(value):
    return ' '.join(unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower().split())

def multi_field_identity(item,target):
    if (target.get('id')!='pokemon-151-bundle-en' or target.get('reviewed') is not True
            or target.get('game')!='Pokemon' or target.get('gtin')!='820650853210' or target.get('quantity')!=1
            or target.get('aspects')!={'Language':'English','Configuration':'Box'}):return False
    aspects={}
    for a in item.get('localizedAspects') or []:
        if not isinstance(a,dict):continue
        key=words(a.get('name'));value=words(a.get('value'))
        if key in aspects and aspects[key]!=value:return False
        aspects[key]=value
    if aspects.get('language')!='english' or aspects.get('configuration')!='box':return False
    if aspects.get('game') not in {'pokemon','pokemon tcg','pokemon trading card game'}:return False
    if str(item.get('conditionId'))!='1000':return False
    title=words(item.get('title',''))
    if not all(re.search(r'\b'+p+r'\b',title) for p in ('pokemon','151','booster bundle','sealed')):return False
    if re.search(r'\b(?:unsealed|opened|resealed|loose|japanese|korean|chinese|lot|case|display|empty|proxy|replica|repack|mystery)\b|\b(?:no box|box only|not sealed|packs only)\b',title):return False
    count=aspects.get('number of packs')
    if count is not None and count not in {'6','six','6 packs','six packs'}:return False
    if count is None and not re.search(r'\b6\s+(?:booster\s+)?packs\b',title):return False
    # This is listing evidence, not a publisher GTIN match. The existing lot,
    # condition, variation, seller, stock, auction and price checks still follow.
    return True
