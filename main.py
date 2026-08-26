import os
import discord
from discord.ext import commands
from discord import app_commands


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 0.3
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")


# =========================================================
# GAME ROLES
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
# SUBSCRIPTION ROLES
# =========================================================

SUBSCRIPTION_ROLES = {
    "Premium+": os.getenv("ROLE_PREMIUM_PLUS"),
    "Premium": os.getenv("ROLE_PREMIUM"),
    "Lite": os.getenv("ROLE_LITE"),
    "Free": os.getenv("ROLE_FREE"),
}


# =========================================================
# CHANNELS
# =========================================================

CHANNEL_ROLES = os.getenv("CHANNEL_ROLES")
CHANNEL_TARGET = os.getenv("CHANNEL_TARGET")
CHANNEL_PREORDER_ALERTS = os.getenv("CHANNEL_PREORDER_ALERTS")
CHANNEL_EARLY_PAGE_DETECTION = os.getenv("CHANNEL_EARLY_PAGE_DETECTION")
CHANNEL_DEALS = os.getenv("CHANNEL_DEALS")
CHANNEL_INTERNATIONAL_EXCLUSIVES = os.getenv(
    "CHANNEL_INTERNATIONAL_EXCLUSIVES"
)
CHANNEL_INVENTORY_FLICKERS = os.getenv("CHANNEL_INVENTORY_FLICKERS")
CHANNEL_RELEASE_RADAR = os.getenv("CHANNEL_RELEASE_RADAR")


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
    member_role_ids = {role.id for role in member.roles}

    # Highest tier wins
    for tier in ["Premium+", "Premium", "Lite", "Free"]:
        role_id = safe_int(SUBSCRIPTION_ROLES.get(tier))

        if role_id and role_id in member_role_ids:
            return tier

    return "Free"


def get_followed_games(member: discord.Member):
    member_role_ids = {role.id for role in member.roles}

    followed = []

    for game_name, role_id in GAME_ROLES.items():
        role_id = safe_int(role_id)

        if role_id and role_id in member_role_ids:
            followed.append(game_name)

    return followed


# =========================================================
# SUBSCRIPTION ACCESS
# =========================================================

TIER_LEVELS = {
    "Free": 0,
    "Lite": 1,
    "Premium": 2,
    "Premium+": 3,
}


def tier_allows(current_tier, minimum_tier):
    return (
        TIER_LEVELS.get(current_tier, 0)
        >= TIER_LEVELS.get(minimum_tier, 0)
    )


# =========================================================
# ALERT ACCESS
# =========================================================

ALERT_ACCESS = {
    "major_retailer": {
        "minimum_tier": "Free",
        "channel": lambda: CHANNEL_TARGET,
    },
    "preorder": {
        "minimum_tier": "Lite",
        "channel": lambda: CHANNEL_PREORDER_ALERTS,
    },
    "page_live": {
        "minimum_tier": "Premium",
        "channel": lambda: CHANNEL_EARLY_PAGE_DETECTION,
    },
    "deal": {
        "minimum_tier": "Premium",
        "channel": lambda: CHANNEL_DEALS,
    },
    "international": {
        "minimum_tier": "Premium",
        "channel": lambda: CHANNEL_INTERNATIONAL_EXCLUSIVES,
    },
    "inventory_flicker": {
        "minimum_tier": "Premium+",
        "channel": lambda: CHANNEL_INVENTORY_FLICKERS,
    },
    "release_radar": {
        "minimum_tier": "Premium+",
        "channel": lambda: CHANNEL_RELEASE_RADAR,
    },
}


# =========================================================
# GAME DATA
# =========================================================

GAME_DATA = [
    ("One Piece", "🏴‍☠️", "One Piece Card Game alerts"),
    ("Pokemon", "⚡", "Pokemon TCG alerts"),
    ("Gundam", "🤖", "Gundam Card Game alerts"),
    (
        "Dragon Ball Fusion World",
        "🐉",
        "Dragon Ball Fusion World alerts",
    ),
    ("Riftbound", "🌀", "Riftbound alerts"),
    ("Palworld", "🟢", "Palworld TCG alerts"),
    ("Naruto", "🍥", "Naruto TCG alerts"),
    ("Cyberpunk TCG", "🌃", "Cyberpunk TCG alerts"),
    ("Azuki TCG", "🔴", "Azuki TCG alerts"),
    ("Hellbreak TCG", "🔥", "Hellbreak TCG alerts"),
]


# =========================================================
# UPDATE GAME ROLES
# =========================================================

