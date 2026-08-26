import asyncio

import discord

from discord.ext import commands
from discord import app_commands

from sqlalchemy import text


# =========================================================
# CONFIG
# =========================================================

from app.config import (
    DISCORD_TOKEN,
    GAME_ROLES,
    GAME_DATA,
    ALERT_ACCESS,
    CHANNEL_MAP,
    CHANNEL_ROLES,
)


# =========================================================
# HELPERS
# =========================================================

from app.helpers import (
    safe_int,
    get_subscription,
    get_followed_games,
    tier_allows,
)


# =========================================================
# DATABASE
# =========================================================

from app.database import (
    init_database,
    SessionLocal,
    load_user_preferences,
    sync_member_to_database,
)


# =========================================================
# REDIS
# =========================================================

from app.redis_client import (
    init_redis,
    check_redis,
)


# =========================================================
# EVENTS
# =========================================================

from app.events import (
    ProductEvent,
    ProductEventType,
)

from app.event_service import (
    process_product_event,
    get_queue_size,
)


# =========================================================
# EVENT WORKER
# =========================================================

from app.worker import (
    run_event_worker,
)


# =========================================================
# SHOPIFY
# =========================================================

from app.shopify_monitor import (
    add_shopify_store,
    get_shopify_monitor_status,
    get_shopify_store,
    list_shopify_stores,
    remove_shopify_store,
    run_shopify_monitor,
    scan_all_shopify_stores,
    set_shopify_store_active,
)


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 0.6.2
# =========================================================


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()

intents.members = True


# =========================================================
# SAVE MEMBER
# =========================================================

