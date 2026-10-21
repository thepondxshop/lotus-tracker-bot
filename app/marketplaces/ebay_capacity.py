"""Bounded settings and reviewed-target search pages; no eligibility changes."""
import os
from collections import OrderedDict

def integer(env,key,default,minimum,maximum):
    try:return max(minimum,min(maximum,int(env.get(key,str(default)))))
    except (ValueError,TypeError):return default

def settings(env=None):
    env=os.environ if env is None else env
    return dict(details=integer(env,'LOTUS_EBAY_DETAILS_PER_CYCLE',3,1,10),
                interval=integer(env,'LOTUS_EBAY_CYCLE_SECONDS',135,60,600),
                pages=integer(env,'LOTUS_EBAY_TARGET_PAGES',5,1,10))

class SearchPages:
    def __init__(self,pages=5):self.pages=pages;self.cursors=OrderedDict()
    def offset(self,key):
        head,deep=self.cursors.get(key,(True,1))
        return 0 if head or self.pages<=1 else deep*100
    def advance(self,key,result_count):
        head,deep=self.cursors.get(key,(True,1))
        if result_count<100 or self.pages<=1:self.cursors[key]=(True,1)
        elif head:self.cursors[key]=(False,deep)
        else:self.cursors[key]=(True,1 if deep+1>=self.pages else deep+1)
        self.cursors.move_to_end(key)
        while len(self.cursors)>1000:self.cursors.popitem(last=False)
