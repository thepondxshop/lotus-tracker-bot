"""EBAY-LIVE2: bounded reviewed-target pilot, integrated into the existing bot.
Default OFF. SHADOW performs searches without publishing or saving listings.
"""
import asyncio
import contextlib
import json
import os
import random
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo
import aiohttp
from app.marketplaces.ebay import EbayPreview, response_json, AccessFailure
from app.marketplaces.ebay_live_policy import load_targets, assess, gtin_status
from app.marketplaces.ebay_live_store import Store, WORKER_LOCK
from app.marketplaces.ebay_evidence import config_hash
from app.marketplaces import ebay_shadow


def log(state, **fields):
    print('LOTUS EBAY MONITOR | '+json.dumps({'version':'EBAY-LIVE2','state':state, **fields}), flush=True)


async def allowed_channel(bot, channel_id):
    """Require an actual Premium-only text channel, with no general-role access."""
    import discord
    from app.config import SUBSCRIPTION_ROLES
    channel = await bot.fetch_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError('Premium text channel required')
    guild = channel.guild
    roles = await guild.fetch_roles()
    allowed = {int(SUBSCRIPTION_ROLES[t]) for t in ('Premium','Premium+') if str(SUBSCRIPTION_ROLES.get(t,'')).isdigit()}
    if len(allowed) < 2 or not allowed.issubset({r.id for r in roles}):
        raise ValueError('Premium roles not configured')
    # permissions_for(Role) includes @everyone and role channel overwrites.
    for role in roles:
        if role.id not in allowed and not role.permissions.administrator and not role.is_bot_managed():
            if channel.permissions_for(role).view_channel:
                raise ValueError('Channel visible below Premium')
    if not all(channel.permissions_for(guild.get_role(r)).view_channel for r in allowed):
        raise ValueError('Premium role cannot see channel')
    for subject, overwrite in channel.overwrites.items():
        if isinstance(subject, discord.Member) and overwrite.view_channel is True and subject.id != bot.user.id and not subject.guild_permissions.administrator:
            raise ValueError('Member-specific visibility requires review')
    me = guild.me or await guild.fetch_member(bot.user.id)
    p = channel.permissions_for(me)
    if not (p.view_channel and p.send_messages and p.embed_links and p.read_message_history):
        raise ValueError('Bot needs view/send/embed/history permissions')
    return channel


async def cleanup(bot, store):
    """Reconcile uncertain sends before retrying deletion. Never resend blindly."""
    import discord
    rows = await store.pool.fetch("SELECT * FROM lotus_ebay_outbox WHERE delete_requested OR state='PREPARED' OR created_at < now()-interval '7 days' ORDER BY created_at LIMIT 25")
    for row in rows:
        channel = await bot.fetch_channel(row['channel_id'])
        ids = [row['message_id']] if row['message_id'] else []
        if row['state'] == 'PREPARED':
            if datetime.now(timezone.utc)-row['created_at'] < timedelta(minutes=2):
                continue
            # Handles a crash after Discord accepted the message but before DB save.
            marker = 'Lotus eBay '+str(row['id'])
            async for message in channel.history(after=row['created_at']-timedelta(seconds=5), limit=None, oldest_first=True):
                if message.author.id == bot.user.id and any(e.footer.text == marker for e in message.embeds):
                    ids.append(message.id)
        remove = row['delete_requested'] or row['created_at'] < datetime.now(timezone.utc)-timedelta(days=7)
        if remove:
            for mid in set(ids):
                try:
                    await channel.get_partial_message(mid).delete()
                except discord.NotFound:
                    pass
            async with store.locked() as c:
                await c.execute('DELETE FROM lotus_ebay_outbox WHERE id=$1', row['id'])
        elif row['state'] == 'PREPARED':
            async with store.locked() as c:
                # Keep dedup state even if the failed send produced no message.
                # Additional unexpected duplicate sends are removed immediately.
                for mid in ids[1:]:
                    try: await channel.get_partial_message(mid).delete()
                    except discord.NotFound: pass
                await c.execute("UPDATE lotus_ebay_outbox SET state='RESOLVED',message_id=$2 WHERE id=$1", row['id'], ids[0] if ids else None)


