"""One read-only launch report. Configuration presence never implies delivery readiness."""
from datetime import datetime, timezone
from pathlib import Path
import json, os
from app.marketplaces.foundation import MINIMUM_TIERS
from app.marketplaces.ebay_live_policy import load_targets
from app.marketplaces.ebay_evidence import comparison, config_hash

CHANNELS={'ebay':'CHANNEL_EBAY_INTELLIGENCE','mercari_us':'CHANNEL_MERCARI_INTELLIGENCE',
          'buyee_jp':'CHANNEL_BUYEE_INTELLIGENCE','cardmarket':'CHANNEL_CARDMARKET_INTELLIGENCE',
          'tcgplayer':'CHANNEL_TCGPLAYER_INTELLIGENCE'}

def local_status(environ=None):
    env=os.environ if environ is None else environ
    capabilities={
      'ebay':('BROWSE_WORKER_IMPLEMENTED','REVIEWED_BENCHMARK_AND_LIVE_GATES'),
      'mercari_us':('MANUAL_LISTING_REVIEW_ONLY','LISTING_SOURCE_NOT_CONNECTED'),
      'buyee_jp':('MANUAL_LISTING_REVIEW_ONLY','LISTING_SOURCE_NOT_CONNECTED'),
      'tcgplayer':('TCGDEX_POKEMON_REFERENCE_WORKER','EXACT_REVIEWED_MAPPING_AND_FRESH_PRICE_REQUIRED'),
      'cardmarket':('POKEMON_GUIDE_REFERENCE_WORKER','EXACT_REVIEWED_MAPPING_AND_FRESH_PRICE_REQUIRED')}
    markets={k:{'minimum_tier':MINIMUM_TIERS[k],'implementation':v[0],'remaining':v[1],
        'channel_variable':CHANNELS[k],'channel_configured':str(env.get(CHANNELS[k],'')).isdigit() and int(env[CHANNELS[k]])>0,
        'live_delivery_verified':False} for k,v in capabilities.items()}
    markets['tcgplayer']['credentials_present']=bool(env.get('TCGPLAYER_ACCESS_TOKEN') or
        (env.get('TCGPLAYER_CLIENT_ID') and env.get('TCGPLAYER_CLIENT_SECRET')))
    markets['tcgplayer']['tcgdex_requires_tcgplayer_credentials']=False
    for name in ('tcgplayer','cardmarket'):
        markets[name]['listing_feed_connected']=False
        markets[name]['reference_scope']='POKEMON_ONLY; retailer deals after exact mapping'
    ebay={'mode':env.get('EBAY_MONITOR_MODE','OFF').upper(),'database_checked':False,
          'database_configured':bool(env.get('EBAY_DATABASE_URL')),
          'retention_key_configured':len(env.get('EBAY_RETENTION_HMAC_KEY',''))>=32,
          'automatic_sold_feed':False,'targets':[],
          'discovery_scope':'ROTATING_TRACKED_GAME_SEARCHES',
          'discovery_is_deal_delivery':False,'maximum_reviewed_targets':250}
    ebay['channels']={label:str(env.get(key,'')).isdigit() and int(env[key])>0 for label,key in
        (('fixed','CHANNEL_EBAY_INTELLIGENCE'),('auction','CHANNEL_EBAY_AUCTIONS'))}
    path=Path(env.get('EBAY_TARGETS_FILE','ebay-targets.json'))
    ebay['target_path']=str(path.resolve())
    try:
        targets=load_targets(path);fingerprint=config_hash(targets)
        ebay['config_hash']=fingerprint
        ebay['approved_config_matches']=bool(targets) and env.get('EBAY_APPROVED_TARGETS_SHA256')==fingerprint
        ebay['targets']=[{'target':t['id'],'comparison':comparison(t),
            'fixed_shadow_ready':None,'auction_shadow_ready':None} for t in targets]
    except (OSError,ValueError,TypeError,KeyError) as e:ebay['targets_error']=type(e).__name__
    from app.marketplaces.ebay_capacity import settings
    ebay['capacity']=settings(env)
    ebay['search_coverage']='PARTIAL_HEAD_AND_ROTATING_DEEP_PAGES'
    return {'markets':markets,'ebay':ebay,'alerts_sent':0,'settings_changed':False,
        'community_xp':{'enabled_configured':env.get('LOTUS_XP_ENABLED','false').lower()=='true',
                        'message_content_configured':env.get('LOTUS_XP_MESSAGE_CONTENT','false').lower()=='true',
                        'runtime_verified':False,'check':'/xpstatus'},
        'pending_other_monitors':['Pokemon Center: live stock access not verified',
        'Riot/Riftbound: run lotus_riot_probe.py and lotus_riot_status.py --database; merch is page/price-only, official news is opt-in',
        'Premium Bandai: page/price adapter installed; current production state must be checked with lotus_readiness_check.py --database; stock unverified',
        'Major retailers: check lotus_readiness_check.py --database'],
        'note':'Price previews are not listing feeds or alert integrations. No cross-currency or regional averages are combined.'}


