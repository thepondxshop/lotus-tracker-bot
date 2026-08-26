import asyncio

import discord

from discord.ext import commands
from discord import app_commands

from sqlalchemy import text


from app.config import (
    DISCORD_TOKEN,
    GAME_ROLES,
    GAME_DATA,
    ALERT_ACCESS,
    CHANNEL_MAP,
    CHANNEL_ROLES,
)

from app.helpers import (
    safe_int,
    get_subscription,
    get_followed_games,
    tier_allows,
)

from app.database import (
    init_database,
    SessionLocal,
    load_user_preferences,
    sync_member_to_database,
)

from app.redis_client import (
    init_redis,
    check_redis,
)

from app.events import (
    ProductEvent,
    ProductEventType,
)

from app.event_service import (
    process_product_event,
    get_queue_size,
)

from app.worker import (
    run_event_worker,
)


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 0.5.1
#
# PostgreSQL
# Redis
# Persistent Users
# Product Event Engine
# Background Event Worker
# Automatic Discord Routing
# Affiliate Link Pipeline
# =========================================================


# =========================================================
# INTENTS
# =========================================================

intents = (
    discord.Intents.default()
)

intents.members = True


# =========================================================
# SAVE MEMBER
# =========================================================

async def save_member_to_database(
    member: discord.Member
):

    tier = get_subscription(
        member
    )

    followed_games = (
        get_followed_games(
            member
        )
    )

    await sync_member_to_database(
        member=member,
        subscription_tier=tier,
        selected_games=followed_games,
    )


# =========================================================
# UPDATE GAME ROLES
# =========================================================

async def update_game_roles(
    interaction: discord.Interaction,
    selected_games,
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member
    ):

        return (
            False,
            "❌ This must be used inside the server."
        )

    if interaction.guild is None:

        return (
            False,
            "❌ This must be used inside the server."
        )

    selected_games = set(
        selected_games
    )

    added_roles = []
    removed_roles = []
    errors = []

    for (
        game_name,
        role_id
    ) in GAME_ROLES.items():

        role_id = safe_int(
            role_id
        )

        if not role_id:

            errors.append(
                f"{game_name}: Role ID not configured"
            )

            continue

        role = (
            interaction.guild.get_role(
                role_id
            )
        )

        if role is None:

            errors.append(
                f"{game_name}: Role not found"
            )

            continue

        # -------------------------------------------------
        # ADD
        # -------------------------------------------------

        if game_name in selected_games:

            if role not in member.roles:

                try:

                    await member.add_roles(
                        role,
                        reason=(
                            "Lotus Tracker game selection"
                        ),
                    )

                    added_roles.append(
                        game_name
                    )

                except discord.Forbidden:

                    errors.append(
                        f"{game_name}: Cannot assign role"
                    )

                except discord.HTTPException as error:

                    errors.append(
                        (
                            f"{game_name}: "
                            f"Discord error: {error}"
                        )
                    )

        # -------------------------------------------------
        # REMOVE
        # -------------------------------------------------

        else:

            if role in member.roles:

                try:

                    await member.remove_roles(
                        role,
                        reason=(
                            "Lotus Tracker game selection"
                        ),
                    )

                    removed_roles.append(
                        game_name
                    )

                except discord.Forbidden:

                    errors.append(
                        f"{game_name}: Cannot remove role"
                    )

                except discord.HTTPException as error:

                    errors.append(
                        (
                            f"{game_name}: "
                            f"Discord error: {error}"
                        )
                    )

    # -------------------------------------------------
    # DATABASE
    # -------------------------------------------------

    database_saved = False

    try:

        await save_member_to_database(
            member
        )

        database_saved = True

    except Exception as error:

        print(
            "USER DATABASE SAVE ERROR: "
            f"{type(error).__name__}: {error}"
        )

        errors.append(
            "Database save failed"
        )

    # -------------------------------------------------
    # CONFIRMATION
    # -------------------------------------------------

    actual_games = (
        get_followed_games(
            member
        )
    )

    message = (
        "✅ **Your game alert preferences were updated!**\n\n"
    )

    if actual_games:

        message += (
            "**You are following:**\n"
        )

        for game in sorted(
            actual_games
        ):

            message += (
                f"• {game}\n"
            )

    else:

        message += (
            "**You are currently not following any games.**\n"
        )

    if added_roles:

        message += (
            "\n➕ **Roles added:**\n"
        )

        for game in added_roles:

            message += (
                f"• {game}\n"
            )

    if removed_roles:

        message += (
            "\n➖ **Roles removed:**\n"
        )

        for game in removed_roles:

            message += (
                f"• {game}\n"
            )

    if database_saved:

        message += (
            "\n💾 **Preferences saved to Lotus.**"
        )

    if errors:

        message += (
            "\n\n⚠️ **Warnings:**\n"
        )

        for error in errors:

            message += (
                f"• {error}\n"
            )

    return (
        True,
        message
    )


