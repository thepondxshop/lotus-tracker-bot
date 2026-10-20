"""One public Algolia discovery request. Never asserts availability or changes Lotus."""
import asyncio
import json
import os
import re
from urllib.parse import urlencode,urlsplit
import aiohttp

def parse(data):
    results=data.get('results')
    if not isinstance(results,list) or len(results)!=1:raise ValueError('SCHEMA_INVALID')
    hits=results[0].get('hits')
    if not isinstance(hits,list) or len(hits)>20:raise ValueError('SCHEMA_INVALID')
    out=[];seen=set()
    for h in hits:
        key=h.get('objectID');name=h.get('name');url=h.get('url')
        if not isinstance(key,str) or not key or key in seen:raise ValueError('IDENTITY_INVALID')
        seen.add(key)
        if not isinstance(name,str) or not name or not isinstance(url,str):continue
        if url.startswith('/product/'):url='https://www.pokemoncenter.com'+url
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname!='www.pokemoncenter.com' or not parsed.path.startswith('/product/') or parsed.username or parsed.password:continue
        out.append({'id':key,'title':name,'url':url,'stock_verified':False})
    return {'state':'DISCOVERY_SCHEMA_PARSED','candidates':out,'returned_hits':len(hits),'coverage':'FIRST_20_SEARCH_HITS_ONLY','stock_verified':False,'alerts_sent':0,'database_modified':False}

async def run():
    app=os.getenv('LOTUS_PC_SEARCH_APP_ID','');key=os.getenv('LOTUS_PC_SEARCH_KEY','');index=os.getenv('LOTUS_PC_SEARCH_INDEX','')
    if not re.fullmatch('[A-Z0-9]{10}',app) or not key or not re.fullmatch('[A-Za-z0-9_-]{1,100}',index):
        return {'state':'PUBLIC_SEARCH_CONFIGURATION_REQUIRED','required':['LOTUS_PC_SEARCH_APP_ID','LOTUS_PC_SEARCH_KEY','LOTUS_PC_SEARCH_INDEX'],'stock_verified':False,'alerts_sent':0}
    url='https://'+app.lower()+'-dsn.algolia.net/1/indexes/*/queries'
    payload={'requests':[{'indexName':index,'params':urlencode({'query':'pokemon trading card','hitsPerPage':20,'page':0})}]}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),trust_env=False,cookie_jar=aiohttp.DummyCookieJar()) as client:
        async with client.post(url,json=payload,headers={'x-algolia-application-id':app,'x-algolia-api-key':key},allow_redirects=False) as r:
            if r.status!=200:return {'state':'PUBLIC_SEARCH_UNAVAILABLE','http_status':r.status,'stock_verified':False,'alerts_sent':0}
            body=bytearray()
            async for part in r.content.iter_chunked(65536):
                body.extend(part)
                if len(body)>2000000:raise ValueError('RESPONSE_TOO_LARGE')
            return parse(json.loads(body))
if __name__=='__main__':
    try:print(json.dumps(asyncio.run(run()),indent=2))
    except Exception as e:print(json.dumps({'state':'PROBE_FAILED','error':type(e).__name__,'stock_verified':False,'alerts_sent':0}));raise SystemExit(1)
