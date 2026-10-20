"""Aggregate shadow evidence only; no listing IDs, titles or seller records."""
SCHEMA = '''CREATE TABLE IF NOT EXISTS lotus_ebay_shadow (
 fingerprint text NOT NULL, target_id text NOT NULL, auction boolean NOT NULL,
 checked integer NOT NULL DEFAULT 0, eligible integer NOT NULL DEFAULT 0,
 last_eligible_at timestamptz, last_checked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(fingerprint,target_id,auction))'''
async def ensure(store):
    await store.pool.execute(SCHEMA)
    await store.pool.execute("""CREATE TABLE IF NOT EXISTS lotus_ebay_cycle_status (
      fingerprint text NOT NULL,target_id text NOT NULL,auction boolean NOT NULL,
      checked_at timestamptz NOT NULL DEFAULT now(),payload text NOT NULL,
      PRIMARY KEY(fingerprint,target_id,auction))""")
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


async def record_cycle(store, fingerprint, target_id, auction, mode, search_results, details_checked, counts):
    """Persist bounded aggregate diagnostics, never listing/seller content."""
    import json
    payload=json.dumps(dict(mode=mode,search_results=search_results,
        details_checked=details_checked,counts=dict(counts)))
    await store.pool.execute("""INSERT INTO lotus_ebay_cycle_status(fingerprint,target_id,auction,payload)
      VALUES($1,$2,$3,$4) ON CONFLICT(fingerprint,target_id,auction)
      DO UPDATE SET checked_at=now(),payload=EXCLUDED.payload""",fingerprint,target_id,auction,payload)
    await store.pool.execute("DELETE FROM lotus_ebay_cycle_status WHERE checked_at < now()-interval '14 days'")