# =========================================================
# GAME SELECT
# =========================================================

class GameSelect(
    discord.ui.Select
):

    def __init__(
        self,
        member: discord.Member,
    ):

        current_role_ids = {
            role.id
            for role in member.roles
        }

        options = []

        for (
            game_name,
            emoji,
            description
        ) in GAME_DATA:

            role_id = safe_int(
                GAME_ROLES.get(
                    game_name
                )
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
            placeholder=(
                "Choose the TCGs you want to follow..."
            ),
            min_values=0,
            max_values=len(
                options
            ),
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        _, message = (
            await update_game_roles(
                interaction,
                self.values,
            )
        )

        await interaction.response.edit_message(
            content=message,
            embed=None,
            view=None,
        )


class GameSelectView(
    discord.ui.View
):

    def __init__(
        self,
        member: discord.Member,
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            GameSelect(
                member
            )
        )


# =========================================================
# PERSISTENT GAME SELECT
# =========================================================

class PersistentGameSelect(
    discord.ui.Select
):

    def __init__(
        self
    ):

        options = []

        for (
            game_name,
            emoji,
            description
        ) in GAME_DATA:

            options.append(
                discord.SelectOption(
                    label=game_name,
                    description=description,
                    emoji=emoji,
                    value=game_name,
                )
            )

        super().__init__(
            custom_id=(
                "lotus_persistent_game_selector"
            ),
            placeholder=(
                "Choose the TCGs you want alerts for..."
            ),
            min_values=0,
            max_values=len(
                options
            ),
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        _, message = (
            await update_game_roles(
                interaction,
                self.values,
            )
        )

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


class PersistentGameSelectView(
    discord.ui.View
):

    def __init__(
        self
    ):

        super().__init__(
            timeout=None
        )

        self.add_item(
            PersistentGameSelect()
        )


# =========================================================
# BOT CLASS
# =========================================================

class LotusTrackerBot(
    commands.Bot
):

    def __init__(
        self
    ):

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

        self.database_ready = False

        self.database_error = None

        self.redis_ready = False

        self.redis_error = None

        self.event_worker_task = None


    async def setup_hook(
        self
    ):

        # -------------------------------------------------
        # PERSISTENT UI
        # -------------------------------------------------

        self.add_view(
            PersistentGameSelectView()
        )

        # -------------------------------------------------
        # POSTGRESQL
        # -------------------------------------------------

        try:

            await init_database()

            self.database_ready = True

            self.database_error = None

            print(
                "PostgreSQL initialized successfully."
            )

        except Exception as error:

            self.database_ready = False

            self.database_error = (
                f"{type(error).__name__}: {error}"
            )

            print(
                "DATABASE STARTUP ERROR: "
                f"{self.database_error}"
            )

        # -------------------------------------------------
        # REDIS
        # -------------------------------------------------

        try:

            await init_redis()

            self.redis_ready = True

            self.redis_error = None

            print(
                "Redis initialized successfully."
            )

        except Exception as error:

            self.redis_ready = False

            self.redis_error = (
                f"{type(error).__name__}: {error}"
            )

            print(
                "REDIS STARTUP ERROR: "
                f"{self.redis_error}"
            )

        # -------------------------------------------------
        # EVENT WORKER
        # -------------------------------------------------

        self.event_worker_task = (
            asyncio.create_task(
                run_event_worker(
                    self
                )
            )
        )

        print(
            "Lotus Event Worker task created."
        )

        # -------------------------------------------------
        # COMMAND SYNC
        # -------------------------------------------------

        synced = (
            await self.tree.sync()
        )

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

    print(
        "Lotus Tracker Bot is ONLINE!"
    )

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print(
        "Architecture: v0.5.1"
    )

    print(
        "PostgreSQL:",
        (
            "ONLINE"
            if bot.database_ready
            else "OFFLINE"
        )
    )

    print(
        "Redis:",
        (
            "ONLINE"
            if bot.redis_ready
            else "OFFLINE"
        )
    )

    worker_online = (
        bot.event_worker_task is not None
        and not bot.event_worker_task.done()
    )

    print(
        "Event Worker:",
        (
            "ONLINE"
            if worker_online
            else "OFFLINE"
        )
    )

    print("=" * 60)

    await bot.change_presence(
        activity=discord.Activity(
            type=(
                discord.ActivityType.watching
            ),
            name=(
                "TCG drops worldwide 🌎"
            ),
        )
    )


# =========================================================
# /PING
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check if Lotus is online."
)
async def ping(
    interaction: discord.Interaction,
):

    latency = round(
        bot.latency * 1000
    )

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
async def games(
    interaction: discord.Interaction,
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member
    ):

        await interaction.response.send_message(
            (
                "❌ Use this command inside "
                "the Discord server."
            ),
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            "🎴 Choose Your TCGs"
        ),
        description=(
            "Choose every game you want "
            "Lotus Tracker Bot to monitor.\n\n"
            "Your selections are stored "
            "persistently in PostgreSQL."
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
        text=(
            "Lotus Tracker Bot • PonDeX Trackers"
        )
    )

    await interaction.response.send_message(
        embed=embed,
        view=(
            GameSelectView(
                member
            )
        ),
        ephemeral=True,
    )


# =========================================================
# /SETUPGAMES
# =========================================================

@bot.tree.command(
    name="setupgames",
    description="Post the permanent game selector."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setupgames(
    interaction: discord.Interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    if interaction.guild is None:

        await interaction.followup.send(
            "❌ Use this inside the server.",
            ephemeral=True,
        )

        return

    channel_id = safe_int(
        CHANNEL_ROLES
    )

    if not channel_id:

        await interaction.followup.send(
            "❌ CHANNEL_ROLES is missing.",
            ephemeral=True,
        )

        return

    channel = (
        interaction.guild.get_channel(
            channel_id
        )
    )

    if channel is None:

        await interaction.followup.send(
            "❌ Roles channel not found.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            "🎴 Choose Your Games"
        ),
        description=(
            "Choose every TCG you want alerts for.\n\n"
            "Selections are saved to Lotus."
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
        text=(
            "Lotus Tracker Bot • PonDeX Trackers"
        )
    )

    await channel.send(
        embed=embed,
        view=(
            PersistentGameSelectView()
        ),
    )

    await interaction.followup.send(
        (
            f"✅ Selector posted in "
            f"{channel.mention}."
        ),
        ephemeral=True,
    )


# =========================================================
# /SUBSCRIPTION
# =========================================================

@bot.tree.command(
    name="subscription",
    description="View your PonDeX subscription."
)
async def subscription(
    interaction: discord.Interaction,
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ Use this inside the server.",
            ephemeral=True,
        )

        return

    tier = (
        get_subscription(
            member
        )
    )

    games = (
        get_followed_games(
            member
        )
    )

    if bot.database_ready:

        try:

            await save_member_to_database(
                member
            )

        except Exception as error:

            print(
                "SUBSCRIPTION SYNC ERROR: "
                f"{type(error).__name__}: {error}"
            )

    games_text = (
        "\n".join(
            f"• {game}"
            for game in games
        )
        if games
        else "No games selected"
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

    icon, price, features = (
        tier_details[
            tier
        ]
    )

    embed = discord.Embed(
        title=(
            f"{icon} Your PonDeX Subscription"
        ),
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

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /SETTINGS
# =========================================================

@bot.tree.command(
    name="settings",
    description="View your saved Lotus settings."
)
async def settings(
    interaction: discord.Interaction,
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ Use this inside the server.",
            ephemeral=True,
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    profile = None

    if bot.database_ready:

        try:

            profile = (
                await load_user_preferences(
                    member.id
                )
            )

        except Exception as error:

            print(
                "SETTINGS DB ERROR: "
                f"{type(error).__name__}: {error}"
            )

    if profile is None:

        tier = (
            get_subscription(
                member
            )
        )

        games = (
            get_followed_games(
                member
            )
        )

    else:

        tier = (
            profile[
                "subscription"
            ]
        )

        games = (
            profile[
                "games"
            ]
        )

    features = [

        (
            "Major Retailer Alerts",
            "Free"
        ),

        (
            "Preorder Alerts",
            "Lite"
        ),

        (
            "Early Page Detection",
            "Premium"
        ),

        (
            "Price Drops & Deals",
            "Premium"
        ),

        (
            "International Alerts",
            "Premium"
        ),

        (
            "Release Radar",
            "Premium+"
        ),

        (
            "Inventory Flicker ⚡",
            "Premium+"
        ),

        (
            "Cart Watch 🛒",
            "Premium+"
        ),
    ]

    feature_lines = []

    for (
        feature_name,
        required_tier
    ) in features:

        unlocked = (
            tier_allows(
                tier,
                required_tier
            )
        )

        symbol = (
            "✅"
            if unlocked
            else "🔒"
        )

        feature_lines.append(
            f"{symbol} {feature_name}"
        )

    games_text = (
        "\n".join(
            f"✅ {game}"
            for game in games
        )
        if games
        else "No games selected"
    )

    embed = discord.Embed(
        title=(
            "⚙️ Lotus Tracker Settings"
        ),
        description=(
            f"**Subscription:** {tier}\n"
            "**Storage:** PostgreSQL"
        ),
    )

    embed.add_field(
        name="🎴 Games You Follow",
        value=games_text,
        inline=False,
    )

    embed.add_field(
        name="🔔 Feature Access",
        value=(
            "\n".join(
                feature_lines
            )
        ),
        inline=False,
    )

    await interaction.followup.send(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /DBME
# =========================================================

@bot.tree.command(
    name="dbme",
    description="View your saved Lotus database profile."
)
async def dbme(
    interaction: discord.Interaction,
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ Use this inside the server.",
            ephemeral=True,
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    if not bot.database_ready:

        await interaction.followup.send(
            "🔴 PostgreSQL is offline.",
            ephemeral=True,
        )

        return

    try:

        profile = (
            await load_user_preferences(
                member.id
            )
        )

        if profile is None:

            await save_member_to_database(
                member
            )

            profile = (
                await load_user_preferences(
                    member.id
                )
            )

        games = (
            profile[
                "games"
            ]
        )

        games_text = (
            "\n".join(
                f"• {game}"
                for game in games
            )
            if games
            else "No games saved"
        )

        embed = discord.Embed(
            title=(
                "💾 Your Lotus Database Profile"
            ),
            description=(
                "Your Discord account is "
                "stored in PostgreSQL."
            ),
        )

        embed.add_field(
            name="Discord User",
            value=(
                f"`{profile['discord_user_id']}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Subscription",
            value=(
                profile[
                    "subscription"
                ]
            ),
            inline=True,
        )

        embed.add_field(
            name="Saved Games",
            value=games_text,
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Database lookup failed.\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# /DBSTATUS
# =========================================================

@bot.tree.command(
    name="dbstatus",
    description="Check PostgreSQL."
)
async def dbstatus(
    interaction: discord.Interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        if SessionLocal is None:

            raise RuntimeError(
                "Database not configured."
            )

        async with SessionLocal() as session:

            result = await session.execute(
                text(
                    "SELECT 1"
                )
            )

            result.scalar()

        bot.database_ready = True

        await interaction.followup.send(
            "🟢 **PostgreSQL is online!**",
            ephemeral=True,
        )

    except Exception as error:

        bot.database_ready = False

        await interaction.followup.send(
            (
                "🔴 PostgreSQL failed.\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# /REDISSTATUS
# =========================================================

@bot.tree.command(
    name="redisstatus",
    description="Check Lotus Redis."
)
async def redisstatus(
    interaction: discord.Interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    online = (
        await check_redis()
    )

    bot.redis_ready = (
        online
    )

    if online:

        await interaction.followup.send(
            "🟢 **Redis is online!**",
            ephemeral=True,
        )

    else:

        await interaction.followup.send(
            "🔴 **Redis is offline.**",
            ephemeral=True,
        )


# =========================================================
# /EVENTSTATUS
# =========================================================

@bot.tree.command(
    name="eventstatus",
    description="View the Lotus event engine."
)
async def eventstatus(
    interaction: discord.Interaction,
):

    queue_size = (
        await get_queue_size()
    )

    worker_online = (
        bot.event_worker_task is not None
        and not bot.event_worker_task.done()
    )

    embed = discord.Embed(
        title=(
            "📡 Lotus Event Engine"
        ),
        description=(
            f"**PostgreSQL:** "
            f"{'✅' if bot.database_ready else '❌'}\n"
            f"**Redis:** "
            f"{'✅' if bot.redis_ready else '❌'}\n"
            f"**Event Worker:** "
            f"{'✅' if worker_online else '❌'}\n"
            f"**Queue Depth:** {queue_size}\n"
            "**Affiliate Pipeline:** Ready ✅"
        ),
    )

    embed.add_field(
        name="Lifecycle Events",
        value=(
            "DISCOVERED\n"
            "PAGE_LIVE\n"
            "COMING_SOON\n"
            "PREORDER_LIVE\n"
            "STOCK_AVAILABLE\n"
            "RESTOCK\n"
            "SOLD_OUT\n"
            "PRICE_DROP\n"
            "PRICE_INCREASE\n"
            "PRICE_ERROR\n"
            "INVENTORY_FLICKER\n"
            "RELEASE_DATE_CHANGED"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /SIMULATEPRODUCT
# =========================================================

@bot.tree.command(
    name="simulateproduct",
    description="Simulate a product lifecycle event."
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(

    game=[
        app_commands.Choice(
            name="One Piece",
            value="One Piece"
        ),
        app_commands.Choice(
            name="Pokemon",
            value="Pokemon"
        ),
        app_commands.Choice(
            name="Gundam",
            value="Gundam"
        ),
        app_commands.Choice(
            name="Dragon Ball Fusion World",
            value="Dragon Ball Fusion World"
        ),
        app_commands.Choice(
            name="Riftbound",
            value="Riftbound"
        ),
        app_commands.Choice(
            name="Palworld",
            value="Palworld"
        ),
        app_commands.Choice(
            name="Naruto",
            value="Naruto"
        ),
        app_commands.Choice(
            name="Cyberpunk TCG",
            value="Cyberpunk TCG"
        ),
        app_commands.Choice(
            name="Azuki TCG",
            value="Azuki TCG"
        ),
        app_commands.Choice(
            name="Hellbreak TCG",
            value="Hellbreak TCG"
        ),
    ],

    event=[
        app_commands.Choice(
            name="Discovered",
            value="DISCOVERED"
        ),
        app_commands.Choice(
            name="Page Live",
            value="PAGE_LIVE"
        ),
        app_commands.Choice(
            name="Coming Soon",
            value="COMING_SOON"
        ),
        app_commands.Choice(
            name="Preorder Live",
            value="PREORDER_LIVE"
        ),
        app_commands.Choice(
            name="Stock Available",
            value="STOCK_AVAILABLE"
        ),
        app_commands.Choice(
            name="Restock",
            value="RESTOCK"
        ),
        app_commands.Choice(
            name="Sold Out",
            value="SOLD_OUT"
        ),
        app_commands.Choice(
            name="Price Drop",
            value="PRICE_DROP"
        ),
        app_commands.Choice(
            name="Price Increase",
            value="PRICE_INCREASE"
        ),
        app_commands.Choice(
            name="Price Error",
            value="PRICE_ERROR"
        ),
        app_commands.Choice(
            name="Inventory Flicker",
            value="INVENTORY_FLICKER"
        ),
        app_commands.Choice(
            name="Release Date Changed",
            value="RELEASE_DATE_CHANGED"
        ),
    ],
)
async def simulateproduct(
    interaction: discord.Interaction,
    game: app_commands.Choice[str],
    event: app_commands.Choice[str],
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        event_type = (
            ProductEventType(
                event.value
            )
        )

        product_event = (
            ProductEvent(

                event_type=(
                    event_type
                ),

                game=(
                    game.value
                ),

                product_name=(
                    f"{game.value} Test Booster Box"
                ),

                store_name=(
                    "Lotus Simulation Store"
                ),

                product_url=(
                    "https://example.com/test-product"
                ),

                price=119.99,

                currency="USD",

                in_stock=(
                    event.value
                    in [
                        "STOCK_AVAILABLE",
                        "RESTOCK",
                        "INVENTORY_FLICKER",
                    ]
                ),

                region="US",

                language="English",

                product_type=(
                    "Booster Box"
                ),
            )
        )

        result = (
            await process_product_event(
                product_event
            )
        )

        queue_size = (
            await get_queue_size()
        )

        embed = discord.Embed(
            title=(
                "🧪 Product Event Simulated"
            ),
            description=(
                f"**{game.value} Test Booster Box**"
            ),
        )

        embed.add_field(
            name="Event",
            value=(
                event.value
            ),
            inline=True,
        )

        embed.add_field(
            name="PostgreSQL",
            value=(
                "✅ Saved"
                if result[
                    "database_saved"
                ]
                else "❌ Failed"
            ),
            inline=True,
        )

        embed.add_field(
            name="Redis",
            value=(
                "✅ Accepted"
                if result[
                    "redis_saved"
                ]
                else "❌ Failed"
            ),
            inline=True,
        )

        embed.add_field(
            name="Current Queue Depth",
            value=(
                str(
                    queue_size
                )
            ),
            inline=True,
        )

        embed.add_field(
            name="Worker",
            value=(
                "The event worker should "
                "automatically route this "
                "event into Discord."
            ),
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except Exception as error:

        print(
            "SIMULATE PRODUCT ERROR: "
            f"{type(error).__name__}: {error}"
        )

        await interaction.followup.send(
            (
                "❌ Simulation failed.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# TEST ALERT BUILDER
# =========================================================

def build_test_alert_embed(
    alert_type,
    game,
):

    if alert_type == "major_retailer":

        title = (
            "🚨 MAJOR RETAILER DROP"
        )

    elif alert_type == "preorder":

        title = (
            "🟣 PREORDER LIVE"
        )

    elif alert_type == "page_live":

        title = (
            "🔵 EARLY PAGE DETECTION"
        )

    elif alert_type == "deal":

        title = (
            "🔥 DEAL DETECTED"
        )

    elif alert_type == "international":

        title = (
            "🌎 INTERNATIONAL EXCLUSIVE"
        )

    elif alert_type == "inventory_flicker":

        title = (
            "⚡ INVENTORY FLICKER"
        )

    elif alert_type == "release_radar":

        title = (
            "📡 RELEASE RADAR"
        )

    else:

        title = (
            "Lotus Test Alert"
        )

    embed = discord.Embed(
        title=title,
        description=(
            f"**{game} Test Product**"
        ),
    )

    embed.add_field(
        name="Status",
        value=(
            "🧪 TEST ALERT"
        ),
        inline=False,
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
            value="One Piece"
        ),
        app_commands.Choice(
            name="Pokemon",
            value="Pokemon"
        ),
        app_commands.Choice(
            name="Gundam",
            value="Gundam"
        ),
    ],

    alert_type=[
        app_commands.Choice(
            name="Major Retailer",
            value="major_retailer"
        ),
        app_commands.Choice(
            name="Preorder",
            value="preorder"
        ),
        app_commands.Choice(
            name="Early Page Detection",
            value="page_live"
        ),
        app_commands.Choice(
            name="Deal",
            value="deal"
        ),
        app_commands.Choice(
            name="International",
            value="international"
        ),
        app_commands.Choice(
            name="Inventory Flicker",
            value="inventory_flicker"
        ),
        app_commands.Choice(
            name="Release Radar",
            value="release_radar"
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

        return

    config = (
        ALERT_ACCESS.get(
            alert_type.value
        )
    )

    if not config:

        await interaction.followup.send(
            "❌ Unknown alert type.",
            ephemeral=True,
        )

        return

    channel_variable = (
        config[
            "channel_variable"
        ]
    )

    channel_id = safe_int(
        CHANNEL_MAP.get(
            channel_variable
        )
    )

    if not channel_id:

        await interaction.followup.send(
            "❌ Alert channel not configured.",
            ephemeral=True,
        )

        return

    channel = (
        interaction.guild.get_channel(
            channel_id
        )
    )

    if channel is None:

        await interaction.followup.send(
            "❌ Alert channel not found.",
            ephemeral=True,
        )

        return

    game_role_id = safe_int(
        GAME_ROLES.get(
            game.value
        )
    )

    game_role = (
        interaction.guild.get_role(
            game_role_id
        )
        if game_role_id
        else None
    )

    embed = (
        build_test_alert_embed(
            alert_type.value,
            game.value,
        )
    )

    mention_text = (
        game_role.mention
        if game_role
        else f"**{game.value}**"
    )

    await channel.send(
        content=mention_text,
        embed=embed,
        allowed_mentions=(
            discord.AllowedMentions(
                roles=True,
                users=False,
                everyone=False,
            )
        ),
    )

    await interaction.followup.send(
        (
            "✅ Test alert sent to "
            f"{channel.mention}."
        ),
        ephemeral=True,
    )


# =========================================================
# /STATUS
# =========================================================

@bot.tree.command(
    name="status",
    description="Check Lotus system status."
)
async def status(
    interaction: discord.Interaction,
):

    latency = round(
        bot.latency * 1000
    )

    queue_size = (
        await get_queue_size()
    )

    worker_online = (
        bot.event_worker_task is not None
        and not bot.event_worker_task.done()
    )

    embed = discord.Embed(
        title=(
            "🟢 Lotus Tracker Bot Status"
        ),
        description=(
            "**Discord:** Connected ✅\n"
            f"**PostgreSQL:** "
            f"{'Online ✅' if bot.database_ready else 'Offline ⚠️'}\n"
            f"**Redis:** "
            f"{'Online ✅' if bot.redis_ready else 'Offline ⚠️'}\n"
            f"**Event Worker:** "
            f"{'Online ✅' if worker_online else 'Offline ⚠️'}\n"
            "**Persistent Users:** Online ✅\n"
            "**Product Event Engine:** Online ✅\n"
            "**Automatic Discord Routing:** Online ✅\n"
            "**Affiliate Link Pipeline:** Ready ✅\n"
            f"**Queue Depth:** {queue_size}\n"
            "**Real Store Monitoring:** Coming Next\n\n"
            f"**Latency:** {latency}ms\n"
            "**Version:** 0.5.1"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# ADMIN ERROR HANDLER
# =========================================================

async def send_admin_error(
    interaction,
    error,
    command_name,
):

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (
            f"❌ Only administrators "
            f"can use `/{command_name}`."
        )

    else:

        message = (
            f"❌ `/{command_name}` failed.\n\n"
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


@setupgames.error
async def setupgames_error(
    interaction,
    error,
):

    await send_admin_error(
        interaction,
        error,
        "setupgames",
    )


@simulateproduct.error
async def simulateproduct_error(
    interaction,
    error,
):

    await send_admin_error(
        interaction,
        error,
        "simulateproduct",
    )


@testalert.error
async def testalert_error(
    interaction,
    error,
):

    await send_admin_error(
        interaction,
        error,
        "testalert",
    )


# =========================================================
# START LOTUS
# =========================================================

if not DISCORD_TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN is missing."
    )


bot.run(
    DISCORD_TOKEN
)