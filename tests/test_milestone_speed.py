import importlib.util
from pathlib import Path
import unittest
import ast
import asyncio
from collections import Counter
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from urllib.parse import quote
import os
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

plan=load('page_plan','app/marketplaces/ebay_search_plan.py')
reports=load('monitor_report','lotus_monitor_report.py')

class CoverageTests(unittest.TestCase):
    def test_page_cursor_isolation_and_resume(self):
        r=plan.DetailRotation()
        head=[{'itemId':str(i)} for i in range(10)]
        deep=[{'itemId':'deep'+str(i)} for i in range(10)]
        r.put('target',head,now=0,offset=0)
        self.assertEqual(r.take('target',3),head[:3])
        r.put('target',deep,now=1,offset=100)
        self.assertEqual(r.take('target',3),deep[:3])
        r.put('target',head,now=2,offset=0)
        self.assertEqual(r.take('target',3),head[3:6])
    def test_expiry_and_other_targets(self):
        r=plan.DetailRotation(ttl=2)
        rows=[{'itemId':str(i)} for i in range(5)]
        r.put('a',rows,now=0);r.take('a',2)
        self.assertIsNone(r.get('a',now=3))
        r.put('a',rows,now=3)
        self.assertEqual(r.take('a',1),rows[2:3])
        r.put('b',rows,now=3)
        self.assertEqual(r.take('b',1),rows[:1])
    def test_bounds_and_no_seller_retention(self):
        r=plan.DetailRotation(maximum=2)
        for i in range(5):
            r.put('a',[{'itemId':str(i),'seller':'SECRET'}],now=i,offset=100*i);r.take('a')
        self.assertLessEqual(len(r.cursors),2)
        self.assertNotIn('SECRET',repr(r.cache))
    def test_log_metrics_and_malformed_input(self):
        result=reports.report([
            'LOTUS DELIVERY TIMING | QueueAgeSeconds=2 | DiscordSendSeconds=nan',
            'LOTUS DELIVERY TIMING | QueueAgeSeconds=4',
            'SHOPIFY REQUEST EVIDENCE | {"store":"example.com","http_status":429}',
            'SHOPIFY REQUEST EVIDENCE | {"store":"https://secret@host/","http_status":403}',
            'LOTUS EBAY MONITOR | {"state":"CYCLE_COMPLETE","search_results":100,"details_checked":3}',
            'LOTUS EBAY MONITOR | invalid'])
        self.assertEqual(result['delivery_seconds']['QueueAgeSeconds']['p95'],4)
        self.assertNotIn('DiscordSendSeconds',result['delivery_seconds'])
        self.assertEqual(result['ebay']['details_checked'],3)
        self.assertEqual(result['malformed_records'],1)
        self.assertNotIn('secret',str(result))
    def test_empty_logs_do_not_claim_health(self):
        result=reports.report([])
        self.assertEqual(result['delivery_seconds'],{})
        self.assertEqual(result['ebay']['cycles'],0)

class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_loop_records_page_and_details(self):
        path=ROOT/'app/marketplaces/ebay_live.py'
        fn=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='loop')
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        class Pages:
            def __init__(self,*args):pass
            def offset(self,key):return 100
            def advance(self,*args):pass
        api=NS(get=AsyncMock(side_effect=[{'itemSummaries':[{'itemId':str(i)} for i in range(3)]}]+[{'itemId':str(i)} for i in range(3)]))
        record=AsyncMock(); logs=[]
        target=dict(id='test',gtin='123',required_terms=['test'])
        ns=dict(asyncio=asyncio,os=os,random=random,Counter=Counter,quote=quote,
                DetailRotation=plan.DetailRotation,log=lambda state,**kw:logs.append((state,kw)),
                aiohttp=NS(ClientSession=lambda **kw:Session(),ClientTimeout=lambda **kw:None,DummyCookieJar=lambda:None),
                Browse=lambda *args:api,cleanup=AsyncMock(),load_targets=lambda p:[target],
                config_hash=lambda t:'hash',assess=lambda *a:dict(eligible=False,reason='NOT_A_DEAL'),
                gtin_status=lambda *a:dict(reason='GTIN_MISSING'),
                ebay_shadow=NS(record=AsyncMock(),record_cycle=record),AccessFailure=type('AccessFailure',(Exception,),{}))
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),ns)
        closed=iter([False,True])
        store=NS(pool=NS(fetchval=AsyncMock(return_value=False)),epoch=AsyncMock(return_value=0))
        modules={'app.marketplaces.ebay_capacity':NS(settings=lambda:dict(details=3,pages=5,interval=135),SearchPages=Pages),
                 'app.marketplaces.ebay_live_policy':NS(review_diagnostics=lambda *a:dict(benchmark_ready=True,item_price_threshold='1',price_only_meets_threshold=False))}
        with patch.dict(sys.modules,modules),patch.object(asyncio,'sleep',AsyncMock()):
            await ns['loop'](NS(is_closed=lambda:next(closed)),store,NS(fetchval=AsyncMock(return_value=1)),'SHADOW')
        self.assertEqual(api.get.await_count,4)
        self.assertEqual(record.call_args.args[6],3)
        cycle=next(row for state,row in logs if state=='CYCLE_COMPLETE')
        self.assertEqual(cycle['search_offset'],100)
        self.assertEqual(cycle['details_checked'],3)
