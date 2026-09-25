"""Persistent public Review entry, private permission-checked admin controls."""
import logging
import discord

from .service import CatalogError
from .publishing_format import notice_embed

LOG = logging.getLogger(__name__)


async def reply(interaction, text):
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def authorized(interaction, guild=None, owner=None):
    valid = (interaction.guild_id is not None
             and getattr(getattr(interaction, 'permissions', None), 'administrator', False)
             and (guild is None or interaction.guild_id == guild)
             and (owner is None or interaction.user.id == owner))
    if not valid:
        await reply(interaction, 'Only a server administrator can use these review controls. Open your own Review panel.')
    return valid


async def failure(interaction, error):
    LOG.error('LOTUS RADAR REVIEW ERROR | Type=%s', type(error).__name__)
    await reply(interaction, str(error) if isinstance(error, CatalogError)
                else 'Review could not complete. Reopen Review to check the saved result before retrying.')


class ReviewEntry(discord.ui.View):
    def __init__(self, publisher):
        super().__init__(timeout=None)
        self.publisher = publisher

    async def interaction_check(self, interaction):
        return await authorized(interaction)

    @discord.ui.button(label='Review', emoji='🔎', custom_id='lotus:radar:review:v1', style=discord.ButtonStyle.secondary)
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            n = await self.publisher.store.from_message(interaction.guild_id, interaction.channel_id, interaction.message.id)
            n = await self.publisher.store.refresh(interaction.guild_id, n['id'])
            await interaction.followup.send(content='Review the information below. Choosing Incorrect opens a correction form.',
                embed=notice_embed(n), view=ReviewPanel(self.publisher, n, interaction.user.id),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            await failure(interaction, error)

    async def on_error(self, interaction, error, item):
        await failure(interaction, error)


class ReviewPanel(discord.ui.View):
    def __init__(self, publisher, notice, owner):
        super().__init__(timeout=600)
        self.publisher, self.notice, self.owner = publisher, notice, owner

    async def interaction_check(self, interaction):
        return await authorized(interaction, self.notice['guild_id'], self.owner)

    async def save(self, interaction, action):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            n = await self.publisher.store.reviewed(interaction.guild_id, interaction.user.id,
                self.notice['id'], self.notice['revision'], action)
            try:
                await self.publisher.sync(n)
                message = 'Review saved. The original alert has been updated.'
            except Exception:
                message = 'Review saved. The publisher will retry updating the original alert.'
            self.stop()
            await reply(interaction, message + ' Future stock and price still require fresh observations.')
        except Exception as error:
            await failure(interaction, error)

    @discord.ui.button(label='Correct', emoji='✅', style=discord.ButtonStyle.success)
    async def correct(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.save(interaction, 'CORRECT')

    @discord.ui.button(label='Incorrect', emoji='❌', style=discord.ButtonStyle.danger)
    async def incorrect(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.send_modal(CorrectionModal(self.publisher, self.notice, self.owner))

    @discord.ui.button(label='Still unknown', style=discord.ButtonStyle.secondary)
    async def unknown(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.save(interaction, 'UNKNOWN')

    async def on_error(self, interaction, error, item):
        await failure(interaction, error)


class CorrectionModal(discord.ui.Modal, title='Correct release information'):
    field = discord.ui.TextInput(label='What is wrong?', placeholder='title, game, region, language, format, code, date, or false alert', max_length=40)
    value = discord.ui.TextInput(label='Correct information (if known)', placeholder='Leave blank if the correct information is unknown.', required=False, max_length=180)
    reason = discord.ui.TextInput(label='Explanation', style=discord.TextStyle.paragraph, max_length=1000)
    source = discord.ui.TextInput(label='Supporting HTTPS link (optional)', required=False, max_length=500)

    def __init__(self, publisher, notice, owner):
        super().__init__(timeout=600)
        self.publisher, self.notice, self.owner = publisher, notice, owner

    async def interaction_check(self, interaction):
        return await authorized(interaction, self.notice['guild_id'], self.owner)

    async def on_submit(self, interaction):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            field = str(self.field).strip().casefold().replace(' ', '_')
            field = {'format': 'product_format', 'code': 'set_code', 'date': 'reported_date',
                     'product_title': 'title', 'product_name': 'title'}.get(field, field)
            value, note = str(self.value).strip(), str(self.reason).strip()
            if field in ('false_alert', 'false', 'invalid', 'whole_alert'):
                action = 'INCORRECT'
            elif not value or field == 'unknown':
                action = 'UNKNOWN'
                note = f"Reported problem: {str(self.field).strip()}. {note}"
            else:
                action = 'CORRECT_FIELD'
            n = await self.publisher.store.reviewed(interaction.guild_id, interaction.user.id,
                self.notice['id'], self.notice['revision'], action, field=field, value=value,
                note=note[:1000], source=str(self.source).strip())
            try:
                await self.publisher.sync(n)
                result = 'Review saved and original alert updated.'
            except Exception:
                result = 'Review saved. The original alert update will retry automatically.'
            if action == 'CORRECT_FIELD':
                result += ' This correction is saved for this product/source, not every listing from its retailer.'
            elif action == 'UNKNOWN':
                result += ' The alert remains visibly unverified; no correction was invented.'
            await reply(interaction, result)
        except Exception as error:
            await failure(interaction, error)

    async def on_error(self, interaction, error):
        await failure(interaction, error)