async def update_game_roles(
    interaction: discord.Interaction,
    selected_games
):
    member = interaction.user

    if not isinstance(member, discord.Member):
        return False, "❌ This must be used inside the server."

    selected_games = set(selected_games)

    added_roles = []
    removed_roles = []
    errors = []

    for game_name, role_id in GAME_ROLES.items():
        role_id = safe_int(role_id)

        if not role_id:
            errors.append(f"{game_name}: Role ID not configured")
            continue

        role = interaction.guild.get_role(role_id)

        if role is None:
            errors.append(f"{game_name}: Role not found")
            continue

        if game_name in selected_games:
            if role not in member.roles:
                try:
                    await member.add_roles(
                        role,
                        reason="Lotus Tracker game selection"
                    )
                    added_roles.append(game_name)

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
                    removed_roles.append(game_name)

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
# /GAMES SELECTOR
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

            selected = (
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
                    default=selected,
                )
            )

        super().__init__(
            placeholder="Choose the TCGs you want to follow...",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        _, message = await update_game_roles(
            interaction,
            self.values
        )

        await interaction.response.edit_message(
            content=message,
            embed=None,
            view=None,
        )


class GameSelectView(discord.ui.View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=300)
        self.add_item(GameSelect(member))


# =========================================================
# PERMANENT #ROLES SELECTOR
# =========================================================

class PersistentGameSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=game_name,
                description=description,
                emoji=emoji,
                value=game_name,
            )
            for game_name, emoji, description in GAME_DATA
        ]

        super().__init__(
            custom_id="lotus_persistent_game_selector",
            placeholder="Choose the TCGs you want alerts for...",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        _, message = await update_game_roles(
            interaction,
            self.values
        )

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


class PersistentGameSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PersistentGameSelect())


# =========================================================
# BOT
# =========================================================

class LotusTrackerBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
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
# READY
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
            name="TCG drops worldwide 🌎",
        )
    )


# =========================================================
# /PING
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check if Lotus Tracker Bot is online."
)
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        (
            "🏓 **Lotus Tracker Bot is online!**\n"
            f"Latency: `{latency}ms`"
        ),
        ephemeral=True,
    )


# =========================================================
# /GAMES
# =========================================================

@bot.tree.command(
    name="games",
    description="Choose which TCGs you want alerts for."
)
async def games(interaction: discord.Interaction):
    member = interaction.user

    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Use this command inside the server.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="🎴 Choose Your TCGs",
        description=(
            "Select every game you want **Lotus Tracker Bot** "
            "to monitor for you.\n\n"
            "**Game roles determine which games you follow.**\n"
            "**Your subscription determines which features you unlock.**"
        ),
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
        inline=False,
    )

    embed.set_footer(
        text="Lotus Tracker Bot • PonDeX Trackers"
    )

    await interaction.response.send_message(
        embed=embed,
        view=GameSelectView(member),
        ephemeral=True,
    )


# =========================================================
# /SETUPGAMES
# =========================================================

