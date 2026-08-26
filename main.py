import os
import discord
from discord.ext import commands


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 0.2.1
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")


# =========================================================
# GAME ROLE IDS
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
# SUBSCRIPTION ROLE IDS
# =========================================================

SUBSCRIPTION_ROLES = {
    "Premium+": os.getenv("ROLE_PREMIUM_PLUS"),
    "Premium": os.getenv("ROLE_PREMIUM"),
    "Lite": os.getenv("ROLE_LITE"),
    "Free": os.getenv("ROLE_FREE"),
}


# =========================================================
# CHANNEL IDS
# =========================================================

CHANNEL_ROLES = os.getenv("CHANNEL_ROLES")


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()
intents.members = True


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_subscription(member: discord.Member):

    member_role_ids = {
        role.id
        for role in member.roles
    }

    tier_order = [
        "Premium+",
        "Premium",
        "Lite",
        "Free",
    ]

    for tier in tier_order:

        role_id = safe_int(
            SUBSCRIPTION_ROLES.get(tier)
        )

        if role_id and role_id in member_role_ids:
            return tier

    return "Free"


def get_followed_games(member: discord.Member):

    member_role_ids = {
        role.id
        for role in member.roles
    }

    followed = []

    for game_name, role_id in GAME_ROLES.items():

        role_id = safe_int(role_id)

        if role_id and role_id in member_role_ids:
            followed.append(game_name)

    return followed


# =========================================================
# GAME DATA
# =========================================================

GAME_DATA = [
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


# =========================================================
# PERSISTENT GAME SELECTOR
# =========================================================

class PersistentGameSelect(discord.ui.Select):

    def __init__(self):

        options = []

        for game_name, emoji, description in GAME_DATA:

            options.append(
                discord.SelectOption(
                    label=game_name,
                    description=description,
                    emoji=emoji,
                    value=game_name
                )
            )

        super().__init__(
            custom_id="lotus_persistent_game_selector",
            placeholder="Choose the TCGs you want alerts for...",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        success, message = await update_game_roles(
            interaction,
            self.values
        )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )


class PersistentGameSelectView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            PersistentGameSelect()
        )


# =========================================================
# NORMAL /GAMES SELECTOR
# =========================================================

class GameSelect(discord.ui.Select):

    def __init__(self, member: discord.Member):

        current_role_ids = {
            role.id
            for role in member.roles
        }

        options = []

        for game_name, emoji, description in GAME_DATA:

            role_id = safe_int(
                GAME_ROLES.get(game_name)
            )

            is_selected = (
                role_id in current_role_ids
                if role_id
                else False
            )

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

        success, message = await update_game_roles(
            interaction,
            self.values
        )

        await interaction.response.edit_message(
            content=message,
            embed=None,
            view=None
        )


class GameSelectView(discord.ui.View):

    def __init__(self, member: discord.Member):

        super().__init__(
            timeout=300
        )

        self.add_item(
            GameSelect(member)
        )


# =========================================================
# SHARED GAME ROLE UPDATE LOGIC
# =========================================================

