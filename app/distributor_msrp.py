"""Read-only public MSRP extraction. Observations are not approved references."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

HOSTS={'acdd.com','www.acdd.com','gtsdistribution.com','www.gtsdistribution.com','phdgames.com','www.phdgames.com','portal.phdgames.com'}
class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
    def handle_starttag(self,t,a):
        if t in ('script','style','noscript'):self.skip+=1
        if t in ('div','p','br','tr','td','li','h1','h2','h3','h4','section'):self.parts.append('\n')
    def handle_endtag(self,t):
        if t in ('script','style','noscript'):self.skip=max(0,self.skip-1)
        if t in ('div','p','tr','td','li','h1','h2','h3','h4','section'):self.parts.append('\n')
    def handle_data(self,d):
        if not self.skip:self.parts.append(d)
    def text(self):
        return '\n'.join(' '.join(l.split()) for l in ''.join(self.parts).splitlines() if l.strip())

def validate_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):
        raise ValueError('Use an HTTPS public ACD, GTS or PHD page')
    return url

def extract(url,html):
    validate_url(url)
    reader=Text();reader.feed(html);text=reader.text()
    text=re.split(r'(?im)^Recent posts\s*$',text,maxsplit=1)[0]
    if re.search(r'<title[^>]*>\s*(?:Access Denied|Just a moment|One moment)',html,re.I):
        return {'state':'ACCESS_CHALLENGE','observations':[]}
    markers=list(re.finditer(r'(?im)^(?:Item Code|SKU|Item\s*#)\s*:?\s*\n?\s*([A-Z0-9][A-Z0-9_-]{1,99})\b',text))
    rows=[]
    for i,m in enumerate(markers[:100]):
        start=markers[i-1].end() if i else 0
        prefix=text[start:m.start()]
        # PHD's Publisher line immediately follows its product title.
        before=prefix.split('Publisher:',1)[0].strip().splitlines()
        title=before[-1] if before else None
        stop=markers[i+1].start() if i+1<len(markers) else len(text)
        block=text[m.end():stop]
        prices=sorted(set(re.findall(r'(?i)\bMSRP\s*:?\s*\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)',block)))
        # Do not join ambiguous articles or use sale/wholesale prices as MSRP.
        if len(prices)!=1:
            rows.append({'sku':m[1],'state':'MSRP_MISSING_OR_AMBIGUOUS'});continue
        dates=sorted(set(re.findall(r'(?i)\b(?:Releases|Release Date\s*:)\s*([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{1,2}/\d{1,2}/\d{4})',block)))
        rows.append({'sku':m[1],'title_context':title,'msrp':prices[0].replace(',',''),
            'currency':'UNVERIFIED','release_date_text':dates[0] if len(dates)==1 else None,
            'source':url,'state':'PUBLIC_MSRP_OBSERVED','packaging_verified':False,'reference_ready':False})
    return {'state':'OBSERVATIONS_EXTRACTED' if rows else 'NO_SUPPORTED_PRODUCT_BLOCKS','observations':rows}
