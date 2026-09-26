"""Private catalog commands; automatic public notices use the separate publisher."""
from __future__ import annotations

import json
import logging

import discord
from discord import app_commands

from . import VERSION
from .service import CatalogError, FORMATS, SOURCE_KINDS, STATUSES, ReleaseCatalog
from .source_confidence import confidence

LOG = logging.getLogger(__name__)
SAFETY = "Admin tools • Source evidence retained • Publishing: /release radar publishing"


def safe(value, maximum: int = 1000) -> str:
    text = discord.utils.escape_mentions(discord.utils.escape_markdown(str(value)))
    return text if len(text) <= maximum else text[:maximum - 1] + "…"


def embed(title: str, description: str = "") -> discord.Embed:
    result = discord.Embed(title=title, description=description or None, colour=0x667ACD)
    result.set_footer(text=f"Lotus Release Catalog v{VERSION} • {SAFETY}")
    return result


def release_embed(row: dict, heading: str = "Release record") -> discord.Embed:
    result = embed(f"{heading} • #{row['id']}", safe(row["title"], 250))
    for name, value in (
        ("Listing confidence", confidence(row)['label']), ("Game", row["game"]), ("Format", row["product_format"]),
        ("Region", row["region"]), ("Language", row["language"]),
        ("Confirmed release date", row["release_date"] or "Unknown / not confirmed"),
    ):
        result.add_field(name=name, value=safe(value, 180), inline=True)
    parts = []
    for label, key in (
        ("Set/prefix", "set_code"), ("Cards per pack", "reported_cards_per_pack"),
        ("Packs per display box", "reported_packs_per_box"), ("Boxes per case", "reported_boxes_per_case"),
    ):
        parts.append(f"{label}: {safe(row[key] if row[key] is not None else 'Unknown', 70)}")
    foil = row["reported_all_foil"]
    parts.append(f"All foil: {'Unknown' if foil is None else ('Reported yes' if foil else 'Reported no')}")
    result.add_field(name="Reported details — NOT independently verified", value="\n".join(parts), inline=False)
    result.add_field(name="Original reported text (excerpt)", value=safe(row["reported_details"], 850), inline=False)
    if row["confirmed_source_id"] is not None:
        automatic = row.get("confirmation_mode") == "AUTOMATIC_SOURCE_POLICY"
        result.add_field(
            name="Confirmation provenance",
            value=(f"Source #{row['confirmed_source_id']} • automatic source policy approved by admin ID {row['confirmed_by']}\n"
                   "Extracted automatically; no per-item human attestation."
                   if automatic else f"Source #{row['confirmed_source_id']} • reviewed by admin ID {row['confirmed_by']}\n"
                   "Human attestation of release/date only; not a customer preorder."),
            inline=False,
        )
    return result


def page_embed(data: dict, title: str) -> discord.Embed:
    lines = []
    for row in data["items"]:
        lines.append(
            f"**#{row['id']} • {safe(row['title'], 170)}**\n"
            f"{safe(row['game'], 60)} • {confidence(row)['label']} • {row['release_date'] or 'Date unknown'}\n"
            f"{safe(row['region'], 40)} / {safe(row['language'], 40)} • {row['product_format']}"
        )
    body = "\n\n".join(lines) or "No matching releases. Rumors and undated releases are not on the confirmed calendar."
    if "start" in data:
        body = f"{data['start']} through {data['end']} (inclusive)\n\n" + body
    body += f"\n\nPage {data['page']}" + (" • More results: request the next page." if data["has_more"] else " • End of results.")
    return embed(title, body)


