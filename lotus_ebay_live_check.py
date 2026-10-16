"""EBAY-LIVE2 configuration and isolated PostgreSQL self-test. No Discord sends."""
import argparse
import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from app.marketplaces.ebay_live_policy import load_targets
from app.marketplaces.ebay_live_store import Store, SCHEMA
from app.marketplaces.ebay_evidence import comparison, config_hash
from app.marketplaces import ebay_shadow

async def database_test(store):
    # Every assertion uses a new isolated schema and a rolled-back transaction.
    async with store.pool.acquire() as c:
        tx = c.transaction()
        await tx.start()
        try:
            schema = 'lotus_ebay_test_'+uuid.uuid4().hex
            await c.execute('CREATE SCHEMA '+schema)
            await c.execute('SET LOCAL search_path TO '+schema)
            await c.execute(SCHEMA)
            await c.execute("INSERT INTO lotus_ebay_control(id,key_check,mode,identity_at) VALUES(1,'test','LIVE_REVIEWED',now())")
            class ConnectionPool:
                @asynccontextmanager
                async def acquire(self): yield c
                def __getattr__(self, name): return getattr(c, name)
            test = Store()
            test.pool = ConnectionPool()
            owner = {'username':'synthetic-test-seller'}
            first = uuid.uuid4()
            assert await test.prepare('test-listing',owner,123,0,first)
            assert not await test.prepare('test-listing',owner,123,0,uuid.uuid4())
            await test.receive_deletion(owner)
            assert await c.fetchval('SELECT delete_requested FROM lotus_ebay_outbox WHERE id=$1',first)
            assert not await test.prepare('different-listing',owner,123,1,uuid.uuid4())
            assert not await test.prepare('stale-result',{'username':'other'},123,0,uuid.uuid4())
            await test.receive_deletion(owner) # idempotent tombstones
            assert await c.fetchval('SELECT count(*) FROM lotus_ebay_suppressed') == len(test.owners(owner))
            await test.receive_deletion({'eiasToken':'unmatchable-synthetic'})
            assert await c.fetchval('SELECT unresolved FROM lotus_ebay_control WHERE id=1')
            assert not await test.ready()
            await ebay_shadow.ensure(test)
            assert not await ebay_shadow.ready(test,'test-config','test-target',False)
            await ebay_shadow.record(test,'test-config','test-target',False,False)
            assert not await ebay_shadow.ready(test,'test-config','test-target',False)
            await ebay_shadow.record(test,'test-config','test-target',False,True)
            assert await ebay_shadow.ready(test,'test-config','test-target',False)
            assert not await ebay_shadow.ready(test,'changed-config','test-target',False)
            assert not await ebay_shadow.ready(test,'test-config','test-target',True)
            for _ in range(120): assert await test.budget()
            assert not await test.budget()
        finally:
            await tx.rollback()
    # Successful transaction tests unlock the DB gate, not the monitor mode.
    await store.pool.execute('UPDATE lotus_ebay_control SET tested=true WHERE id=1')
    return 'DATABASE_SELF_TEST_PASSED'

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-self-test',action='store_true')
    args = parser.parse_args()
    result = {'version':'EBAY-LIVE2','mode':os.getenv('EBAY_MONITOR_MODE','OFF'),
              'alerts_sent':0, 'sold_source_integrated':False,
              'database_configured':bool(os.getenv('EBAY_DATABASE_URL')),
              'retention_key_configured':len(os.getenv('EBAY_RETENTION_HMAC_KEY',''))>=32,
              'channels':{k:bool(os.getenv(k)) for k in ('CHANNEL_EBAY_INTELLIGENCE','CHANNEL_EBAY_AUCTIONS')}}
    path = Path(os.getenv('EBAY_TARGETS_FILE','ebay-targets.json'))
    try:
        targets = load_targets(path)
        result['reviewed_targets'] = len(targets)
        result['comparison_status'] = [{'target':t['id'], **comparison(t)} for t in targets]
        result['approved_config_matches'] = bool(targets) and os.getenv('EBAY_APPROVED_TARGETS_SHA256','') == config_hash(targets)
    except Exception as error:
        result.update(reviewed_targets=0, targets_error=type(error).__name__)
    if args.database_self_test:
        store = None
        try:
            store = Store()
            await store.start()
            result['database_test'] = await database_test(store)
            result['identity_retention_ready'] = await store.ready()
            result['outbox'] = await store.stats()
        except Exception as error:
            result.update(database_test='FAILED',error_type=type(error).__name__)
        finally:
            if store: await store.close()
    print('LOTUS EBAY LIVE CHECK | '+json.dumps(result),flush=True)
    if result.get('database_test') == 'FAILED': return 1
    return 0

if __name__=='__main__': raise SystemExit(asyncio.run(main()))
