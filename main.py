import os
import discord
from discord.ext import commands


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")


# =========================================================
# GAME ROLE IDS
#
# These are loaded from Railway Variables.
# Do NOT put your Discord bot token here.
# =========================================================

GAME_ROLES = {
    "One Piece": os.getenv("ROLE_ONE_PIECE"),
    "Pokemon": os.getenv("ROLE_POKEMON"),
    "Gundam": os.getenv("ROLE_GUNDAM"),
    "Dragon Ball Fusion World": os.getenv("ROLE_DRAGON_BALL"),
    "Riftbound": os.getenv("ROLE_RIFTBOUND"),
    "Palworld": os.getenv("ROLE_PALWORLD"),
    "Naruto": os.getenv("ROLE_NARUTO"),
    "Cyberpunk TCG": os.getenv("ROLE_CYBERPUNK"),
    "Azuki TCG": os.getenv("ROLE_AZUKI"),
    "Hellbreak TCG": os.getenv("ROLE_HELLBREAK"),
}


# =========================================================
# DISCORD INTENTS
# =========================================================

intents = discord.Intents.default()

# Required because Lotus Tracker Bot manages member game roles
intents.members = True


# =========================================================
# BOT
# =========================================================

class LotusTrackerBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):
        # Makes slash commands appear in Discord
        synced = await self.tree.sync()

        print(
            f"Synced {len(synced)} slash command(s)."
        )


bot = LotusTrackerBot()


# =========================================================
# READY EVENT
# =========================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(f"Lotus Tracker Bot is ONLINE!")
    print(f"Logged in as: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("=" * 50)

    # Discord status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="TCG drops 🌎"
        )
    )


# =========================================================
# /PING
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check if Lotus Tracker Bot is online."
)
async def ping(
    interaction: discord.Interaction
):

    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        f"🏓 **Lotus Tracker Bot is online!**\n"
        f"Latency: `{latency}ms`",
        ephemeral=True
    )


# =========================================================
# GAME SELECT MENU
# =========================================================

class GameSelect(discord.ui.Select):

    def __init__(self, member: discord.Member):

        self.member = member

        # Find which game roles the member already has
        current_roles = {
            role.id
            for role in member.roles
        }

        options = []

        game_data = [
            (
                "One Piece",
                "🏴‍☠️",
                "One Piece Card Game alerts"
            ),
            (
                "Pokemon",
                "⚡",
                "Pokemon TCG alerts"
            ),
            (
                "Gundam",
                "🤖",
                "Gundam Card Game alerts"
            ),
            (
                "Dragon Ball Fusion World",
                "🐉",
                "Dragon Ball Fusion World alerts"
            ),
            (
                "Riftbound",
                "🌀",
                "Riftbound alerts"
            ),
            (
                "Palworld",
                "🟢",
                "Palworld TCG alerts"
            ),
            (
                "Naruto",
                "🍥",
                "Naruto TCG alerts"
            ),
            (
                "Cyberpunk TCG",
                "🌃",
                "Cyberpunk TCG alerts"
            ),
            (
                "Azuki TCG",
                "🔴",
                "Azuki TCG alerts"
            ),
            (
                "Hellbreak TCG",
                "🔥",
                "Hellbreak TCG alerts"
            ),
        ]

        for game_name, emoji, description in game_data:

            role_id = GAME_ROLES.get(game_name)

            is_selected = False

            if role_id:
                try:
                    is_selected = (
                        int(role_id)
                        in current_roles
                    )
                except ValueError:
                    pass

            options.append(
                discord.SelectOption(
                    label=game_name,
                    description=description,
                    emoji=emoji,
                    value=game_name,
                    default=is_selected
                )
            )

        super().__init__(
            placeholder="Choose the TCGs you want to follow...",
            min_values=0,
            max_values=len(options),
            options=options
        )


    async def callback(
        self,
        interaction: discord.Interaction
    ):

        member = interaction.user

        if not isinstance(
            member,
            discord.Member
        ):
            await interaction.response.send_message(
                "❌ This command can only be used inside the PonDeX Trackers server.",
                ephemeral=True
            )
            return

        selected_games = set(self.values)

        added_roles = []
        removed_roles = []
        errors = []

        # Go through every game role
        for game_name, role_id in GAME_ROLES.items():

            if not role_id:
                errors.append(
                    f"{game_name}: Role ID not configured"
                )
                continue

            try:
                role_id = int(role_id)

            except ValueError:
                errors.append(
                    f"{game_name}: Invalid Role ID"
                )
                continue

            role = interaction.guild.get_role(
                role_id
            )

            if role is None:
                errors.append(
                    f"{game_name}: Role not found"
                )
                continue

            # =========================================
            # USER SELECTED THIS GAME
            # =========================================

            if game_name in selected_games:

                if role not in member.roles:

                    try:
                        await member.add_roles(
                            role,
                            reason="Lotus Tracker Bot game selection"
                        )

                        added_roles.append(
                            game_name
                        )

                    except discord.Forbidden:
                        errors.append(
                            f"{game_name}: Bot cannot assign role"
                        )

            # =========================================
            # USER DESELECTED THIS GAME
            # =========================================

            else:

                if role in member.roles:

                    try:
                        await member.remove_roles(
                            role,
                            reason="Lotus Tracker Bot game selection"
                        )

                        removed_roles.append(
                            game_name
                        )

                    except discord.Forbidden:
                        errors.append(
                            f"{game_name}: Bot cannot remove role"
                        )


        # =========================================
        # BUILD CONFIRMATION MESSAGE
        # =========================================

        message = (
            "✅ **Your TCG alert preferences were updated!**\n\n"
        )

        if selected_games:

            message += (
                "**You are following:**\n"
            )

            for game in sorted(selected_games):
                message += f"• {game}\n"

        else:

            message += (
                "**You are currently not following any games.**\n"
            )


        if added_roles:

            message += (
                "\n➕ **Roles added:**\n"
            )

            for game in added_roles:
                message += f"• {game}\n"


        if removed_roles:

            message += (
                "\n➖ **Roles removed:**\n"
            )

            for game in removed_roles:
                message += f"• {game}\n"


        if errors:

            message += (
                "\n⚠️ **Configuration warnings:**\n"
            )

            for error in errors:
                message += f"• {error}\n"


        await interaction.response.edit_message(
            content=message,
            view=None
        )


