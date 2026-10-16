"""Aggregate shadow evidence only; no listing IDs, titles or seller records."""
SCHEMA = '''CREATE TABLE IF NOT EXISTS lotus_ebay_shadow (
 fingerprint text NOT NULL, target_id text NOT NULL, auction boolean NOT NULL,
 checked integer NOT NULL DEFAULT 0, eligible integer NOT NULL DEFAULT 0,
 last_eligible_at timestamptz, last_checked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(fingerprint,target_id,auction))'''
async def ensure(store):
    await store.pool.execute(SCHEMA)
async def record(store, fingerprint, target_id, auction, eligible):
    await store.pool.execute('''INSERT INTO lotus_ebay_shadow(fingerprint,target_id,auction,checked,eligible,last_eligible_at)
      VALUES($1,$2,$3,1,$4,CASE WHEN $4>0 THEN now() ELSE NULL END)
      ON CONFLICT(fingerprint,target_id,auction) DO UPDATE SET
      checked=lotus_ebay_shadow.checked+1,eligible=lotus_ebay_shadow.eligible+EXCLUDED.eligible,
      last_checked_at=now(),last_eligible_at=COALESCE(EXCLUDED.last_eligible_at,lotus_ebay_shadow.last_eligible_at)''',
      fingerprint,target_id,auction,int(eligible))
async def ready(store, fingerprint, target_id, auction):
    return bool(await store.pool.fetchval('''SELECT eligible>0 AND last_eligible_at IS NOT NULL
      FROM lotus_ebay_shadow WHERE fingerprint=$1 AND target_id=$2 AND auction=$3''',fingerprint,target_id,auction))