async def save_member_to_database(
    member: discord.Member,
):

    tier = get_subscription(
        member
    )

    games = get_followed_games(
        member
    )

    await sync_member_to_database(
        member=member,
        subscription_tier=tier,
        selected_games=games,
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
        discord.Member,
    ):

        return (
            False,
            "❌ Use this inside the server.",
        )

    if interaction.guild is None:

        return (
            False,
            "❌ Use this inside the server.",
        )

    selected_games = set(
        selected_games
    )

    added_roles = []
    removed_roles = []
    errors = []

    for (
        game_name,
        role_id,
    ) in GAME_ROLES.items():

        role_id = safe_int(
            role_id
        )

        if not role_id:

            errors.append(
                f"{game_name}: Role ID missing"
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

                except Exception as error:

                    errors.append(
                        (
                            f"{game_name}: "
                            f"{type(error).__name__}"
                        )
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

                except Exception as error:

                    errors.append(
                        (
                            f"{game_name}: "
                            f"{type(error).__name__}"
                        )
                    )

    database_saved = False

    try:

        await save_member_to_database(
            member
        )

        database_saved = True

    except Exception as error:

        print(
            (
                "USER DATABASE SAVE ERROR: "
                f"{type(error).__name__}: {error}"
            )
        )

        errors.append(
            "Database save failed"
        )

    current_games = (
        get_followed_games(
            member
        )
    )

    message = (
        "✅ **Your game alert preferences were updated!**\n\n"
    )

    if current_games:

        message += (
            "**You are following:**\n"
        )

        for game in sorted(
            current_games
        ):

            message += (
                f"• {game}\n"
            )

    else:

        message += (
            "You are currently not following any games.\n"
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
        message,
    )


# =========================================================
# GAME SELECTOR
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
            description,
        ) in GAME_DATA:

            role_id = safe_int(
                GAME_ROLES.get(
                    game_name
                )
            )

            options.append(

                discord.SelectOption(

                    label=game_name,

                    description=description,

                    emoji=emoji,

                    value=game_name,

                    default=(
                        role_id
                        in current_role_ids
                        if role_id
                        else False
                    ),
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
        member,
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
# PERSISTENT GAME SELECTOR
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
            description,
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
        interaction,
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
# BOT
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

        self.shopify_monitor_task = None


    async def setup_hook(
        self
    ):

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
                (
                    "DATABASE STARTUP ERROR: "
                    f"{self.database_error}"
                )
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
                (
                    "REDIS STARTUP ERROR: "
                    f"{self.redis_error}"
                )
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
        # SHOPIFY MONITOR
        # -------------------------------------------------

        self.shopify_monitor_task = (
            asyncio.create_task(

                run_shopify_monitor()
            )
        )

        print(
            "Lotus Shopify Monitor task created."
        )

        # -------------------------------------------------
        # SLASH COMMANDS
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
        "Architecture: v0.6.2"
    )

    print(
        "PostgreSQL:",
        (
            "ONLINE"
            if bot.database_ready
            else "OFFLINE"
        ),
    )

    print(
        "Redis:",
        (
            "ONLINE"
            if bot.redis_ready
            else "OFFLINE"
        ),
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
    description="Check if Lotus is online.",
)
async def ping(
    interaction,
):

    latency = round(
        bot.latency
        * 1000
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
    description="Choose which TCGs you want alerts for.",
)
async def games(
    interaction,
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member,
    ):

        await interaction.response.send_message(
            "❌ Use this inside the server.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title="🎴 Choose Your TCGs",
        description=(
            "Choose every game you want Lotus "
            "Tracker Bot to monitor."
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        view=GameSelectView(
            member
        ),
        ephemeral=True,
    )


# =========================================================
# /SETUPGAMES
# =========================================================

@bot.tree.command(
    name="setupgames",
    description="Post the permanent game selector.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setupgames(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    if interaction.guild is None:

        return

    channel_id = safe_int(
        CHANNEL_ROLES
    )

    channel = (
        interaction.guild.get_channel(
            channel_id
        )
        if channel_id
        else None
    )

    if channel is None:

        await interaction.followup.send(
            "❌ Roles channel not found.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title="🎴 Choose Your Games",
        description=(
            "Select every TCG you want "
            "Lotus alerts for."
        ),
    )

    await channel.send(
        embed=embed,
        view=PersistentGameSelectView(),
    )

    await interaction.followup.send(
        (
            f"✅ Selector posted "
            f"in {channel.mention}."
        ),
        ephemeral=True,
    )


# =========================================================
# /SUBSCRIPTION
# =========================================================

@bot.tree.command(
    name="subscription",
    description="View your subscription.",
)
async def subscription(
    interaction,
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member,
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

    embed = discord.Embed(
        title="💳 PonDeX Subscription",
        description=(
            f"**Current Tier:** {tier}"
        ),
    )

    embed.add_field(
        name="Games",
        value=(
            "\n".join(
                f"• {game}"
                for game in games
            )
            if games
            else "No games selected"
        ),
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
    description="View your saved Lotus settings.",
)
async def settings(
    interaction,
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member,
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

    feature_checks = [

        (
            "Major Retailer Alerts",
            "Free",
        ),

        (
            "Preorder Alerts",
            "Lite",
        ),

        (
            "Early Page Detection",
            "Premium",
        ),

        (
            "Deals",
            "Premium",
        ),

        (
            "Inventory Flicker",
            "Premium+",
        ),
    ]

    lines = []

    for (
        name,
        required,
    ) in feature_checks:

        lines.append(

            (
                "✅"
                if tier_allows(
                    tier,
                    required
                )

                else "🔒"
            )

            + f" {name}"
        )

    embed = discord.Embed(
        title="⚙️ Lotus Settings",
        description=(
            f"**Subscription:** {tier}"
        ),
    )

    embed.add_field(
        name="Games",
        value=(
            "\n".join(
                f"✅ {game}"
                for game in games
            )
            if games
            else "None"
        ),
        inline=False,
    )

    embed.add_field(
        name="Features",
        value=(
            "\n".join(
                lines
            )
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /DBSTATUS
# =========================================================

@bot.tree.command(
    name="dbstatus",
    description="Check PostgreSQL.",
)
async def dbstatus(
    interaction,
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
    description="Check Redis.",
)
async def redisstatus(
    interaction,
):

    online = (
        await check_redis()
    )

    bot.redis_ready = online

    await interaction.response.send_message(

        (
            "🟢 **Redis is online!**"
            if online
            else "🔴 **Redis is offline.**"
        ),

        ephemeral=True,
    )


# =========================================================
# /EVENTSTATUS
# =========================================================

@bot.tree.command(
    name="eventstatus",
    description="View Lotus event-engine status.",
)
async def eventstatus(
    interaction,
):

    queue_size = (
        await get_queue_size()
    )

    worker_online = (

        bot.event_worker_task
        is not None

        and not bot.event_worker_task.done()
    )

    embed = discord.Embed(
        title="📡 Lotus Event Engine",
        description=(
            f"**PostgreSQL:** "
            f"{'✅' if bot.database_ready else '❌'}\n"
            f"**Redis:** "
            f"{'✅' if bot.redis_ready else '❌'}\n"
            f"**Event Worker:** "
            f"{'✅' if worker_online else '❌'}\n"
            f"**Queue Depth:** {queue_size}\n"
            "**Affiliate Pipeline:** ✅"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /ADDSHOPIFYSTORE
# =========================================================

@bot.tree.command(
    name="addshopifystore",
    description="Add or update a Shopify store.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def addshopifystore(
    interaction,
    name: str,
    domain: str,
    region: str = "US",
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        store, created = (
            await add_shopify_store(

                name=name,

                domain=domain,

                region=region,
            )
        )

        await interaction.followup.send(
            (
                f"{'✅ Added' if created else '✅ Updated'} "
                f"**{store.name}**\n\n"
                f"`{store.domain}`\n"
                f"Region: `{store.region}`"
            ),
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Store could not be added.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# /STORES
# =========================================================

@bot.tree.command(
    name="stores",
    description="View Shopify stores configured in Lotus.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def stores(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    store_list = (
        await list_shopify_stores()
    )

    if not store_list:

        await interaction.followup.send(
            "No Shopify stores configured.",
            ephemeral=True,
        )

        return

    lines = []

    for store in store_list:

        status = (
            "🟢 Active"
            if store.active
            else "⚫ Disabled"
        )

        lines.append(
            (
                f"**ID {store.id} — {store.name}**\n"
                f"`{store.domain}`\n"
                f"{status}"
            )
        )

    message = (
        "\n\n".join(
            lines
        )
    )

    await interaction.followup.send(
        message[
            :1900
        ],
        ephemeral=True,
    )


# =========================================================
# /STOREINFO
# =========================================================

@bot.tree.command(
    name="storeinfo",
    description="View information about a monitored store.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def storeinfo(
    interaction,
    store_id: int,
):

    await interaction.response.defer(
        ephemeral=True
    )

    store = (
        await get_shopify_store(
            store_id
        )
    )

    if store is None:

        await interaction.followup.send(
            "❌ Store ID not found.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            f"🏪 {store.name}"
        ),
    )

    embed.add_field(
        name="Store ID",
        value=str(
            store.id
        ),
        inline=True,
    )

    embed.add_field(
        name="Status",
        value=(
            "🟢 Active"
            if store.active
            else "⚫ Disabled"
        ),
        inline=True,
    )

    embed.add_field(
        name="Platform",
        value=(
            store.platform
            or "Unknown"
        ),
        inline=True,
    )

    embed.add_field(
        name="Domain",
        value=(
            store.domain
            or "Unknown"
        ),
        inline=False,
    )

    embed.add_field(
        name="Region",
        value=(
            store.region
            or "Unknown"
        ),
        inline=True,
    )

    await interaction.followup.send(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /DISABLESTORE
# =========================================================

@bot.tree.command(
    name="disablestore",
    description="Disable a Shopify store.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def disablestore(
    interaction,
    store_id: int,
):

    store = (
        await set_shopify_store_active(
            store_id,
            False,
        )
    )

    if store is None:

        await interaction.response.send_message(
            "❌ Store ID not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        (
            f"⚫ **{store.name}** disabled.\n"
            "Lotus will stop scanning it."
        ),
        ephemeral=True,
    )


# =========================================================
# /ENABLESTORE
# =========================================================

@bot.tree.command(
    name="enablestore",
    description="Re-enable a Shopify store.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def enablestore(
    interaction,
    store_id: int,
):

    store = (
        await set_shopify_store_active(
            store_id,
            True,
        )
    )

    if store is None:

        await interaction.response.send_message(
            "❌ Store ID not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        (
            f"🟢 **{store.name}** enabled."
        ),
        ephemeral=True,
    )


# =========================================================
# /REMOVESTORE
# =========================================================

@bot.tree.command(
    name="removestore",
    description="Remove a store from active monitoring.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def removestore(
    interaction,
    store_id: int,
):

    store = (
        await remove_shopify_store(
            store_id
        )
    )

    if store is None:

        await interaction.response.send_message(
            "❌ Store ID not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        (
            f"🗑️ **{store.name}** removed "
            "from active monitoring.\n\n"
            "Historical product and alert data "
            "was preserved."
        ),
        ephemeral=True,
    )


# =========================================================
# /SCANSHOPIFY
# =========================================================

@bot.tree.command(
    name="scanshopify",
    description="Run a Shopify scan now.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def scanshopify(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    results = (
        await scan_all_shopify_stores()
    )

    if not results:

        await interaction.followup.send(
            (
                "⚠️ No active Shopify stores "
                "were successfully scanned."
            ),
            ephemeral=True,
        )

        return

    lines = []

    for result in results:

        lines.append(
            (
                f"**{result['store']}**\n"
                f"Products: {result['seen']}\n"
                f"New: {result['new']}\n"
                f"Updated: {result['updated']}\n"
                f"Events: {result['events']}\n"
                f"Flickers: {result['flickers']}"
                + (
                    "\n🌱 Initial baseline"
                    if result[
                        "initial_seed"
                    ]
                    else ""
                )
            )
        )

    await interaction.followup.send(
        (
            "\n\n".join(
                lines
            )
        )[
            :1900
        ],
        ephemeral=True,
    )


# =========================================================
# /SHOPIFYSTATUS
# =========================================================

@bot.tree.command(
    name="shopifystatus",
    description="View Shopify monitor status.",
)
async def shopifystatus(
    interaction,
):

    status_data = (
        get_shopify_monitor_status()
    )

    worker_online = (

        bot.shopify_monitor_task
        is not None

        and not bot.shopify_monitor_task.done()
    )

    embed = discord.Embed(
        title="🛍️ Lotus Shopify Monitor",
        description=(
            f"**Worker:** "
            f"{'✅ Online' if worker_online else '❌ Offline'}\n"
            f"**Running:** "
            f"{'✅' if status_data['running'] else '❌'}\n"
            f"**Stores Last Scanned:** "
            f"{status_data['stores_scanned']}\n"
            f"**TCG Products Seen:** "
            f"{status_data['products_seen']}\n"
            f"**Events Created:** "
            f"{status_data['events_created']}\n"
            f"**Flickers Detected:** "
            f"{status_data['flickers_detected']}"
        ),
    )

    embed.add_field(
        name="Last Scan",
        value=(
            status_data[
                "last_scan"
            ]
            or "Not yet"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Error",
        value=(
            status_data[
                "last_error"
            ]
            or "None ✅"
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
    description="Simulate a Lotus product event.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def simulateproduct(
    interaction,
    game: str,
    event: str,
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        event_type = (
            ProductEventType(
                event.upper()
            )
        )

        product_event = (
            ProductEvent(

                event_type=event_type,

                game=game,

                product_name=(
                    f"{game} Test Product"
                ),

                store_name=(
                    "Lotus Simulation Store"
                ),

                product_url=(
                    "https://example.com/test"
                ),

                price=119.99,

                in_stock=True,

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

        await interaction.followup.send(
            (
                "🧪 Event simulated.\n\n"
                f"PostgreSQL: "
                f"{'✅' if result['database_saved'] else '❌'}\n"
                f"Redis: "
                f"{'✅' if result['redis_saved'] else '❌'}"
            ),
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Simulation failed.\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# /STATUS
# =========================================================

@bot.tree.command(
    name="status",
    description="Check Lotus system status.",
)
async def status(
    interaction,
):

    queue_size = (
        await get_queue_size()
    )

    event_worker_online = (

        bot.event_worker_task
        is not None

        and not bot.event_worker_task.done()
    )

    shopify_worker_online = (

        bot.shopify_monitor_task
        is not None

        and not bot.shopify_monitor_task.done()
    )

    embed = discord.Embed(
        title="🟢 Lotus Tracker Bot Status",
        description=(
            f"**PostgreSQL:** "
            f"{'✅' if bot.database_ready else '❌'}\n"
            f"**Redis:** "
            f"{'✅' if bot.redis_ready else '❌'}\n"
            f"**Event Worker:** "
            f"{'✅' if event_worker_online else '❌'}\n"
            f"**Shopify Monitor:** "
            f"{'✅' if shopify_worker_online else '❌'}\n"
            "**Affiliate Pipeline:** ✅\n"
            f"**Redis Queue:** {queue_size}\n\n"
            "**Version:** 0.6.2"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
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