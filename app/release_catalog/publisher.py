"""Separate automatic release publisher. Retailer event queue remains independent."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from .publishing_store import PublishingStore
from .publishing_format import notice_embed, audience_event
from .service import CatalogError

LOG = logging.getLogger(__name__)


class ReleasePublisher:
    def __init__(self, bot, ingestion, verifier):
        self.bot = bot
        self.store = PublishingStore(ingestion, verifier)
        self.task = None
        self.state = 'NOT_STARTED'
        self.last_error = None
        self.last_tick = None
        self.view = None
        self.send_locks = {}

    def start(self):
        from .publishing_ui import ReviewEntry
        if self.view is None:
            self.view = ReviewEntry(self)
            self.bot.add_view(self.view)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name='lotus-release-publisher')
        return self.task

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.state = 'STOPPED'

    async def channel(self, n):
        guild = self.bot.get_guild(n['guild_id'])
        if guild is None:
            raise CatalogError('Server is unavailable.')
        channel = guild.get_channel(n['channel_id'])
        if channel is None:
            channel = await self.bot.fetch_channel(n['channel_id'])
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != n['guild_id']:
            raise CatalogError('Configured release channel is unavailable in this server.')
        return channel

    async def mentions(self, n, channel):
        from app.worker import get_eligible_members, build_mention_chunks
        from app.config import ALERT_ACCESS
        tier = ALERT_ACCESS.get('release_radar', {}).get('minimum_tier', 'Premium+')
        try:
            async with asyncio.timeout(8):
                members = await get_eligible_members(channel.guild, audience_event(n), 'release_radar', tier)
                # Channel access is an additional condition, never a replacement for tier/preferences.
                members = [m for m in members if channel.permissions_for(m).view_channel]
                return build_mention_chunks(members)
        except Exception as error:
            LOG.warning('LOTUS RADAR AUDIENCE | Alert=%s | Type=%s | Mentions=NONE', n['id'], type(error).__name__)
            return []

    async def sync(self, n):
        """Edit the original message; corrections never generate another ping."""
        if not n.get('message_id') or not n['dirty'] or n['state'] != 'SENT':
            return
        async with self.send_locks.setdefault(n['id'], asyncio.Lock()):
            n = await self.store.refresh(n['guild_id'], n['id'])
            if not n['dirty']:
                return
            try:
                channel = await self.channel(n)
                await channel.get_partial_message(n['message_id']).edit(embed=notice_embed(n), view=self.view,
                    allowed_mentions=discord.AllowedMentions.none())
                await self.store.delivery(n['guild_id'], n['id'], state='SENT', revision=n['revision'])
            except discord.NotFound:
                # A moderator may intentionally delete a notice. Never recreate it automatically.
                await self.store.delivery(n['guild_id'], n['id'], state='DELETED', error='MESSAGE_DELETED')
                raise CatalogError('The original alert was deleted. Review is saved; the message will not be reposted.')
            except Exception as error:
                await self.store.delivery(n['guild_id'], n['id'], state='SENT', error=type(error).__name__)
                raise

    async def recover(self, n):
        """Find an acknowledged-lost send by its durable alert marker, without replaying it."""
        if n['state'] not in ('SENDING', 'UNCERTAIN') or not n.get('attempt_at'):
            return
        attempt = datetime.fromisoformat(n['attempt_at'])
        if datetime.now(timezone.utc) - attempt < timedelta(seconds=90):
            return
        channel = await self.channel(n)
        marker = f" • Alert #{n['id']} • "
        async for message in channel.history(limit=100, after=attempt - timedelta(seconds=10), oldest_first=True):
            if message.author.id != self.bot.user.id:
                continue
            if any(marker in (e.footer.text or '') for e in message.embeds):
                await self.store.delivery(n['guild_id'], n['id'], state='SENT', message=message.id)
                return
        await self.store.delivery(n['guild_id'], n['id'], state='UNCERTAIN', error='DELIVERY_NOT_RECONCILED')

    async def deliver(self, guild, nid):
        n = await self.store.refresh(guild, nid)
        if n['state'] == 'SENT':
            await self.sync(n)
            return
        if n['state'] in ('SENDING', 'UNCERTAIN'):
            await self.recover(n)
            return
        if n['state'] not in ('READY', 'RETRY'):
            return
        from app.event_listing_filter import is_event_listing
        if n['payload']['facts']['status'] == 'ARCHIVED' or is_event_listing(n['payload']['facts']['title']):
            await self.store.delivery(guild, nid, state='SKIPPED', error='ARCHIVED_OR_EVENT_LISTING')
            return
        # Resolve the route before reserving the send. No source HTTP checks here.
        try:
            channel = await self.channel(n)
        except Exception as error:
            await self.store.delivery(guild, nid, state='RETRY', error=type(error).__name__)
            return
        n = await self.store.claim(guild, nid)
        if n is None:
            return
        try:
            channel = await self.channel(n)
            chunks = await self.mentions(n, channel)
            message = await channel.send(content=chunks[0] if chunks else None, embed=notice_embed(n),
                view=self.view, nonce=str(n['id']),
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))
        except (discord.Forbidden, discord.NotFound) as error:
            await self.store.delivery(guild, nid, state='RETRY', error=type(error).__name__)
            return
        except discord.HTTPException as error:
            state = 'RETRY' if error.status < 500 else 'UNCERTAIN'
            await self.store.delivery(guild, nid, state=state, error=f'HTTP_{error.status}')
            return
        except Exception as error:
            # An HTTP timeout can mean Discord accepted the message. Do not blindly resend.
            await self.store.delivery(guild, nid, state='UNCERTAIN', error=type(error).__name__)
            return
        await self.store.delivery(guild, nid, state='SENT', message=message.id, revision=n['revision'])
        LOG.info('LOTUS RADAR SENT | Guild=%s | Alert=%s | Message=%s | Review=%s', guild, nid, message.id, n['review_state'])
        # Same entitlement-filtered overflow behavior as the existing stock worker.
        # Persist the main delivery first so a failed extra mention cannot duplicate its embed.
        for chunk in chunks[1:]:
            try:
                await channel.send(content=chunk, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))
            except Exception as error:
                LOG.warning('LOTUS RADAR MENTION ERROR | Alert=%s | Type=%s', nid, type(error).__name__)

    async def tick(self):
        for guild in await self.store.enabled_guilds():
            await self.store.stage(guild)
            for nid in await self.store.work(guild):
                try:
                    async with asyncio.timeout(35):
                        await self.deliver(guild, nid)
                except Exception as error:
                    self.last_error = type(error).__name__
                    LOG.error('LOTUS RADAR PUBLISH ERROR | Guild=%s | Alert=%s | Type=%s', guild, nid, self.last_error)

    async def run(self):
        await self.bot.wait_until_ready()
        try:
            while not self.bot.is_closed():
                try:
                    self.state, self.last_error = 'RUNNING', None
                    self.last_tick = datetime.now(timezone.utc).isoformat()
                    await self.tick()
                except Exception as error:
                    self.state, self.last_error = 'ERROR', type(error).__name__
                    LOG.error('LOTUS RADAR PUBLISH WORKER | Type=%s', self.last_error)
                await asyncio.sleep(5)
        finally:
            self.state = 'STOPPED'