async def publish(bot, store, item, result, epoch):
    import discord
    from app.marketplaces.opportunity import timestamp
    cid = int(os.getenv(result['destination_variable'], '0'))
    channel = await allowed_channel(bot, cid)
    token = uuid.uuid4()
    if not await store.prepare(item['itemId'], item.get('seller', {}), cid, epoch, token):
        return 'DEDUPLICATED_OR_SUPPRESSED'
    async with store.locked() as c:
        record = await c.fetchrow('SELECT * FROM lotus_ebay_outbox WHERE id=$1', token)
        current_epoch = await c.fetchval('SELECT epoch FROM lotus_ebay_control WHERE id=1')
        now = datetime.now(timezone.utc)
        observed = timestamp(result['observed_at'])
        end = timestamp(result.get('ends_at'))
        if (not record or record['delete_requested'] or current_epoch != epoch or not await store.ready()
                or (now-observed).total_seconds()>60 or (end and end<=now)):
            if record:
                await c.execute("UPDATE lotus_ebay_outbox SET state='CANCELLED' WHERE id=$1", token)
            return 'CANCELLED_BEFORE_SEND'
        label = 'Auction ending soon' if result['auction'] else 'eBay deal'
        embed = discord.Embed(title=label+' • '+result['title'], url=result['url'], color=0x25A080, timestamp=now)
        if result.get('comparison_basis') == 'ITEM_ONLY':
            shipping = ('Not quoted — calculated at checkout' if result['shipping'] is None
                        else '$'+result['shipping']+' API quote; confirm for your destination')
            embed.description = ('**'+result['game']+'**\n'
                f"Item / next bid: **${result['price']}**\nShipping: {shipping}\n"
                f"Reviewed sold item average: **${float(result['comparison_amount']):.2f}** "
                f"({result.get('comparison_label', str(result['comparison_samples'])+' listing observations, last 14 days')})\n"
                f"**{float(result['discount_percent']):.1f}% below item-price average**\n"
                'Before shipping, tax and import charges. This is not a delivered-cost discount. '
                'Comparison prices were manually reviewed; no vault exemption assumed.')
        else:
            embed.description = ('**'+result['game']+'**\n'
                f"Item / next bid: **${result['price']}**\nShipping: ${result['shipping']}\n"
                f"Estimated total: **${result['current_total']}**\n"
                f"Reviewed sold comparison: **${result['comparison_amount']}**\n"
                f"At least 10% below the comparison at this check.\n"
                f"Cost scenario: US ZIP {result['destination_zip']}; tax {float(result['tax_rate'])*100:g}%. "
                'Your checkout total may differ. No vault exemption assumed.')
        if result['auction']:
            embed.add_field(name='Auction', value=f"Ends <t:{int(end.timestamp())}:R>\nMaximum item bid for the 10% target: **${result['maximum_item_bid']}**\nBids can change; winning is not guaranteed.", inline=False)
        embed.add_field(name='Observed • New York', value=observed.astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %Y %I:%M:%S %p %Z'), inline=False)
        embed.set_footer(text='Lotus eBay '+str(token))
        # Durable PREPARED row already committed. If send/commit is uncertain,
        # history reconciliation locates this marker instead of sending again.
        msg = await asyncio.wait_for(channel.send(
            content=f"{'⏳' if result['auction'] else '💰'} {result['title']} — ${result['price']} • eBay",
            embed=embed, allowed_mentions=discord.AllowedMentions.none()), timeout=20)
        await c.execute("UPDATE lotus_ebay_outbox SET state='SENT',message_id=$2 WHERE id=$1", token, msg.id)
    return 'DELIVERED'


class Browse:
    def __init__(self, store, session):
        self.store, self.session = store, session
        self.auth = EbayPreview('production')
    async def get(self, path, params, target):
        if not await self.store.budget():
            raise AccessFailure('LOCAL_HOURLY_REQUEST_BUDGET', 'SEARCH')
        token = await self.auth.token(self.session)
        headers={'Authorization':'Bearer '+token, 'X-EBAY-C-MARKETPLACE-ID':'EBAY_US'}
        if target.get('comparison_mode') != 'ITEM_ONLY':
            headers['X-EBAY-C-ENDUSERCTX']='contextualLocation=country%3DUS%2Czip%3D'+target['destination_zip']
        async with self.session.get('https://api.ebay.com/buy/browse/v1/'+path,
                params=params, headers=headers, allow_redirects=False) as response:
            return await response_json(response, 'BROWSE')


async def live_gate(store, fingerprint, target_id, auction):
    if os.getenv('EBAY_APPROVED_TARGETS_SHA256','') != fingerprint:
        return 'LIVE_REVIEW_HASH_REQUIRED'
    if not await ebay_shadow.ready(store,fingerprint,target_id,auction):
        return 'SHADOW_EVIDENCE_REQUIRED'
    return None


async def run(bot):
    await bot.wait_until_ready()
    if not os.getenv('EBAY_DATABASE_URL') and os.getenv('EBAY_MONITOR_MODE','OFF').upper() == 'OFF':
        log('OFF'); return
    while not bot.is_closed():
        try:
            await run_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log('WORKER_RESTART_PENDING', error_type=type(error).__name__)
        if not bot.is_closed():
            await asyncio.sleep(60)


async def run_once(bot):
    mode = os.getenv('EBAY_MONITOR_MODE','OFF').upper()
    # Cleanup continues with OFF when retention is configured.
    if mode not in {'OFF','SHADOW','LIVE'}:
        log('INVALID_MODE'); return
    if not os.getenv('EBAY_DATABASE_URL'):
        log('OFF' if mode=='OFF' else 'DATABASE_REQUIRED'); return
    store = Store()
    await store.start()
    try:
        await ebay_shadow.ensure(store)
        async with store.pool.acquire() as leader:
            if not await leader.fetchval('SELECT pg_try_advisory_lock($1)', WORKER_LOCK):
                log('OTHER_WORKER_ACTIVE'); return
            try:
                await loop(bot, store, leader, mode)
            finally:
                await leader.execute('SELECT pg_advisory_unlock($1)', WORKER_LOCK)
    finally:
        await store.close()


async def loop(bot, store, leader, mode):
    index = 0
    cooldown_until = 0.0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),trust_env=False,cookie_jar=aiohttp.DummyCookieJar()) as session:
        api = Browse(store, session)
        while not bot.is_closed():
            try:
                await leader.fetchval('SELECT 1') # Lost leader connection stops this worker.
            except Exception:
                log('LEADER_CONNECTION_LOST'); return
            try:
                # A deletion failure pauses new publication, but cleanup retries.
                await cleanup(bot, store)
                pending = await store.pool.fetchval('SELECT EXISTS(SELECT 1 FROM lotus_ebay_outbox WHERE delete_requested)')
                if pending:
                    log('DELETION_PENDING')
                elif mode == 'OFF':
                    log('OFF_CLEANUP_ACTIVE')
                elif asyncio.get_running_loop().time() < cooldown_until:
                    log('API_COOLDOWN')
                elif mode == 'LIVE' and not await store.ready():
                    log('IDENTITY_RETENTION_NOT_READY')
                else:
                    targets = load_targets(os.getenv('EBAY_TARGETS_FILE','ebay-targets.json'))
                    fingerprint = config_hash(targets)
                    if not targets:
                        log('NO_REVIEWED_TARGETS')
                    else:
                        target = targets[(index//2) % len(targets)]
                        auction = index%2 == 1
                        index += 1
                        epoch = await store.epoch()
                        data = await api.get('item_summary/search', {('gtin' if ((index-1)//(2*len(targets)))%2 == 0 else 'q'): (target['gtin'] if ((index-1)//(2*len(targets)))%2 == 0 else ' '.join(target['required_terms'])), 'limit':'20',
                            'sort':'endingSoonest' if auction else 'newlyListed',
                            'filter':'buyingOptions:{'+('AUCTION' if auction else 'FIXED_PRICE')+'},itemLocationCountry:US'}, target)
                        reasons = Counter()
                        rows = data.get('itemSummaries', [])
                        if not isinstance(rows, list) or 'errors' in data:
                            raise ValueError('Invalid search response')
                        # One detail request per cycle keeps the pilot near 120
                        # Browse calls/hour; rotate among up to twenty results, alternating GTIN and title searches.
                        candidates = rows[:20]
                        selected = [candidates[((index-1)//(4*len(targets))) % len(candidates)]] if candidates else []
                        for row in selected:
                            iid = row.get('itemId')
                            if not isinstance(iid,str) or len(iid)>200:
                                reasons['INVALID_ITEM_ID']+=1; continue
                            await asyncio.sleep(1)
                            item = await api.get('item/'+quote(iid,safe=''), {'fieldgroups': 'PRODUCT'}, target)
                            if item.get('itemId') != iid:
                                reasons['ITEM_ID_MISMATCH']+=1; continue
                            result = assess(item,target)
                            identity = gtin_status(item, target)
                            from app.marketplaces.ebay_live_policy import review_diagnostics
                            diagnostic = review_diagnostics(item, target)
                            log('PRICE_ASSESSMENT', target=target['id'], auction=auction,
                                benchmark_ready=diagnostic['benchmark_ready'],
                                item_price_threshold=diagnostic['item_price_threshold'],
                                price_only_meets_threshold=diagnostic['price_only_meets_threshold'],
                                assessment=result.get('reason','ELIGIBLE'), identity_method=result.get('identity_method'))
                            log('IDENTITY_CHECK', target=target['id'], auction=auction,
                                fieldgroups='PRODUCT', assessment_reason=result.get('reason', 'ELIGIBLE'),
                                **identity)
                            if result['eligible']:
                                if mode == 'SHADOW':
                                    await allowed_channel(bot, int(os.getenv(result['destination_variable'], '0')))
                                    state = 'SHADOW_ELIGIBLE'
                                    log('SHADOW_PRICE_CHECK', target=target['id'], auction=auction,
                                        price=result['price'], shipping=result['shipping'],
                                        comparison=result['comparison_amount'], basis=result.get('comparison_basis','LEGACY_TOTAL'),
                                        maximum_item_bid=result.get('maximum_item_bid'))
                                else:
                                    blocked = await live_gate(store,fingerprint,target['id'],auction)
                                    state = blocked or await publish(bot,store,item,result,epoch)
                                reasons[state] += 1
                            else:
                                reasons[result['reason']] += 1
                            if mode == 'SHADOW':
                                await ebay_shadow.record(store,fingerprint,target['id'],auction,result['eligible'])
                        log('CYCLE_COMPLETE', mode=mode, target=target['id'], auction=auction, search_results=len(rows), details_checked=len(selected), counts=dict(reasons))
            except AccessFailure as error:
                result = error.result
                wait = 900
                try:
                    wait = max(wait, int(result.get('retry_after') or 0))
                except (ValueError,TypeError):
                    try:
                        wait = max(wait, (parsedate_to_datetime(result['retry_after'])-datetime.now(timezone.utc)).total_seconds())
                    except (KeyError,ValueError,TypeError,OverflowError): pass
                cooldown_until = asyncio.get_running_loop().time()+wait
                log('API_PAUSED', **result)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Never log server bodies, API listing content or seller identifiers.
                log('CYCLE_FAILED', error_type=type(error).__name__)
            await asyncio.sleep(60+random.uniform(0,5))


def start(bot):
    if getattr(bot,'ebay_live_task',None) is None:
        bot.ebay_live_task = asyncio.create_task(run(bot))
        def done(task):
            if not task.cancelled() and task.exception():
                log('WORKER_STOPPED', error_type=type(task.exception()).__name__)
        bot.ebay_live_task.add_done_callback(done)


async def stop(bot):
    task = getattr(bot,'ebay_live_task',None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