class ReleaseCommands(app_commands.Group):
    def __init__(self, catalog: ReleaseCatalog):
        super().__init__(
            name="release", description="Admin-reviewed release catalog and calendar preview",
            guild_only=True, default_permissions=discord.Permissions(administrator=True),
        )
        self.catalog = catalog
        from .ingestion_commands import ReleaseWatchCommands
        self.watch_group = ReleaseWatchCommands(self)
        self.add_command(self.watch_group)
        from .official_commands import OfficialCommands
        self.add_command(OfficialCommands(self))
        from .radar_commands import RadarCommands
        self.add_command(RadarCommands(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # UI defaults can be overridden in a server: runtime authorization is
        # mandatory as well. Do not rely on the visibility of the command alone.
        permissions = getattr(interaction, "permissions", None)
        if interaction.guild_id is None or not getattr(permissions, "administrator", False):
            message = "The release catalog is an administrator-only server preview."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            else:
                await interaction.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return False
        return True

    async def _run(self, interaction, action, render):
        # Repeat the guard here so direct callback invocation cannot bypass it.
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = render(await action())
        except CatalogError as error:
            result = embed("No change made", safe(error, 1800))
        except Exception as error:
            # Do not log source text, database connection strings or SQL params.
            LOG.error("LOTUS RELEASE CATALOG ERROR | Version=%s | Type=%s", VERSION, type(error).__name__)
            result = embed("Release catalog unavailable", "The operation could not be confirmed. Check Railway for LOTUS RELEASE CATALOG ERROR, then use /release show or /release list before retrying. No stock alerts are emitted by this module.")
        await interaction.followup.send(embed=result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure) and interaction.response.is_done():
            return
        LOG.error("LOTUS RELEASE COMMAND ERROR | Version=%s | Type=%s", VERSION, type(error).__name__)
        message = "Release command could not complete. Check the command options and try again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="status", description="Check catalog version, scope and record counts")
    async def status(self, interaction: discord.Interaction):
        await self._run(interaction, lambda: self.catalog.stats(interaction.guild_id), lambda counts: embed(
            f"Lotus Release Catalog v{VERSION}",
            "Database: ready\nMode: administrator-only preview\n"
            + "\n".join(f"{key}: {value}" for key, value in counts.items())
            + "\n\nAutomatic sources: configure /release watch add\nWorker state: /release watch status\n"
              "AI model calls: OFF\nPublishing settings: /release radar publishing\n"
              "Calendar dates carry manual or approved source-policy provenance.",
        ))

    @app_commands.command(name="add", description="Save an unverified release lead; a source link is optional")
    @app_commands.describe(
        details="Forwarded text or reported facts (max 4000 characters; never treated as verified)",
        source_label="Where you received this, or leave the original source marked unknown",
        set_code="Reported prefix/code only; do not invent a sequence number",
        packs_per_box="Packs in one display box, NOT boxes per case",
    )
    @app_commands.choices(product_format=[app_commands.Choice(name=x.title(), value=x) for x in FORMATS])
    async def add(
        self, interaction: discord.Interaction, game: str, title: str, details: str,
        source_label: str = "Forwarded community message; original source unknown",
        source_url: str | None = None, set_code: str | None = None,
        region: str = "UNKNOWN", language: str = "UNKNOWN", product_format: str = "UNKNOWN",
        cards_per_pack: app_commands.Range[int, 1, 10000] | None = None,
        packs_per_box: app_commands.Range[int, 1, 10000] | None = None,
        boxes_per_case: app_commands.Range[int, 1, 10000] | None = None,
        all_foil: bool | None = None,
    ):
        def render(data):
            result = release_embed(data["release"], "Release lead saved" if data["created"] else "Existing record — unchanged")
            if not data["created"]:
                result.add_field(name="Duplicate protection", value="Nothing was overwritten. Use /release source to attach new information.", inline=False)
            return result
        async def work():
            data = await self.catalog.add(
                interaction.guild_id, interaction.user.id, game=game, title=title, details=details,
                source_label=source_label, source_url=source_url, set_code=set_code, region=region,
                language=language, product_format=product_format, cards_per_pack=cards_per_pack,
                packs_per_box=packs_per_box, boxes_per_case=boxes_per_case, all_foil=all_foil,
            )
            data['release'] = (await self.catalog.get(interaction.guild_id, data['release']['id']))['release']
            return data
        await self._run(interaction, work, render)

    @app_commands.command(name="source", description="Attach source evidence and update listing confidence")
    @app_commands.choices(kind=[app_commands.Choice(name=x.title(), value=x) for x in SOURCE_KINDS])
    @app_commands.describe(note="What the source actually supports; distinguish retailer claims from publisher facts")
    async def source(self, interaction: discord.Interaction, release_id: int, kind: str, label: str, note: str, url: str | None = None, supporting_url: str | None = None):
        def render(data):
            row = data["source"]
            result = embed("Evidence saved" if data["created"] else "Existing evidence — unchanged", f"Release #{row['release_id']} • Source #{row['id']}\nType: {row['kind']}\n"
                f"{data['listing_confidence']['label']}\nExact date and stock status were not changed.")
            result.add_field(name="Label", value=safe(row["label"], 180), inline=False)
            result.add_field(name="URL", value=safe(row["url"] or "Not provided", 1000), inline=False)
            result.add_field(name="Evidence note (excerpt)", value=safe(row["note"], 1000), inline=False)
            return result
        async def work():
            from .service import public_source_url
            recorded_note = note
            if supporting_url:
                recorded_note = json.dumps({'note': note, 'supporting_urls': [public_source_url(supporting_url, required=True)]})
            data = await self.catalog.add_source(interaction.guild_id, interaction.user.id, release_id,
                kind=kind, label=label, note=recorded_note, url=url)
            data['listing_confidence'] = (await self.catalog.get(interaction.guild_id, release_id))['release']['listing_confidence']
            return data
        await self._run(interaction, work, render)

    @app_commands.command(name="show", description="Inspect a release, reported details and recent provenance")
    async def show(self, interaction: discord.Interaction, release_id: int):
        async def read():
            data = await self.catalog.get(interaction.guild_id, release_id)
            data['official'] = await self.watch_group.runner.official.result(interaction.guild_id, release_id)
            return data
        def render(data):
            result = release_embed(data["release"])
            result.add_field(name="Latest evidence (use /release sources for links)", value="\n".join(f"#{s['id']} • {s['kind']} • {safe(s['label'], 110)}" for s in data["sources"]) or "None", inline=False)
            check=data['official']['check']
            windows=[w['label']+' ('+w['precision']+', '+e['match_scope']+')' for e in check.get('evidence',[]) for w in e['windows']]
            result.add_field(name="Official publisher check", value=safe(check['state']+'\n'+' / '.join(windows),750)+f"\nDetails: /release official check release_id:{release_id}", inline=False)
            result.add_field(name="Recent history (UTC)", value="\n".join(f"{a['recorded_at'][:19]} • {a['action']} • admin {a['actor_id']}" for a in data["audit"]) or "None", inline=False)
            return result
        await self._run(interaction, read, render)

    @app_commands.command(name="sources", description="List evidence IDs, links and excerpts for a release")
    async def sources(self, interaction: discord.Interaction, release_id: int, page: app_commands.Range[int, 1, 10000] = 1):
        def render(data):
            result = embed(f"Release #{release_id} • Evidence • Page {page}")
            for source in data["items"]:
                result.add_field(name=f"#{source['id']} • {source['kind']}", value=f"{safe(source['label'], 130)}\n{safe(source['url'] or 'No source URL supplied', 250)}\n{safe(source['note'], 80)}", inline=False)
            result.description = "Saved evidence, not automated verification. Use /release evidence for an unabridged URL. " + ("More results: request the next page." if data["has_more"] else "End of results.")
            return result
        await self._run(interaction, lambda: self.catalog.sources(interaction.guild_id, release_id, page), render)

    @app_commands.command(name="evidence", description="Inspect one source with its complete saved URL")
    async def evidence(self, interaction: discord.Interaction, release_id: int, source_id: int):
        def render(source):
            result = embed(f"Release #{release_id} • Source #{source_id}")
            # URLs are validated as credential-free HTTPS with no whitespace or
            # angle brackets; angle-link syntax preserves long paths verbatim.
            url = f"<{source['url']}>" if source["url"] else "No source URL supplied"
            result.description = f"{safe(source['label'], 220)}\nType: {source['kind']}\n\n{url}\n\n{safe(source['note'], 1600)}"
            result.add_field(name="Recorded provenance (not publication time)", value=f"{source['recorded_at']}\nAdministrator ID: {source['recorded_by']}", inline=False)
            return result
        await self._run(interaction, lambda: self.catalog.evidence(interaction.guild_id, release_id, source_id), render)

    @app_commands.command(name="history", description="Inspect confirmation notes, corrections and retractions")
    async def history(self, interaction: discord.Interaction, release_id: int, page: app_commands.Range[int, 1, 10000] = 1):
        def render(data):
            result = embed(f"Release #{release_id} • History • Page {page}")
            for audit in data["items"]:
                details = json.loads(audit["details_json"])
                before, after = details.get("before", {}), details.get("after", {})
                summary = details.get("review_note") or details.get("reason") or f"Source #{details.get('source_id', '?')}"
                date_change = f"\nDate: {before.get('release_date') or 'Unknown'} → {after.get('release_date') or 'Unknown'}" if "before" in details else ""
                result.add_field(name=f"{audit['action']} • {audit['recorded_at'][:19]} UTC", value=f"Admin {audit['actor_id']} • Audit #{audit['id']}\n{safe(summary, 300)}{date_change}", inline=False)
            result.description = "Immutable history; notes may be excerpted. " + ("More results: request the next page." if data["has_more"] else "End of results.")
            return result
        await self._run(interaction, lambda: self.catalog.history(interaction.guild_id, release_id, page), render)

    @app_commands.command(name="list", description="List releases, including rumors and undated records")
    @app_commands.choices(status=[app_commands.Choice(name=x.title(), value=x) for x in ("ALL", "CONFIRMED", "LEAKED", "RUMORED", "ARCHIVED")])
    async def list_command(self, interaction: discord.Interaction, status: str = "ALL", game: str | None = None, page: app_commands.Range[int, 1, 10000] = 1):
        await self._run(interaction, lambda: self.catalog.list_releases(interaction.guild_id, status=status, game=game, page=page), lambda data: page_embed(data, "Release catalog"))

    @app_commands.command(name="confirm", description="Attest to a publisher/distributor source; no automatic verification")
    @app_commands.describe(
        reviewed="True only after you personally verify source identity and the release/date/scope",
        review_note="Explain what you checked; stored in the audit history",
        release_date="Exact YYYY-MM-DD, or omit for undated (also clears a previously recorded date)",
        title="Optional official title correction; original report remains in history",
        region="Date-specific region supported by the source, e.g. US",
        language="Date-specific edition language supported by the source, e.g. English",
    )
    async def confirm(
        self, interaction: discord.Interaction, release_id: int, source_id: int, reviewed: bool,
        review_note: str, release_date: str | None = None, title: str | None = None,
        region: str | None = None, language: str | None = None, set_code: str | None = None,
    ):
        await self._run(interaction, lambda: self.catalog.confirm(
            interaction.guild_id, interaction.user.id, release_id, source_id=source_id,
            reviewed=reviewed, review_note=review_note, release_date=release_date,
            title=title, region=region, language=language, set_code=set_code,
        ), lambda row: release_embed(row, "Admin-reviewed confirmation saved"))

    @app_commands.command(name="calendar", description="Preview confirmed, dated releases only (admin-only)")
    @app_commands.describe(start="YYYY-MM-DD; defaults to today's UTC date", days="Number of dates, inclusive of start")
    async def calendar(
        self, interaction: discord.Interaction, start: str | None = None,
        days: app_commands.Range[int, 1, 730] = 90, game: str | None = None,
        region: str | None = None, language: str | None = None,
        page: app_commands.Range[int, 1, 10000] = 1,
    ):
        await self._run(interaction, lambda: self.catalog.calendar(interaction.guild_id, start=start, days=days, game=game, region=region, language=language, page=page), lambda data: page_embed(data, "Confirmed release calendar — admin preview"))

    @app_commands.command(name="trace", description="Inspect a retailer product, recorded events and linked Discord deliveries")
    async def trace(self, interaction: discord.Interaction, store_id: int, url: str):
        from app.alert_trace import trace_product
        async def read():
            try:
                return await trace_product(self.catalog.sessions, store_id, url,
                    [c.id for c in list(interaction.guild.channels)+list(interaction.guild.threads)])
            except ValueError as error:
                raise CatalogError(str(error)) from None
        def render(data):
            lines=[f"Store: {safe(data['store'],80)} • Active: {data['active']} • {data['health']}"]
            if data['last_store_error']: lines.append('Store error: '+safe(data['last_store_error'],250))
            product=data['product']
            if product:
                lines.append(f"Stored product #{product['id']} • In stock: {product['in_stock']}\nStatus: {safe(product['status'],80)} • Last seen (UTC): {product['last_seen']}\nVariant: {product['variant_id'] or 'Unknown'}")
            else:
                lines.append('No unique stored product match. Discovery/classification may not have captured it; this is not proof the page was never live.')
            lines.append('**Recent recorded events**')
            lines.extend(f"{safe(e['type'],60)} • {e['at']} UTC • In stock: {e['in_stock']}" for e in data['events'])
            if not data['events']: lines.append('No matching event history. Earlier availability cannot be reconstructed.')
            lines.append('**Linked deliveries in this server**')
            for d in data['deliveries']:
                lines.append(f"{safe(d['type'],60)} • {d['at']} UTC\nhttps://discord.com/channels/{interaction.guild_id}/{d['channel']}/{d['message']}")
            if not data['deliveries']: lines.append('No linked delivery found. Older delivery rows lack product/store IDs; absence does not prove no alert was sent.')
            lines.append('Read-only: no scan or test ping was sent. Event records alone do not prove successful queueing or delivery.')
            return embed('Product alert trace','\n\n'.join(lines)[:3900])
        await self._run(interaction,read,render)

    @app_commands.command(name="retract", description="Return a release to unverified; remove its date from the calendar")
    async def retract(self, interaction: discord.Interaction, release_id: int, reason: str):
        await self._run(interaction, lambda: self.catalog.change_status(interaction.guild_id, interaction.user.id, release_id, status="RUMORED", reason=reason), lambda row: release_embed(row, "Returned to unverified"))

    @app_commands.command(name="archive", description="Archive a lead without deleting its source or audit history")
    async def archive(self, interaction: discord.Interaction, release_id: int, reason: str):
        await self._run(interaction, lambda: self.catalog.change_status(interaction.guild_id, interaction.user.id, release_id, status="ARCHIVED", reason=reason), lambda row: release_embed(row, "Archived"))


def register_release_catalog_commands(bot, *, catalog: ReleaseCatalog | None = None) -> ReleaseCommands:
    """Call once AFTER bot exists and BEFORE bot.run()/tree.sync(). No network I/O."""
    existing = bot.tree.get_command("release")
    if existing is not None:
        if isinstance(existing, ReleaseCommands):
            return existing
        raise RuntimeError("A different /release command already exists; resolve the name conflict before installing.")
    if catalog is None:
        from app.database import engine
        catalog = ReleaseCatalog(engine)
    group = ReleaseCommands(catalog)
    bot.release_ingestion = group.watch_group.runner
    from .publisher import ReleasePublisher
    group.publisher = ReleasePublisher(bot, group.watch_group.store, group.watch_group.runner.official)
    bot.release_publisher = group.publisher
    bot.tree.add_command(group)
    print(f"LOTUS RELEASE CATALOG | Version={VERSION} | Commands=REGISTERED | Mode=ADMIN_ONLY | AI=OFF | Publishing=CONFIGURED_SEPARATELY", flush=True)
    return group
