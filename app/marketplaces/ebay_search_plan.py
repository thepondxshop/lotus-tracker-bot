"""Bounded, fair search/detail scheduling. No publication policy changes."""
from collections import OrderedDict
import time

GAME_QUERIES = (
    ('Pokemon','Pokemon TCG'), ('One Piece','One Piece card game'),
    ('MTG','Magic the Gathering'), ('Dragon Ball Fusion World','Dragon Ball Fusion World'),
    ('Riftbound','Riftbound TCG'), ('Gundam','Gundam card game'),
    ('Final Fantasy TCG','Final Fantasy TCG'), ('CookieRun: Braverse','CookieRun Braverse'),
    ('Union Arena','Union Arena'), ('Cyberpunk TCG','Cyberpunk TCG'),
    ('Azuki TCG','Azuki TCG'), ('Naruto','Naruto TCG'),
    ('Palworld','Palworld card game'), ('Hellbreak TCG','Hellbreak TCG'),
    ('Jurassic Park TCG','Jurassic Park TCG'), ('Godzilla TCG','Godzilla TCG'),
    ('Horo Beat','Horo Beat'), ('Wuthering Waves','Wuthering Waves TCG'),
    ('Harry Potter TCG — Kakawow','Harry Potter Kakawow'), ('Cataclysm Arcade','Cataclysm Arcade TCG'),
)

def discovery_plan(index):
    game,query=GAME_QUERIES[index % len(GAME_QUERIES)]
    # Both new listings and price-ordered results, across five pages, without
    # claiming exhaustive marketplace coverage.
    turn=index//len(GAME_QUERIES)
    return game, {'q':query, 'limit':'100', 'offset':str((turn//2 % 5)*100),
        'sort':'newlyListed' if turn%2==0 else 'price',
        'filter':'buyingOptions:{FIXED_PRICE|AUCTION},itemLocationCountry:US'}

class DetailRotation:
    def __init__(self, ttl=300, maximum=100):
        self.ttl,self.maximum=ttl,maximum
        self.cache=OrderedDict()
        self.cursors=OrderedDict()
    def get(self,key,now=None):
        now=time.monotonic() if now is None else now
        self.expire(now)
        value=self.cache.get(key)
        return None if value is None else value['rows']
    def expire(self,now):
        for key in list(self.cache):
            if now-self.cache[key]['at']>=self.ttl: del self.cache[key]
    def put(self,key,rows,now=None):
        now=time.monotonic() if now is None else now
        if not isinstance(rows,list): raise ValueError('Invalid search response')
        # Retain only item IDs, never seller/profile fields from summaries.
        ids=list(dict.fromkeys(r['itemId'] for r in rows if isinstance(r,dict)
            and isinstance(r.get('itemId'),str) and len(r['itemId'])<=200))[:100]
        previous=self.cursors.get(key,0)
        self.cache[key]={'at':now,'rows':[{'itemId':i} for i in ids], 'cursor':previous}
        self.cache.move_to_end(key);self.expire(now)
        while len(self.cache)>self.maximum:self.cache.popitem(last=False)
    def take(self,key,count=3):
        v=self.cache[key];rows=v['rows']
        if not rows:return []
        count=min(count,len(rows));start=v['cursor']%len(rows)
        result=[rows[(start+i)%len(rows)] for i in range(count)]
        v['cursor']=(start+count)%len(rows)
        self.cursors[key]=v['cursor'];self.cursors.move_to_end(key)
        while len(self.cursors)>self.maximum:self.cursors.popitem(last=False)
        return result