# =========================================================
# GAME SELECT VIEW
# =========================================================

class GameSelectView(discord.ui.View):

    def __init__(
        self,
        member: discord.Member
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            GameSelect(member)
        )


# =========================================================
# /GAMES
# =========================================================

@bot.tree.command(
    name="games",
    description="Choose which TCGs you want alerts for."
)
async def games(
    interaction: discord.Interaction
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ This command must be used inside the PonDeX Trackers server.",
            ephemeral=True
        )

        return


    embed = discord.Embed(
        title="🎴 Choose Your TCGs",
        description=(
            "Choose **all of the games you want Lotus Tracker Bot to monitor for you.**\n\n"
            "Your game roles work with **every subscription level**.\n\n"
            "Your subscription determines which alerts you can access.\n"
            "Your game roles determine which games you follow.\n\n"
            "You can return to `/games` anytime to change your selections."
        )
    )


    embed.add_field(
        name="Available Games",
        value=(
            "🏴‍☠️ One Piece\n"
            "⚡ Pokémon\n"
            "🤖 Gundam\n"
            "🐉 Dragon Ball Fusion World\n"
            "🌀 Riftbound\n"
            "🟢 Palworld\n"
            "🍥 Naruto\n"
            "🌃 Cyberpunk TCG\n"
            "🔴 Azuki TCG\n"
            "🔥 Hellbreak TCG"
        ),
        inline=False
    )


    embed.set_footer(
        text="Lotus Tracker Bot • PonDeX Trackers"
    )


    view = GameSelectView(member)


    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )


# =========================================================
# /STATUS
# =========================================================

@bot.tree.command(
    name="status",
    description="Check Lotus Tracker Bot system status."
)
async def status(
    interaction: discord.Interaction
):

    latency = round(
        bot.latency * 1000
    )

    embed = discord.Embed(
        title="🟢 Lotus Tracker Bot Status",
        description=(
            "**Status:** Online\n"
            f"**Latency:** {latency}ms\n"
            "**Discord:** Connected\n"
            "**Monitoring System:** Coming Soon\n"
            "**Version:** 0.1"
        )
    )

    embed.set_footer(
        text="PonDeX Trackers"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )


bot.run(TOKEN)