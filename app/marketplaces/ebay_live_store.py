"""Shared eBay outbox/deletion inbox. No raw seller IDs or listing content stored.
Database backups require a separate retention policy; this cannot erase backups.
"""
import hashlib
import hmac
import os
from contextlib import asynccontextmanager
LOCK = 71042603
WORKER_LOCK = 71042604
SCHEMA = '''
CREATE TABLE IF NOT EXISTS lotus_ebay_control (
 id integer PRIMARY KEY CHECK(id=1), key_check text NOT NULL,
 tested boolean NOT NULL DEFAULT false, unresolved boolean NOT NULL DEFAULT false, epoch bigint NOT NULL DEFAULT 0, identity_at timestamptz, mode text,
 requests_at timestamptz NOT NULL DEFAULT now(), requests integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lotus_ebay_suppressed (digest text PRIMARY KEY);
CREATE TABLE IF NOT EXISTS lotus_ebay_outbox (
 id uuid PRIMARY KEY, listing_key text UNIQUE NOT NULL, owners text[] NOT NULL,
 channel_id bigint NOT NULL, message_id bigint, state text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), delete_requested boolean NOT NULL DEFAULT false
);
'''
def identifiers(data):
    values = []
    for key in ('username', 'userId', 'eiasToken'):
        v = data.get(key)
        if isinstance(v, str) and v:
            values.extend((v, v.casefold()))
    return set(values)

class Store:
    def __init__(self):
        self.pool = None
        self.secret = os.getenv('EBAY_RETENTION_HMAC_KEY', '').encode()
        if len(self.secret) < 32:
            raise ValueError('EBAY_RETENTION_HMAC_KEY must contain at least 32 characters')
    def digest(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()
    def owners(self, data):
        return sorted(self.digest(v) for v in identifiers(data))
    async def start(self):
        import asyncpg
        url = os.getenv('EBAY_DATABASE_URL', '')
        if not url:
            raise ValueError('EBAY_DATABASE_URL missing')
        self.pool = await asyncpg.create_pool(url.replace('postgresql+asyncpg://','postgresql://'), min_size=1, max_size=3, command_timeout=20)
        try:
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await c.execute('SELECT pg_advisory_xact_lock($1)', LOCK)
                    await c.execute(SCHEMA)
                    check = self.digest('LOTUS_EBAY_RETENTION_KEY_V1')
                    await c.execute('INSERT INTO lotus_ebay_control(id,key_check) VALUES(1,$1) ON CONFLICT DO NOTHING', check)
                    if await c.fetchval('SELECT key_check FROM lotus_ebay_control WHERE id=1') != check:
                        raise ValueError('Retention key differs from existing database')
        except BaseException:
            await self.pool.close()
            self.pool = None
            raise
    async def close(self):
        if self.pool:
            await self.pool.close()
    @asynccontextmanager
    async def locked(self):
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock($1)', LOCK)
                yield c
    async def heartbeat(self, mode):
        await self.pool.execute('UPDATE lotus_ebay_control SET identity_at=now(), mode=$1 WHERE id=1', mode)
    async def ready(self):
        return bool(await self.pool.fetchval("SELECT tested AND NOT unresolved AND mode='LIVE_REVIEWED' AND identity_at > now()-interval '90 seconds' FROM lotus_ebay_control WHERE id=1"))
    async def epoch(self):
        return await self.pool.fetchval('SELECT epoch FROM lotus_ebay_control WHERE id=1')
    async def budget(self):
        async with self.locked() as c:
            await c.execute("UPDATE lotus_ebay_control SET requests_at=now(),requests=0 WHERE id=1 AND requests_at < now()-interval '1 hour'")
            return bool(await c.fetchval('UPDATE lotus_ebay_control SET requests=requests+1 WHERE id=1 AND requests<120 RETURNING true'))
    async def receive_deletion(self, data):
        owners = self.owners(data)
        async with self.locked() as c:
            await c.executemany('INSERT INTO lotus_ebay_suppressed(digest) VALUES($1) ON CONFLICT DO NOTHING', [(x,) for x in owners])
            await c.execute('UPDATE lotus_ebay_control SET epoch=epoch+1 WHERE id=1')
            if not (data.get('username') or data.get('userId')):
                await c.execute('UPDATE lotus_ebay_outbox SET delete_requested=true')
                await c.execute('UPDATE lotus_ebay_control SET unresolved=true WHERE id=1')
            else:
                await c.execute('UPDATE lotus_ebay_outbox SET delete_requested=true WHERE owners && $1::text[]', owners)
    async def prepare(self, listing_id, owner, channel_id, epoch, token):
        owners = self.owners(owner)
        if not owners:
            return False
        async with self.locked() as c:
            if epoch != await c.fetchval('SELECT epoch FROM lotus_ebay_control WHERE id=1'):
                return False
            if await c.fetchval('SELECT EXISTS(SELECT 1 FROM lotus_ebay_suppressed WHERE digest=ANY($1::text[]))', owners):
                return False
            return bool(await c.fetchval("INSERT INTO lotus_ebay_outbox(id,listing_key,owners,channel_id,state) VALUES($1,$2,$3,$4,'PREPARED') ON CONFLICT(listing_key) DO NOTHING RETURNING true", token, self.digest(listing_id), owners, channel_id))
    async def stats(self):
        rows = await self.pool.fetch('SELECT state,delete_requested,count(*) AS count FROM lotus_ebay_outbox GROUP BY state,delete_requested')
        return [dict(r) for r in rows]
