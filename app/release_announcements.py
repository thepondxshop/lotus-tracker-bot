"""Explicit admin publishing; never announce on startup or reconnect."""
from app.version import VERSION, ANNOUNCEMENT_CHANNEL_ID, announcement, release_kind

async def deliver_once(reserve, send, mark_sent):
    if not await reserve():
        return 'Already published or reserved. Check the announcement channel before investigating a pending send.'
    try:
        message = await send()
        await mark_sent(message.id)
    except Exception as error:
        print(f"LOTUS RELEASE DELIVERY UNCERTAIN | Version={VERSION} | Error={type(error).__name__}", flush=True)
        # An HTTP timeout can occur after Discord accepted the message. Keep reservation.
        return 'Delivery outcome uncertain. Reservation retained to prevent duplicates; inspect the channel and logs. Do not blindly retry.'
    return f'Published release {VERSION} (message {message.id}).'

def register_release_announcements(bot):
    import discord
    from discord import app_commands
    from sqlalchemy import text
    from app.database import SessionLocal

    @bot.tree.command(name='botrelease', description='Preview or publish the current Lotus release announcement.')
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def botrelease(interaction: discord.Interaction, publish: bool = False):
        await interaction.response.defer(ephemeral=True)
        content = announcement()
        kind = release_kind()
        if not publish:
            await interaction.followup.send(content+'\n\nPreview only. Use /botrelease publish:True to publish.', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID) or await bot.fetch_channel(ANNOUNCEMENT_CHANNEL_ID)
        if getattr(getattr(channel, 'guild', None), 'id', None) != interaction.guild_id:
            await interaction.followup.send('Announcement channel must belong to this server.', ephemeral=True)
            return
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.view_channel or not perms.send_messages or (kind == 'major' and not perms.mention_everyone):
            await interaction.followup.send('Missing announcement channel permissions (major releases also require Mention Everyone).', ephemeral=True)
            return
        async def reserve():
            async with SessionLocal() as session:
                await session.execute(text('CREATE TABLE IF NOT EXISTS lotus_release_announcements (channel_id BIGINT NOT NULL, version TEXT NOT NULL, state TEXT NOT NULL, message_id BIGINT, reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(channel_id, version))'))
                result = await session.execute(text("INSERT INTO lotus_release_announcements(channel_id,version,state) VALUES(:channel,:version,'RESERVED') ON CONFLICT DO NOTHING RETURNING version"), {'channel':channel.id,'version':VERSION})
                inserted = result.scalar_one_or_none() is not None
                await session.commit()
                return inserted
        async def send():
            return await channel.send(content, allowed_mentions=discord.AllowedMentions(everyone=kind=='major', users=False, roles=False, replied_user=False))
        async def mark_sent(message_id):
            async with SessionLocal() as session:
                await session.execute(text("UPDATE lotus_release_announcements SET state='SENT',message_id=:message WHERE channel_id=:channel AND version=:version"), {'message':message_id,'channel':channel.id,'version':VERSION})
                await session.commit()
        result = await deliver_once(reserve, send, mark_sent)
        await interaction.followup.send(result, ephemeral=True)
