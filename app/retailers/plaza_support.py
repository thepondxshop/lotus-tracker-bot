"""ASIA1: Plaza Japan's public HTML Product microdata and TCG categories."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, parse_qs
from decimal import Decimal, InvalidOperation
import re

CATEGORIES = (
 '/toys/trading-cards/other/', '/pokemon/pokemon-card-game-booster-boxes/',
 '/toys/trading-cards/one-piece/', '/toys/trading-cards/card-accessories/',
 '/toys/trading-cards/duel-masters/', '/toys/trading-cards/disney-lorcana/',
)
_STATE = {}

class Node:
 def __init__(self, tag='', attrs=()):
  self.tag=tag; self.attrs=dict(attrs); self.children=[]; self.parts=[]
 def walk(self):
  yield self
  for c in self.children: yield from c.walk()
 def text(self):
  return ' '.join(' '.join(n.parts) for n in self.walk()).strip()

class Tree(HTMLParser):
 def __init__(self, html):
  super().__init__(convert_charrefs=True); self.root=Node(); self.stack=[self.root]; self.feed(html)
 def handle_starttag(self,tag,attrs):
  n=Node(tag,attrs);self.stack[-1].children.append(n)
  if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:self.stack.append(n)
 def handle_startendtag(self,tag,attrs):
  self.handle_starttag(tag,attrs);self.handle_endtag(tag)
 def handle_endtag(self,tag):
  for i in range(len(self.stack)-1,0,-1):
   if self.stack[i].tag==tag:self.stack=self.stack[:i];break
 def handle_data(self,data):self.stack[-1].parts.append(data)

def host(url):return (urlsplit(url).hostname or '').lower() in {'plazajapan.com','www.plazajapan.com'}
def product_url(url):
 p=urlsplit(url)
 return host(url) and p.scheme=='https' and bool(re.fullmatch(r'/\d{13}/',p.path)) and not p.query

def values(node,prop):
 return {n.attrs.get('content') or n.attrs.get('src') or n.text()
         for n in node.walk() if n.attrs.get('itemprop')==prop}
def one(node,prop):
 v={x.strip() for x in values(node,prop) if x and x.strip()}
 return next(iter(v)) if len(v)==1 else None

def schema(html,url):
 if not product_url(url):return None
 nodes=list(Tree(html).root.walk())
 products=[n for n in nodes if n.attrs.get('itemtype','').rstrip('/').endswith('/Product') and 'itemscope' in n.attrs]
 if len(products)!=1:return None
 p=products[0]
 titles=[n.text() for n in p.walk() if n.tag=='h1' and n.attrs.get('itemprop')=='name']
 offers=[n for n in p.walk() if n.attrs.get('itemprop')=='offers' and n.attrs.get('itemtype','').rstrip('/').endswith('/Offer')]
 if len(titles)!=1 or len(offers)!=1:return None
 o=offers[0]; identity=one(o,'url')
 if not identity or not product_url(identity) or urlsplit(identity).path!=urlsplit(url).path:return None
 price=one(o,'price');currency=one(o,'priceCurrency');availability=one(o,'availability')
 try:
  if not Decimal(price).is_finite() or Decimal(price)<0:return None
 except (InvalidOperation,TypeError):return None
 if not currency or not re.fullmatch('[A-Z]{3}',currency):return None
 return {'@type':'Product','name':titles[0],'url':url,'sku':one(p,'sku'),
         'image':one(p,'image'),'description':one(p,'description'),
         '_lotus_microdata':True,
         'offers':{'@type':'Offer','url':url,'price':price,'priceCurrency':currency,
                   'availability':availability or ''}}

def category_links(html,url):
 tree=Tree(html).root
 grids=[n for n in tree.walk() if 'productGrid' in n.attrs.get('class','').split() and not n.attrs.get('data-product-type')]
 links=[]
 for grid in grids:
  for n in grid.walk():
   u=urljoin(url,n.attrs.get('href',''))
   if n.tag=='a' and product_url(u) and u not in links:links.append(u)
 next_url=None
 for n in tree.walk():
  if n.tag=='link' and n.attrs.get('rel')=='next':
   u=urljoin(url,n.attrs.get('href',''));p=urlsplit(u);q=parse_qs(p.query)
   if host(u) and p.scheme=='https' and p.path==urlsplit(url).path and set(q)=={'page'} and q['page'][0].isdigit() and 1<int(q['page'][0])<=20:next_url=u
 return links,next_url

async def discover(adapter,session):
 state=_STATE.setdefault(adapter.domain,{'index':0,'pages':{},'last':{}})
 path=CATEGORIES[state['index']%len(CATEGORIES)]
 url=state['pages'].get(path,'https://www.plazajapan.com'+path)
 body=await adapter._get(session,url)
 state['index']+=1
 if not body:return []
 links,nxt=category_links(body,url)
 if not links:return []
 # Work through a page's products before advancing its pagination.
 last=state['last'].get(url)
 start=(links.index(last)+1) if last in links else 0
 if start>=len(links):start=0
 selected=links[start:start+min(adapter.max_product_pages,12)]
 if start+len(selected)>=len(links):
  state['last'].pop(url,None)
  state['pages'][path]=nxt or 'https://www.plazajapan.com'+path
 else:state['last'][url]=selected[-1]
 adapter.diagnostics['product_urls_discovered']=len(links)
 print(f'PLAZA CATEGORY COVERAGE | ProductsSelected={len(selected)} | Category={path} | Page={parse_qs(urlsplit(url).query).get("page",["1"])[0]} | Scope=PARTIAL | Version=ASIA1')
 return selected