@bot.tree.command(
    name="setupgames",
    description="Post the permanent game-role selector."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setupgames(interaction: discord.Interaction):
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Use this inside the server.",
                ephemeral=True,
            )
            return

        channel_id = safe_int(CHANNEL_ROLES)

        if not channel_id:
            await interaction.followup.send(
                "❌ `CHANNEL_ROLES` is missing or invalid.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(
            channel_id
        )

        if channel is None:
            await interaction.followup.send(
                "❌ I could not find `#roles`.",
                ephemeral=True,
            )
            return

        bot_member = interaction.guild.me
        permissions = channel.permissions_for(
            bot_member
        )

        if not permissions.view_channel:
            await interaction.followup.send(
                "❌ Lotus cannot view `#roles`.",
                ephemeral=True,
            )
            return

        if not permissions.send_messages:
            await interaction.followup.send(
                "❌ Lotus cannot send messages in `#roles`.",
                ephemeral=True,
            )
            return

        if not permissions.embed_links:
            await interaction.followup.send(
                "❌ Lotus needs **Embed Links** in `#roles`.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🎴 Choose Your Games",
            description=(
                "Choose every TCG you want alerts for.\n\n"
                "You may select **as many games as you want**.\n\n"
                "Game roles control **which games you follow**.\n"
                "Your subscription controls **which features you unlock**."
            ),
        )

        embed.add_field(
            name="Available Games",
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
            inline=False,
        )

        embed.set_footer(
            text="Lotus Tracker Bot • PonDeX Trackers"
        )

        await channel.send(
            embed=embed,
            view=PersistentGameSelectView(),
        )

        await interaction.followup.send(
            (
                "✅ Permanent selector posted in "
                f"{channel.mention}."
            ),
            ephemeral=True,
        )

    except Exception as error:
        print(
            "SETUPGAMES ERROR: "
            f"{type(error).__name__}: {error}"
        )

        await interaction.followup.send(
            (
                "❌ Setup failed.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# /SUBSCRIPTION
# =========================================================

@bot.tree.command(
    name="subscription",
    description="View your PonDeX Trackers subscription."
)
async def subscription(
    interaction: discord.Interaction
):
    member = interaction.user

    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Use this command inside the server.",
            ephemeral=True,
        )
        return

    tier = get_subscription(member)
    followed_games = get_followed_games(member)

    games_text = (
        "\n".join(
            f"• {game}"
            for game in followed_games
        )
        if followed_games
        else "No games selected yet."
    )

    tier_details = {
        "Free": (
            "⚪",
            "$0",
            (
                "• Major retailer alerts\n"
                "• Basic stock alerts\n"
                "• Game role selection"
            ),
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
            ),
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
                "• Advanced discovery"
            ),
        ),
        "Premium+": (
            "💎",
            "$44.99/month",
            (
                "• Everything in Premium\n"
                "• Earliest detections\n"
                "• Global intelligence\n"
                "• Inventory Flicker ⚡\n"
                "• Cart Watch 🛒\n"
                "• Forwarder intelligence\n"
                "• Landed-cost analysis\n"
                "• Priority drops\n"
                "• Authorized purchasing where supported"
            ),
        ),
    }

    icon, price, features = tier_details[tier]

    embed = discord.Embed(
        title=f"{icon} Your PonDeX Subscription",
        description=(
            f"**Current Plan:** {tier}\n"
            f"**Price:** {price}"
        ),
    )

    embed.add_field(
        name="Your Access",
        value=features,
        inline=False,
    )

    embed.add_field(
        name="Games You Follow",
        value=games_text,
        inline=False,
    )

    embed.set_footer(
        text="Lotus Tracker Bot • PonDeX Trackers"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /SETTINGS
# =========================================================

@bot.tree.command(
    name="settings",
    description="View your Lotus Tracker Bot settings."
)
async def settings(
    interaction: discord.Interaction
):
    member = interaction.user

    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Use this command inside the server.",
            ephemeral=True,
        )
        return

    tier = get_subscription(member)
    followed_games = get_followed_games(member)

    games_text = (
        "\n".join(
            f"✅ {game}"
            for game in followed_games
        )
        if followed_games
        else "No games selected"
    )

    features = [
        ("Major Retailer Alerts", "Free"),
        ("Preorder Alerts", "Lite"),
        ("Early Page Detection", "Premium"),
        ("Price Drops & Deals", "Premium"),
        ("International Alerts", "Premium"),
        ("Release Radar", "Premium+"),
        ("Inventory Flicker ⚡", "Premium+"),
        ("Cart Watch 🛒", "Premium+"),
    ]

    feature_lines = []

    for feature_name, required_tier in features:
        unlocked = tier_allows(
            tier,
            required_tier
        )

        symbol = "✅" if unlocked else "🔒"

        feature_lines.append(
            f"{symbol} {feature_name}"
        )

    embed = discord.Embed(
        title="⚙️ Lotus Tracker Settings",
        description=(
            f"**Subscription:** {tier}\n\n"
            "More personal alert controls will be added "
            "when the database system is connected."
        ),
    )

    embed.add_field(
        name="🎴 Games You Follow",
        value=games_text,
        inline=False,
    )

    embed.add_field(
        name="🔔 Feature Access",
        value="\n".join(feature_lines),
        inline=False,
    )

    embed.add_field(
        name="Change Games",
        value=(
            "Use `/games` or the selector in `#roles`."
        ),
        inline=False,
    )

    embed.set_footer(
        text="Lotus Tracker Bot • Version 0.3"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# TEST ALERT EMBEDS
# =========================================================

def build_test_alert_embed(
    alert_type,
    game
):
    if alert_type == "major_retailer":
        embed = discord.Embed(
            title="🚨 MAJOR RETAILER DROP",
            description=f"**{game} Test Product**",
        )

        embed.add_field(
            name="Store",
            value="Target",
            inline=True,
        )

        embed.add_field(
            name="Price",
            value="$29.99",
            inline=True,
        )

        embed.add_field(
            name="Status",
            value="🟢 IN STOCK",
            inline=True,
        )

        embed.add_field(
            name="Alert Tier",
            value="FREE+",
            inline=False,
        )

    elif alert_type == "preorder":
        embed = discord.Embed(
            title="🟣 PREORDER LIVE",
            description=f"**{game} Upcoming Product**",
        )

        embed.add_field(
            name="Price",
            value="$119.99",
            inline=True,
        )

        embed.add_field(
            name="Status",
            value="✅ PREORDER OPEN",
            inline=True,
        )

        embed.add_field(
            name="Alert Tier",
            value="LITE+",
            inline=False,
        )

    elif alert_type == "page_live":
        embed = discord.Embed(
            title="🔵 EARLY PAGE DETECTION",
            description=f"**{game} New Product Page**",
        )

        embed.add_field(
            name="Page",
            value="Detected",
            inline=True,
        )

        embed.add_field(
            name="Purchasable",
            value="❌ Not Yet",
            inline=True,
        )

        embed.add_field(
            name="Alert Tier",
            value="PREMIUM+",
            inline=False,
        )

    elif alert_type == "deal":
        embed = discord.Embed(
            title="🔥 DEAL DETECTED",
            description=f"**{game} Test Booster Box**",
        )

        embed.add_field(
            name="Price",
            value="$89.99",
            inline=True,
        )

        embed.add_field(
            name="Market",
            value="$129.99",
            inline=True,
        )

        embed.add_field(
            name="Savings",
            value="30.8%",
            inline=True,
        )

        embed.add_field(
            name="Deal Score",
            value="92 / 100 🔥",
            inline=False,
        )

        embed.add_field(
            name="Alert Tier",
            value="PREMIUM+",
            inline=False,
        )

    elif alert_type == "international":
        embed = discord.Embed(
            title="🌎 INTERNATIONAL EXCLUSIVE",
            description=(
                f"**{game} Japan Exclusive Test Product**"
            ),
        )

        embed.add_field(
            name="Region",
            value="🇯🇵 Japan",
            inline=True,
        )

        embed.add_field(
            name="Local Price",
            value="¥7,980",
            inline=True,
        )

        embed.add_field(
            name="USD",
            value="≈ $54.00",
            inline=True,
        )

        embed.add_field(
            name="US Shipping",
            value="✅ Available",
            inline=True,
        )

        embed.add_field(
            name="Alert Tier",
            value="PREMIUM+",
            inline=False,
        )

    elif alert_type == "inventory_flicker":
        embed = discord.Embed(
            title="⚡ INVENTORY FLICKER",
            description=(
                f"**{game} High-Demand Test Product**"
            ),
        )

        embed.add_field(
            name="Store",
            value="Target",
            inline=True,
        )

        embed.add_field(
            name="Status",
            value="🟢 AVAILABLE NOW",
            inline=True,
        )

        embed.add_field(
            name="Recent Activity",
            value=(
                "🔴 OUT\n"
                "🟢 IN\n"
                "🔴 OUT\n"
                "🟢 IN"
            ),
            inline=False,
        )

        embed.add_field(
            name="Action",
            value="🔥 TRY CHECKOUT NOW",
            inline=False,
        )

        embed.add_field(
            name="Alert Tier",
            value="💎 PREMIUM+ ONLY",
            inline=False,
        )

    elif alert_type == "release_radar":
        embed = discord.Embed(
            title="📡 RELEASE RADAR",
            description=(
                f"**Potential New {game} Product Detected**"
            ),
        )

        embed.add_field(
            name="Current State",
            value="🟡 RETAILER LISTING",
            inline=True,
        )

        embed.add_field(
            name="Official Confirmation",
            value="❌ Not Yet",
            inline=True,
        )

        embed.add_field(
            name="Confidence",
            value="Medium",
            inline=True,
        )

        embed.add_field(
            name="Alert Tier",
            value="💎 PREMIUM+",
            inline=False,
        )

    else:
        embed = discord.Embed(
            title="Lotus Test Alert",
            description="Unknown alert type.",
        )

    embed.set_footer(
        text=(
            "TEST ALERT • Lotus Tracker Bot "
            "• PonDeX Trackers"
        )
    )

    return embed


# =========================================================
# /TESTALERT
# =========================================================

@bot.tree.command(
    name="testalert",
    description="Send a simulated PonDeX alert."
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    game=[
        app_commands.Choice(
            name="One Piece",
            value="One Piece",
        ),
        app_commands.Choice(
            name="Pokemon",
            value="Pokemon",
        ),
        app_commands.Choice(
            name="Gundam",
            value="Gundam",
        ),
        app_commands.Choice(
            name="Dragon Ball Fusion World",
            value="Dragon Ball Fusion World",
        ),
        app_commands.Choice(
            name="Riftbound",
            value="Riftbound",
        ),
        app_commands.Choice(
            name="Palworld",
            value="Palworld",
        ),
        app_commands.Choice(
            name="Naruto",
            value="Naruto",
        ),
        app_commands.Choice(
            name="Cyberpunk TCG",
            value="Cyberpunk TCG",
        ),
        app_commands.Choice(
            name="Azuki TCG",
            value="Azuki TCG",
        ),
        app_commands.Choice(
            name="Hellbreak TCG",
            value="Hellbreak TCG",
        ),
    ],
    alert_type=[
        app_commands.Choice(
            name="Major Retailer",
            value="major_retailer",
        ),
        app_commands.Choice(
            name="Preorder",
            value="preorder",
        ),
        app_commands.Choice(
            name="Early Page Detection",
            value="page_live",
        ),
        app_commands.Choice(
            name="Deal",
            value="deal",
        ),
        app_commands.Choice(
            name="International Exclusive",
            value="international",
        ),
        app_commands.Choice(
            name="Inventory Flicker",
            value="inventory_flicker",
        ),
        app_commands.Choice(
            name="Release Radar",
            value="release_radar",
        ),
    ],
)
async def testalert(
    interaction: discord.Interaction,
    game: app_commands.Choice[str],
    alert_type: app_commands.Choice[str],
):
    await interaction.response.defer(
        ephemeral=True
    )

    if interaction.guild is None:
        await interaction.followup.send(
            "❌ Use this command inside the server.",
            ephemeral=True,
        )
        return

    config = ALERT_ACCESS.get(
        alert_type.value
    )

    if config is None:
        await interaction.followup.send(
            "❌ Unknown alert type.",
            ephemeral=True,
        )
        return

    channel_id = safe_int(
        config["channel"]()
    )

    if not channel_id:
        await interaction.followup.send(
            (
                "❌ The Railway channel variable for "
                "this alert type is missing."
            ),
            ephemeral=True,
        )
        return

    channel = interaction.guild.get_channel(
        channel_id
    )

    if channel is None:
        await interaction.followup.send(
            "❌ Lotus could not find that channel.",
            ephemeral=True,
        )
        return

    game_role_id = safe_int(
        GAME_ROLES.get(game.value)
    )

    game_role = (
        interaction.guild.get_role(game_role_id)
        if game_role_id
        else None
    )

    embed = build_test_alert_embed(
        alert_type.value,
        game.value,
    )

    mention_text = (
        game_role.mention
        if game_role
        else f"**{game.value}**"
    )

    await channel.send(
        content=mention_text,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=False,
            everyone=False,
        ),
    )

    await interaction.followup.send(
        (
            "✅ **Test alert sent!**\n\n"
            f"**Game:** {game.value}\n"
            f"**Alert:** {alert_type.name}\n"
            f"**Minimum Tier:** "
            f"{config['minimum_tier']}\n"
            f"**Channel:** {channel.mention}"
        ),
        ephemeral=True,
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
            "**Permanent Game Selector:** Online ✅\n"
            "**Subscription Detection:** Online ✅\n"
            "**Subscription Access Engine:** Online ✅\n"
            "**Test Alert Engine:** Online ✅\n"
            "**Monitoring Engine:** Coming Soon\n"
            "**Product Database:** Coming Soon\n"
            "**Live Alert Engine:** Coming Soon\n\n"
            f"**Latency:** {latency}ms\n"
            "**Version:** 0.3"
        ),
    )

    embed.set_footer(
        text="PonDeX Trackers"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# ERROR HANDLERS
# =========================================================

@setupgames.error
async def setupgames_error(
    interaction: discord.Interaction,
    error
):
    if isinstance(
        error,
        app_commands.MissingPermissions
    ):
        message = (
            "❌ Only administrators can use `/setupgames`."
        )
    else:
        message = (
            "❌ `/setupgames` encountered an error.\n\n"
            f"`{type(error).__name__}: {error}`"
        )

    if interaction.response.is_done():
        await interaction.followup.send(
            message,
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


@testalert.error
async def testalert_error(
    interaction: discord.Interaction,
    error
):
    if isinstance(
        error,
        app_commands.MissingPermissions
    ):
        message = (
            "❌ Only administrators can use `/testalert`."
        )
    else:
        message = (
            "❌ `/testalert` encountered an error.\n\n"
            f"`{type(error).__name__}: {error}`"
        )

    if interaction.response.is_done():
        await interaction.followup.send(
            message,
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )


bot.run(TOKEN)