async def database_status(report):
    import asyncpg
    raw=os.getenv('EBAY_DATABASE_URL','').replace('postgresql+asyncpg://','postgresql://',1)
    if not raw:return report
    con=None;ebay=report['ebay']
    try:
        con=await asyncpg.connect(raw,timeout=10,command_timeout=10)
        async with con.transaction(readonly=True):
            if not await con.fetchval("SELECT to_regclass('lotus_ebay_control')"):
                ebay['database_state']='SCHEMA_NOT_CREATED';return report
            control=await con.fetchrow("SELECT tested,unresolved,mode,identity_at, tested AND NOT unresolved AND mode='LIVE_REVIEWED' AND identity_at>now()-interval '90 seconds' AS ready FROM lotus_ebay_control WHERE id=1")
            ebay['identity_retention_ready']=bool(control and control['ready'])
            ebay['database_checked']=True
            fp=ebay.get('config_hash')
            shadow=await con.fetchval("SELECT to_regclass('lotus_ebay_shadow')")
            cycles=await con.fetchval("SELECT to_regclass('lotus_ebay_cycle_status')")
            for t in ebay['targets']:
                for auction,label in ((False,'fixed'),(True,'auction')):
                    if shadow:
                        t[label+'_shadow_ready']=bool(await con.fetchval('SELECT eligible>0 AND last_eligible_at IS NOT NULL FROM lotus_ebay_shadow WHERE fingerprint=$1 AND target_id=$2 AND auction=$3',fp,t['target'],auction))
                    if cycles:
                        cycle=await con.fetchrow('SELECT checked_at,payload FROM lotus_ebay_cycle_status WHERE fingerprint=$1 AND target_id=$2 AND auction=$3',fp,t['target'],auction)
                        if cycle:t[label+'_last_cycle']={'checked_at':cycle['checked_at'].isoformat(),**json.loads(cycle['payload'])}
                    blockers=[]
                    if not ebay['channels'][label]:blockers.append('CHANNEL_NOT_CONFIGURED')
                    if not t['comparison']['ready']:blockers.append(t['comparison']['reason'])
                    if not t.get(label+'_shadow_ready'):blockers.append('ELIGIBLE_SHADOW_OBSERVATION_REQUIRED')
                    if not ebay['identity_retention_ready']:blockers.append('IDENTITY_RETENTION_NOT_READY')
                    if not ebay.get('approved_config_matches'):blockers.append('APPROVED_CONFIG_HASH_REQUIRED')
                    if ebay['mode']!='LIVE':blockers.append('MODE_'+ebay['mode'])
                    t[label+'_launch_blockers']=blockers
    except Exception as e:
        ebay['database_state']='CHECK_FAILED';ebay['database_error_type']=type(e).__name__
    finally:
        if con:await con.close()
    return report
