"""Read-only MTG configuration diagnostics; no scans or test alert sends."""
import discord
from discord import app_commands
from app.config import GAME_ROLES, CHANNEL_MAP, ALERT_ACCESS
from app.helpers import safe_int
from app.mtg_products import VERSION


def mtg_status_embed(guild):
    embed = discord.Embed(title=f"MTG retailer integration {VERSION}", color=0x8E63CE)
    role_id = safe_int(GAME_ROLES.get("MTG"))
    role = guild.get_role(role_id) if role_id else None
    me = guild.me
    if role is None:
        role_status = "Missing. Set Railway ROLE_MTG to this server's Magic: The Gathering role ID."
    else:
        manageable = bool(me and me.guild_permissions.manage_roles and me.top_role > role
                          and not role.managed and not role.is_default())
        role_status = f"{role.mention}\nBot can assign role: {'Yes' if manageable else 'No — check Manage Roles and role order'}"
        role_status += f"\nCached followers: {sum(not member.bot for member in role.members)}"
    embed.add_field(name="MTG game role", value=role_status, inline=False)
    lines = []
    labels = (("shopify", "Shop stock"), ("preorder", "Preorders"),
              ("page_live", "New pages"), ("deal", "Deals"),
              ("international", "International"), ("inventory_flicker", "Flickers"))
    for route, label in labels:
        access = ALERT_ACCESS.get(route, {})
        variable = access.get("channel_variable", "")
        channel_id = safe_int(CHANNEL_MAP.get(variable))
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            state = f"Missing ({variable or 'route configuration'})"
        else:
            permissions = channel.permissions_for(me) if me else None
            writable = bool(permissions and permissions.view_channel and permissions.send_messages
                            and permissions.embed_links)
            state = f"{channel.mention} • {'Writable' if writable else 'Check bot permissions'}"
        lines.append(f"{label}: {state} • {access.get('minimum_tier', 'Unknown')}")
    embed.add_field(name="Existing alert destinations", value="\n".join(lines), inline=False)
    embed.add_field(name="Member setup", value=(
        "Select MTG in /games. Use /alertprefs, /myprefs and /familyprefs with MTG. "
        "Repost /setupgames to update an older public game menu. "
        "Stock alerts send automatically; admin review is not a gate."
    ), inline=False)
    embed.description = (
        "Shopify and existing universal adapters recognize supported MTG products. "
        "These are configuration checks, not proof of live stock, retailer coverage or delivery speed. "
        "Existing source budgets, stock evidence, deduplication and member entitlement checks apply."
    )
    embed.set_footer(text="MTG 1.0.0 • Read-only • No scan or alert sent")
    return embed


def register_mtg_commands(bot):
    @bot.tree.command(name="mtgstatus", description="Check MTG role and retailer alert destinations.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mtgstatus(interaction: discord.Interaction):
        await interaction.response.send_message(embed=mtg_status_embed(interaction.guild), ephemeral=True)
