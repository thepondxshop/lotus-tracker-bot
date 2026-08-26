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


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 0.5
#
# PostgreSQL + Redis + Product Event Engine
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
    selected_games
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

    message = (
        "✅ **Your game alert preferences were updated!**\n\n"
    )

    actual_games = (
        get_followed_games(
            member
        )
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
# GAME SELECTOR
# =========================================================

class GameSelect(
    discord.ui.Select
):

    def __init__(
        self,
        member: discord.Member
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
        interaction: discord.Interaction
    ):

        _, message = (
            await update_game_roles(
                interaction,
                self.values
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
        member: discord.Member
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
# PERSISTENT SELECTOR
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
        interaction: discord.Interaction
    ):

        _, message = (
            await update_game_roles(
                interaction,
                self.values
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


    async def setup_hook(
        self
    ):

        self.add_view(
            PersistentGameSelectView()
        )

        # ---------------------------------------------
        # POSTGRESQL
        # ---------------------------------------------

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

        # ---------------------------------------------
        # REDIS
        # ---------------------------------------------

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

        # ---------------------------------------------
        # COMMAND SYNC
        # ---------------------------------------------

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
        "Architecture: v0.5"
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
    interaction: discord.Interaction
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ Use this command in the server.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            "🎴 Choose Your TCGs"
        ),
        description=(
            "Choose every game you want "
            "Lotus to track for you.\n\n"
            "Selections are saved persistently."
        ),
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
    interaction: discord.Interaction
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
    description="View your subscription."
)
async def subscription(
    interaction: discord.Interaction
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member
    ):

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
                f"{error}"
            )

    games_text = (
        "\n".join(
            f"• {game}"
            for game in games
        )
        if games
        else "No games selected"
    )

    embed = discord.Embed(
        title=(
            "💳 PonDeX Subscription"
        ),
        description=(
            f"**Current Tier:** {tier}"
        ),
    )

    embed.add_field(
        name="Games",
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
    interaction: discord.Interaction
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member
    ):

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
                f"{error}"
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
            f"**Storage:** PostgreSQL"
        ),
    )

    embed.add_field(
        name="Games You Follow",
        value=games_text,
        inline=False,
    )

    await interaction.followup.send(
        embed=embed,
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
    interaction: discord.Interaction
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
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    online = (
        await check_redis()
    )

    bot.redis_ready = online

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
    description="View Lotus event engine status."
)
async def eventstatus(
    interaction: discord.Interaction
):

    queue_size = (
        await get_queue_size()
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
            f"**Queued Events:** {queue_size}"
        ),
    )

    embed.add_field(
        name="Supported Lifecycle Events",
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
                event_type=event_type,
                game=game.value,
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
                product_type="Booster Box",
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
                "✅ Queued"
                if result[
                    "redis_saved"
                ]
                else "❌ Failed"
            ),
            inline=True,
        )

        embed.add_field(
            name="Redis Queue",
            value=(
                str(
                    queue_size
                )
            ),
            inline=True,
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
# /STATUS
# =========================================================

@bot.tree.command(
    name="status",
    description="Check Lotus system status."
)
async def status(
    interaction: discord.Interaction
):

    latency = round(
        bot.latency * 1000
    )

    queue_size = (
        await get_queue_size()
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
            "**Persistent Users:** Online ✅\n"
            "**Product Event Engine:** Online ✅\n"
            f"**Queued Events:** {queue_size}\n"
            "**Real Store Monitoring:** Coming Next\n\n"
            f"**Latency:** {latency}ms\n"
            "**Version:** 0.5"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# ERROR HANDLERS
# =========================================================

@simulateproduct.error
async def simulateproduct_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (
            "❌ Only administrators "
            "can use `/simulateproduct`."
        )

    else:

        message = (
            "❌ `/simulateproduct` failed.\n\n"
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
# START
# =========================================================

if not DISCORD_TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN is missing."
    )


bot.run(
    DISCORD_TOKEN
)