async def update_game_roles(
    interaction: discord.Interaction,
    selected_games
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member
    ):
        return (
            False,
            "❌ This feature must be used inside the server."
        )

    selected_games = set(selected_games)

    added_roles = []
    removed_roles = []
    errors = []

    for game_name, role_id in GAME_ROLES.items():

        role_id = safe_int(role_id)

        if not role_id:
            errors.append(
                f"{game_name}: Role ID not configured"
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

        if game_name in selected_games:

            if role not in member.roles:

                try:

                    await member.add_roles(
                        role,
                        reason="Lotus Tracker game selection"
                    )

                    added_roles.append(
                        game_name
                    )

                except discord.Forbidden:

                    errors.append(
                        f"{game_name}: Cannot assign role"
                    )

        else:

            if role in member.roles:

                try:

                    await member.remove_roles(
                        role,
                        reason="Lotus Tracker game selection"
                    )

                    removed_roles.append(
                        game_name
                    )

                except discord.Forbidden:

                    errors.append(
                        f"{game_name}: Cannot remove role"
                    )

    message = (
        "✅ **Your game alert preferences were updated!**\n\n"
    )

    if selected_games:

        message += "**You are following:**\n"

        for game in sorted(selected_games):
            message += f"• {game}\n"

    else:

        message += (
            "**You are currently not following any games.**\n"
        )

    if added_roles:

        message += "\n➕ **Roles added:**\n"

        for game in added_roles:
            message += f"• {game}\n"

    if removed_roles:

        message += "\n➖ **Roles removed:**\n"

        for game in removed_roles:
            message += f"• {game}\n"

    if errors:

        message += "\n⚠️ **Warnings:**\n"

        for error in errors:
            message += f"• {error}\n"

    return True, message


# =========================================================
# BOT CLASS
# =========================================================

class LotusTrackerBot(commands.Bot):

    def __init__(self):

        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):

        self.add_view(
            PersistentGameSelectView()
        )

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

    print("=" * 60)
    print("Lotus Tracker Bot is ONLINE!")
    print(f"Logged in as: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("=" * 60)

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="TCG drops worldwide 🌎"
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

    latency = round(
        bot.latency * 1000
    )

    await interaction.response.send_message(
        (
            "🏓 **Lotus Tracker Bot is online!**\n"
            f"Latency: `{latency}ms`"
        ),
        ephemeral=True
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
            "❌ This command must be used inside the server.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="🎴 Choose Your TCGs",
        description=(
            "Select every game you want **Lotus Tracker Bot** "
            "to monitor for you.\n\n"
            "**Game roles determine what games you follow.**\n"
            "**Your subscription determines which features you unlock.**\n\n"
            "You can run `/games` anytime to change your selections."
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

    await interaction.response.send_message(
        embed=embed,
        view=GameSelectView(member),
        ephemeral=True
    )


# =========================================================
# /SETUPGAMES
#
# Posts permanent role selector in #roles
# Administrator-only
# =========================================================

@bot.tree.command(
    name="setupgames",
    description="Post the permanent game-role selector."
)
@discord.app_commands.checks.has_permissions(
    administrator=True
)
async def setupgames(
    interaction: discord.Interaction
):

    # Immediately acknowledge command
    # so Discord doesn't show "Application did not respond"
    await interaction.response.defer(
        ephemeral=True
    )

    try:

        if interaction.guild is None:

            await interaction.followup.send(
                "❌ This command must be used inside the server.",
                ephemeral=True
            )

            return


        # -----------------------------------------
        # CHECK CHANNEL ID
        # -----------------------------------------

        channel_id = safe_int(
            CHANNEL_ROLES
        )

        if not channel_id:

            await interaction.followup.send(
                (
                    "❌ `CHANNEL_ROLES` is missing or invalid in Railway.\n\n"
                    "It should contain only the numeric Discord channel ID."
                ),
                ephemeral=True
            )

            return


        # -----------------------------------------
        # FIND CHANNEL
        # -----------------------------------------

        channel = interaction.guild.get_channel(
            channel_id
        )

        if channel is None:

            await interaction.followup.send(
                (
                    "❌ I could not find the configured `#roles` channel.\n\n"
                    "Check that `CHANNEL_ROLES` contains the correct "
                    "numeric Discord channel ID."
                ),
                ephemeral=True
            )

            return


        # -----------------------------------------
        # MAKE SURE IT IS A TEXT CHANNEL
        # -----------------------------------------

        if not isinstance(
            channel,
            discord.TextChannel
        ):

            await interaction.followup.send(
                (
                    "❌ `CHANNEL_ROLES` must point to a "
                    "normal Discord text channel."
                ),
                ephemeral=True
            )

            return


        # -----------------------------------------
        # CHECK BOT PERMISSIONS
        # -----------------------------------------

        bot_member = interaction.guild.me

        if bot_member is None:

            await interaction.followup.send(
                "❌ I could not determine my Discord server permissions.",
                ephemeral=True
            )

            return


        permissions = channel.permissions_for(
            bot_member
        )


        if not permissions.view_channel:

            await interaction.followup.send(
                "❌ Lotus Tracker Bot cannot view `#roles`.",
                ephemeral=True
            )

            return


        if not permissions.send_messages:

            await interaction.followup.send(
                "❌ Lotus Tracker Bot cannot send messages in `#roles`.",
                ephemeral=True
            )

            return


        if not permissions.embed_links:

            await interaction.followup.send(
                (
                    "❌ Lotus Tracker Bot needs the "
                    "**Embed Links** permission in `#roles`."
                ),
                ephemeral=True
            )

            return


        # -----------------------------------------
        # BUILD PERMANENT ROLES PANEL
        # -----------------------------------------

        embed = discord.Embed(
            title="🎴 Choose Your Games",
            description=(
                "Choose the TCGs you want to receive alerts for.\n\n"
                "You may select **as many games as you want**.\n\n"
                "Your game roles control **which games you follow**.\n"
                "Your subscription controls **which alert features you unlock**.\n\n"
                "You can come back here anytime and change your selections."
            )
        )


        embed.add_field(
            name="Games",
            value=(
                "🏴‍☠️ **One Piece**\n"
                "⚡ **Pokémon**\n"
                "🤖 **Gundam**\n"
                "🐉 **Dragon Ball Fusion World**\n"
                "🌀 **Riftbound**\n"
                "🟢 **Palworld**\n"
                "🍥 **Naruto**\n"
                "🌃 **Cyberpunk TCG**\n"
                "🔴 **Azuki TCG**\n"
                "🔥 **Hellbreak TCG**"
            ),
            inline=False
        )


        embed.set_footer(
            text="Lotus Tracker Bot • PonDeX Trackers"
        )


        # -----------------------------------------
        # POST SELECTOR
        # -----------------------------------------

        await channel.send(
            embed=embed,
            view=PersistentGameSelectView()
        )


        await interaction.followup.send(
            (
                f"✅ Permanent game selector successfully posted in "
                f"{channel.mention}."
            ),
            ephemeral=True
        )


    except Exception as error:

        print(
            f"SETUPGAMES ERROR: "
            f"{type(error).__name__}: {error}"
        )

        try:

            await interaction.followup.send(
                (
                    "❌ Something went wrong while creating "
                    "the game selector.\n\n"
                    f"Error: `{type(error).__name__}: {error}`"
                ),
                ephemeral=True
            )

        except Exception:

            print(
                "Could not send setupgames error message to Discord."
            )


# =========================================================
# /SUBSCRIPTION
# =========================================================

@bot.tree.command(
    name="subscription",
    description="View your PonDeX Trackers subscription and access."
)
async def subscription(
    interaction: discord.Interaction
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ This command must be used inside the server.",
            ephemeral=True
        )

        return


    tier = get_subscription(
        member
    )


    followed_games = get_followed_games(
        member
    )


    if followed_games:

        games_text = "\n".join(
            f"• {game}"
            for game in followed_games
        )

    else:

        games_text = (
            "No games selected yet.\n"
            "Use `/games` or the selector in `#roles`."
        )


    tier_details = {

        "Free": (
            "⚪",
            "$0",
            (
                "• Major retailer alerts\n"
                "• Basic stock alerts\n"
                "• Game role selection"
            )
        ),

        "Lite": (
            "🌿",
            "$1.99/month",
            (
                "• Everything in Free\n"
                "• Preorder alerts\n"
                "• Preorder calendar\n"
                "• Priority support\n"
                "• 14-day free trial"
            )
        ),

        "Premium": (
            "👑",
            "$17.99/month",
            (
                "• Everything in Lite\n"
                "• Small TCG shops\n"
                "• Shopify drops\n"
                "• 1,000+ store network\n"
                "• eBay / marketplaces\n"
                "• Price drops & deals\n"
                "• International alerts\n"
                "• Advanced product discovery"
            )
        ),

        "Premium+": (
            "💎",
            "$44.99/month",
            (
                "• Everything in Premium\n"
                "• Earliest detections\n"
                "• Advanced global intelligence\n"
                "• Inventory Flicker ⚡\n"
                "• Cart Watch 🛒\n"
                "• Forwarder intelligence\n"
                "• Landed-cost analysis\n"
                "• Priority drops\n"
                "• Authorized purchasing where supported"
            )
        ),
    }


    icon, price, features = tier_details[
        tier
    ]


    embed = discord.Embed(
        title=(
            f"{icon} Your PonDeX Subscription"
        ),
        description=(
            f"**Current Plan:** {tier}\n"
            f"**Price:** {price}"
        )
    )


    embed.add_field(
        name="Your Access",
        value=features,
        inline=False
    )


    embed.add_field(
        name="Games You Follow",
        value=games_text,
        inline=False
    )


    embed.set_footer(
        text="Lotus Tracker Bot • PonDeX Trackers"
    )


    await interaction.response.send_message(
        embed=embed,
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
            "**Discord:** Connected ✅\n"
            "**Role System:** Online ✅\n"
            "**Game Selector:** Online ✅\n"
            "**Subscription Detection:** Online ✅\n"
            "**Monitoring Engine:** Coming Soon\n"
            "**Product Database:** Coming Soon\n"
            "**Alert Engine:** Coming Soon\n\n"
            f"**Latency:** {latency}ms\n"
            "**Version:** 0.2.1"
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
# /SETUPGAMES ERROR HANDLER
# =========================================================

@setupgames.error
async def setupgames_error(
    interaction: discord.Interaction,
    error
):

    print(
        "SETUPGAMES COMMAND ERROR: "
        f"{type(error).__name__}: {error}"
    )


    if isinstance(
        error,
        discord.app_commands.MissingPermissions
    ):

        message = (
            "❌ Only server administrators can use `/setupgames`."
        )

    else:

        message = (
            "❌ `/setupgames` encountered an error.\n\n"
            f"`{type(error).__name__}: {error}`"
        )


    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                message,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    except Exception as secondary_error:

        print(
            "SETUPGAMES ERROR HANDLER FAILED: "
            f"{type(secondary_error).__name__}: {secondary_error}"
        )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )


bot.run(TOKEN)