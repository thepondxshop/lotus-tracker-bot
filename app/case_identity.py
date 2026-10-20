"""Distinguish personal storage cases and collector sets from shipping cases."""
import re
import unicodedata

CASE_TYPES={'CASE','SEALED CASE','BOOSTER CASE'}

def personal_case_format(title):
    text=unicodedata.normalize('NFKD',str(title or '')).encode('ascii','ignore').decode().lower()
    text=re.sub(r'[-_]+',' ',text)
    if re.search(r'\b(?:play\s*mat|dice|damage\s+counter|can|pencil|pen)\s+(?:and\s+)?case\b|\bdice\s+and\s+case\b', text):
        return ('Accessory Case','ACCESSORY')
    if re.search(r'\b(?:attache\s+case|brief\s*case)\b',text):
        if re.search(r'\b(?:set|collection|booster)\b',text):return ('Collection Box','SEALED')
        return ('Accessory Case','ACCESSORY')
    # A named TCG display case is not automatically a personal display holder.
    # Require explicit booster wording or a numbered One Piece booster set.
    shipping_display = bool(re.search(r'\bdisplay case\b',text) and
        re.search(r'\bbooster\b|\bone piece\b.*\bop\s*\d{1,3}\b',text) and
        not re.search(r'\b(?:acrylic|protector|storage|empty|case only)\b',text))
    if shipping_display:return None
    if re.search(r'\b(?:card|(?<!commander )(?<!starter )(?<!structure )deck|accessory|storage|carrying|carry|display)\s+case\b|\bcase\s+only\b',text):
        return ('Card Case' if re.search(r'\b(?:card|deck)\s+case\b',text) else 'Accessory Case','ACCESSORY')
    if re.search(r'\bsleeves?\b',text):return ('Sleeves','ACCESSORY')
    return None

def normalize_case_event(event):
    result=personal_case_format(event.get('product_name') or event.get('title'))
    if not result:
        title=event.get('product_name') or event.get('title') or ''
        if str(event.get('product_type','')).upper()=='ACCESSORY CASE' and re.search(r'\bdisplay case\b',title,re.I):
            corrected=dict(event,product_type='Case',product_category='SEALED')
            corrected.pop('reference_evidence',None)
            return corrected
        return event
    typ,category=result
    # A mixed case of accessories is not automatically a sealed TCG shipping case.
    corrected=dict(event,product_type=typ,product_category=category)
    if str(event.get('product_type','')).upper() in CASE_TYPES:
        corrected.pop('reference_evidence',None)
    return corrected

def shipping_case_event(event):
    if personal_case_format(event.get('product_name') or event.get('title')):return False
    return str(event.get('product_type','')).strip().upper() in CASE_TYPES
