"""Opt-in fixed-price listing delivery through the existing durable outbox."""
import hashlib
import os
import json
import traceback
from pathlib import Path
from app.marketplaces.ebay_evidence import config_hash
from app.marketplaces.ebay_live_policy import assess
from app.marketplaces import ebay_shadow


def fingerprint(targets):
    # Separate evidence from deals, and invalidate approval when destination changes.
    return hashlib.sha256(('LISTINGS1:'+config_hash(targets)+':'+os.getenv('CHANNEL_EBAY_MARKETPLACE','0')).encode()).hexdigest()


async def _handle(bot, store, item, targets, target, epoch, worker_mode, channel_check, publish):
    mode = os.getenv('EBAY_LISTING_MODE','OFF').upper()
    if mode == 'OFF' or worker_mode == 'OFF':
        return 'OFF'
    if mode not in {'SHADOW','LIVE'}:
        return 'INVALID_LISTING_MODE'
    result = assess(item, target, listing_only=True)
    key = fingerprint(targets)
    if not result['eligible']:
        if mode == 'SHADOW':
            await ebay_shadow.record(store,key,target['id'],False,False)
        return result['reason']
    if not await store.ready():
        return 'IDENTITY_RETENTION_NOT_READY'
    channel = os.getenv('CHANNEL_EBAY_MARKETPLACE','0')
    if not channel.isdigit() or int(channel)<=0:
        return 'LISTING_CHANNEL_REQUIRED'
    await channel_check(bot,int(channel))
    if mode == 'SHADOW':
        await ebay_shadow.record(store,key,target['id'],False,True)
        return 'LISTING_SHADOW_ELIGIBLE'
    if os.getenv('EBAY_LISTING_APPROVED_SHA256','') != key:
        return 'LISTING_APPROVAL_REQUIRED'
    if not await ebay_shadow.ready(store,key,target['id'],False):
        return 'LISTING_SHADOW_REQUIRED'
    return await publish(bot,store,item,result,epoch)


def failure_location(error):
    # Never include exception messages, source lines, locals or API payloads.
    return {'error_type':type(error).__name__, 'frames':[
        {'file':Path(frame.filename).name,'function':frame.name,'line':frame.lineno}
        for frame in traceback.extract_tb(error.__traceback__)[-8:]]}


async def handle(*args, **kwargs):
    try:
        return await _handle(*args, **kwargs)
    except Exception as error:
        print('LOTUS EBAY LISTING FAILURE | '+json.dumps(failure_location(error)),flush=True)
        raise
