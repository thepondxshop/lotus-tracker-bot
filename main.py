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

from app.shopify_monitor import (
    add_shopify_store,
    get_shopify_monitor_status,
    get_shopify_store,
    list_shopify_stores,
    remove_shopify_store,
    restore_shopify_store,
    retry_shopify_store,
    run_shopify_monitor,
    scan_all_shopify_stores,
    set_shopify_store_active,
)

from app.store_health import (
    get_health_overview,
)


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 0.6.3
#
# PostgreSQL
# Alembic
# Redis
# Product Events
# Discord Routing
# Affiliate Pipeline
# Shopify Monitoring
# Product Intelligence
# Inventory Flicker
# Store Health
# Self-Healing
# =========================================================


intents = (
    discord.Intents.default()
)

intents.members = True


# =========================================================
# CHOICES
# =========================================================

GAME_CHOICES = [

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
]


EVENT_CHOICES = [

    app_commands.Choice(
        name="Discovered",
        value="DISCOVERED",
    ),

    app_commands.Choice(
        name="Page Live",
        value="PAGE_LIVE",
    ),

    app_commands.Choice(
        name="Coming Soon",
        value="COMING_SOON",
    ),

    app_commands.Choice(
        name="Preorder Live",
        value="PREORDER_LIVE",
    ),

    app_commands.Choice(
        name="Stock Available",
        value="STOCK_AVAILABLE",
    ),

    app_commands.Choice(
        name="Restock",
        value="RESTOCK",
    ),

    app_commands.Choice(
        name="Sold Out",
        value="SOLD_OUT",
    ),

    app_commands.Choice(
        name="Price Drop",
        value="PRICE_DROP",
    ),

    app_commands.Choice(
        name="Price Increase",
        value="PRICE_INCREASE",
    ),

    app_commands.Choice(
        name="Price Error",
        value="PRICE_ERROR",
    ),

    app_commands.Choice(
        name="Inventory Flicker",
        value="INVENTORY_FLICKER",
    ),

    app_commands.Choice(
        name="Release Date Changed",
        value="RELEASE_DATE_CHANGED",
    ),
]


# =========================================================
# SAVE MEMBER
# =========================================================

async def save_member_to_database(
    member: discord.Member,
):

    await sync_member_to_database(
        member=member,
        subscription_tier=(
            get_subscription(
                member
            )
        ),
        selected_games=(
            get_followed_games(
                member
            )
        ),
    )


# =========================================================
# GAME ROLES
# =========================================================

async def update_game_roles(
    interaction,
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

    errors = []

    for (
        game_name,
        role_value,
    ) in GAME_ROLES.items():

        role_id = safe_int(
            role_value
        )

        if not role_id:

            continue

        role = (
            interaction.guild.get_role(
                role_id
            )
        )

        if role is None:

            continue

        try:

            if (
                game_name
                in selected_games
            ):

                if role not in member.roles:

                    await member.add_roles(
                        role,
                        reason=(
                            "Lotus game selection"
                        ),
                    )

            elif role in member.roles:

                await member.remove_roles(
                    role,
                    reason=(
                        "Lotus game selection"
                    ),
                )

        except Exception as error:

            errors.append(
                (
                    f"{game_name}: "
                    f"{type(error).__name__}"
                )
            )

    saved = False

    try:

        await save_member_to_database(
            member
        )

        saved = True

    except Exception as error:

        print(
            (
                "USER SAVE ERROR: "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

    games = (
        get_followed_games(
            member
        )
    )

    message = (
        "✅ **Game preferences updated.**\n\n"
    )

    if games:

        message += (
            "\n".join(
                f"• {game}"
                for game in sorted(
                    games
                )
            )
        )

    else:

        message += (
            "No games currently selected."
        )

    if saved:

        message += (
            "\n\n💾 Saved to Lotus."
        )

    if errors:

        message += (
            "\n\n⚠️ "
            + "\n".join(
                errors
            )
        )

    return (
        True,
        message,
    )


# =========================================================
# GAME SELECT UI
# =========================================================

class GameSelect(
    discord.ui.Select
):

    def __init__(
        self,
        member,
    ):

        current_ids = {
            role.id
            for role in member.roles
        }

        options = []

        for (
            game,
            emoji,
            description,
        ) in GAME_DATA:

            role_id = safe_int(
                GAME_ROLES.get(
                    game
                )
            )

            options.append(

                discord.SelectOption(
                    label=game,
                    value=game,
                    description=description,
                    emoji=emoji,
                    default=(
                        role_id
                        in current_ids
                        if role_id
                        else False
                    ),
                )
            )

        super().__init__(
            placeholder=(
                "Choose the TCGs you follow..."
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


class PersistentGameSelect(
    discord.ui.Select
):

    def __init__(
        self,
    ):

        options = []

        for (
            game,
            emoji,
            description,
        ) in GAME_DATA:

            options.append(

                discord.SelectOption(
                    label=game,
                    value=game,
                    description=description,
                    emoji=emoji,
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
        self,
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
        self,
    ):

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

        self.database_ready = False

        self.redis_ready = False

        self.event_worker_task = None

        self.shopify_monitor_task = None


    async def setup_hook(
        self,
    ):

        self.add_view(
            PersistentGameSelectView()
        )

        # =================================================
        # POSTGRESQL + ALEMBIC
        # =================================================

        try:

            await init_database()

            self.database_ready = True

            print(
                (
                    "PostgreSQL initialized. "
                    "Alembic migrations complete."
                )
            )

        except Exception as error:

            self.database_ready = False

            print(
                (
                    "DATABASE STARTUP ERROR: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

        # =================================================
        # REDIS
        # =================================================

        try:

            await init_redis()

            self.redis_ready = True

            print(
                "Redis initialized successfully."
            )

        except Exception as error:

            self.redis_ready = False

            print(
                (
                    "REDIS STARTUP ERROR: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

        # =================================================
        # WORKERS
        # =================================================

        self.event_worker_task = (
            asyncio.create_task(
                run_event_worker(
                    self
                )
            )
        )

        self.shopify_monitor_task = (
            asyncio.create_task(
                run_shopify_monitor()
            )
        )

        print(
            "Lotus Event Worker task created."
        )

        print(
            "Lotus Shopify Monitor task created."
        )

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
        "Version: 0.6.3"
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
# BASIC COMMANDS
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check Lotus.",
)
async def ping(
    interaction,
):

    await interaction.response.send_message(
        (
            "🏓 Lotus is online.\n"
            f"Latency: `{round(bot.latency * 1000)}ms`"
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="games",
    description="Choose your TCGs.",
)
async def games(
    interaction,
):

    member = interaction.user

    if not isinstance(
        member,
        discord.Member,
    ):

        return

    await interaction.response.send_message(
        embed=discord.Embed(
            title="🎴 Choose Your TCGs",
            description=(
                "Select every game "
                "you want Lotus alerts for."
            ),
        ),
        view=GameSelectView(
            member
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="setupgames",
    description="Post the persistent game selector.",
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

    await channel.send(
        embed=discord.Embed(
            title="🎴 Choose Your Games",
            description=(
                "Select every TCG "
                "you want Lotus alerts for."
            ),
        ),
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
# SUBSCRIPTION / SETTINGS
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
            else "None"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@bot.tree.command(
    name="settings",
    description="View Lotus settings.",
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

    features = [
        ("Major Retailer Alerts", "Free"),
        ("Preorders", "Lite"),
        ("Early Page Detection", "Premium"),
        ("Deals", "Premium"),
        ("International", "Premium"),
        ("Release Radar", "Premium+"),
        ("Inventory Flicker", "Premium+"),
        ("Cart Watch", "Premium+"),
    ]

    feature_text = "\n".join(

        (
            "✅"
            if tier_allows(
                tier,
                required
            )
            else "🔒"
        )
        + f" {name}"

        for (
            name,
            required,
        ) in features
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
        value=feature_text,
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@bot.tree.command(
    name="dbme",
    description="View your stored Lotus profile.",
)
async def dbme(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    profile = (
        await load_user_preferences(
            interaction.user.id
        )
    )

    if profile is None:

        if isinstance(
            interaction.user,
            discord.Member,
        ):

            await save_member_to_database(
                interaction.user
            )

            profile = (
                await load_user_preferences(
                    interaction.user.id
                )
            )

    if profile is None:

        await interaction.followup.send(
            "❌ Profile could not be loaded.",
            ephemeral=True,
        )

        return

    await interaction.followup.send(
        (
            "💾 **Lotus Database Profile**\n\n"
            f"Tier: **{profile['subscription']}**\n"
            "Games:\n"
            + (
                "\n".join(
                    f"• {game}"
                    for game
                    in profile[
                        "games"
                    ]
                )
                if profile[
                    "games"
                ]
                else "None"
            )
        ),
        ephemeral=True,
    )


# =========================================================
# INFRASTRUCTURE STATUS
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
                "Database unavailable."
            )

        async with SessionLocal() as session:

            await session.execute(
                text(
                    "SELECT 1"
                )
            )

        bot.database_ready = True

        await interaction.followup.send(
            "🟢 PostgreSQL is online.",
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
            "🟢 Redis is online."
            if online
            else "🔴 Redis is offline."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="eventstatus",
    description="View event-engine status.",
)
async def eventstatus(
    interaction,
):

    queue = (
        await get_queue_size()
    )

    worker = (
        bot.event_worker_task
        is not None
        and not bot.event_worker_task.done()
    )

    await interaction.response.send_message(
        (
            "📡 **Lotus Event Engine**\n\n"
            f"PostgreSQL: {'✅' if bot.database_ready else '❌'}\n"
            f"Redis: {'✅' if bot.redis_ready else '❌'}\n"
            f"Worker: {'✅' if worker else '❌'}\n"
            f"Queue: `{queue}`\n"
            "Affiliate Pipeline: ✅"
        ),
        ephemeral=True,
    )


# =========================================================
# STORE MANAGEMENT
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
            f"**{store.name}**\n"
            f"`{store.domain}`"
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="stores",
    description="List monitored Shopify stores.",
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
            "No monitored Shopify stores.",
            ephemeral=True,
        )

        return

    lines = []

    for store in store_list:

        lines.append(
            (
                f"**ID {store.id} — {store.name}**\n"
                f"`{store.domain}`\n"
                f"{'🟢' if store.active else '⚫'} "
                f"{store.health_status}"
                + (
                    f" • {store.disabled_reason}"
                    if store.disabled_reason
                    else ""
                )
            )
        )

    await interaction.followup.send(
        "\n\n".join(
            lines
        )[
            :1900
        ],
        ephemeral=True,
    )


@bot.tree.command(
    name="storeinfo",
    description="View detailed store information.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def storeinfo(
    interaction,
    store_id: int,
):

    store = (
        await get_shopify_store(
            store_id
        )
    )

    if store is None:

        await interaction.response.send_message(
            "❌ Store ID not found.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            f"🏪 {store.name}"
        )
    )

    embed.add_field(
        name="ID",
        value=str(
            store.id
        ),
    )

    embed.add_field(
        name="Health",
        value=store.health_status,
    )

    embed.add_field(
        name="Active",
        value=(
            "Yes ✅"
            if store.active
            else "No ❌"
        ),
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
        name="Consecutive Failures",
        value=str(
            store.consecutive_failures
        ),
    )

    embed.add_field(
        name="Disabled Reason",
        value=(
            store.disabled_reason
            or "None"
        ),
    )

    embed.add_field(
        name="Last Success",
        value=(
            str(
                store.last_success_at
            )
            if store.last_success_at
            else "None"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Failure",
        value=(
            str(
                store.last_failure_at
            )
            if store.last_failure_at
            else "None"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Error",
        value=(
            (
                store.last_error[
                    :1000
                ]
            )
            if store.last_error
            else "None ✅"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@bot.tree.command(
    name="disablestore",
    description="Manually disable a store.",
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
            "❌ Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        (
            f"⚫ **{store.name}** manually disabled.\n\n"
            "It will NOT automatically reactivate."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="enablestore",
    description="Manually enable a store.",
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
            "❌ Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        f"🟢 **{store.name}** enabled.",
        ephemeral=True,
    )


@bot.tree.command(
    name="removestore",
    description="Remove a store from monitoring.",
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
            "❌ Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        (
            f"🗑️ **{store.name}** removed from monitoring.\n\n"
            "It will no longer appear in `/stores`.\n"
            "Historical data remains preserved."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="restorestore",
    description="Restore a previously removed store.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def restorestore(
    interaction,
    store_id: int,
):

    store = (
        await restore_shopify_store(
            store_id
        )
    )

    if store is None:

        await interaction.response.send_message(
            "❌ Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        (
            f"♻️ **{store.name}** restored "
            "to active monitoring."
        ),
        ephemeral=True,
    )


# =========================================================
# STORE HEALTH
# =========================================================

@bot.tree.command(
    name="storehealth",
    description="View a store's monitoring health.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def storehealth(
    interaction,
    store_id: int,
):

    store = (
        await get_shopify_store(
            store_id
        )
    )

    if store is None:

        await interaction.response.send_message(
            "❌ Store not found.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            f"🩺 {store.name} Health"
        ),
        description=(
            f"**Status:** {store.health_status}\n"
            f"**Active:** "
            f"{'✅' if store.active else '❌'}\n"
            f"**Failures:** "
            f"{store.consecutive_failures}\n"
            f"**Disabled Reason:** "
            f"{store.disabled_reason or 'None'}"
        ),
    )

    embed.add_field(
        name="Last Success",
        value=(
            str(
                store.last_success_at
            )
            if store.last_success_at
            else "None"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Failure",
        value=(
            str(
                store.last_failure_at
            )
            if store.last_failure_at
            else "None"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Error",
        value=(
            store.last_error[
                :1000
            ]
            if store.last_error
            else "None ✅"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@bot.tree.command(
    name="healthstatus",
    description="View overall Lotus store health.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def healthstatus(
    interaction,
):

    overview = (
        await get_health_overview()
    )

    await interaction.response.send_message(
        (
            "🩺 **Lotus Store Health**\n\n"
            f"🟢 Healthy: `{overview['healthy']}`\n"
            f"🟡 Degraded: `{overview['degraded']}`\n"
            f"🔴 Unhealthy: `{overview['unhealthy']}`\n"
            f"⚫ Disabled: `{overview['disabled']}`\n"
            f"🗑️ Removed: `{overview['removed']}`\n\n"
            "Health-disabled stores are automatically "
            "checked for recovery every 5 minutes."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="retrystore",
    description="Immediately retry a store health check.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def retrystore(
    interaction,
    store_id: int,
):

    await interaction.response.defer(
        ephemeral=True
    )

    result = (
        await retry_shopify_store(
            store_id
        )
    )

    if result[
        "reason"
    ] == "NOT_FOUND":

        await interaction.followup.send(
            "❌ Store not found.",
            ephemeral=True,
        )

        return

    if result[
        "reason"
    ] == "MANUAL":

        await interaction.followup.send(
            (
                "⚠️ This store was manually disabled.\n"
                "Use `/enablestore` instead."
            ),
            ephemeral=True,
        )

        return

    if result[
        "reason"
    ] == "REMOVED":

        await interaction.followup.send(
            (
                "⚠️ This store was removed.\n"
                "Use `/restorestore` instead."
            ),
            ephemeral=True,
        )

        return

    if result[
        "success"
    ]:

        await interaction.followup.send(
            (
                "🟢 Store responded successfully.\n\n"
                "Health restored and monitoring enabled."
            ),
            ephemeral=True,
        )

    else:

        await interaction.followup.send(
            (
                "🔴 Store health check failed.\n\n"
                f"`{result['reason']}`"
            ),
            ephemeral=True,
        )


# =========================================================
# SHOPIFY MONITOR COMMANDS
# =========================================================

@bot.tree.command(
    name="scanshopify",
    description="Run an immediate Shopify scan.",
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
                "⚠️ No active stores "
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
        "\n\n".join(
            lines
        )[
            :1900
        ],
        ephemeral=True,
    )


@bot.tree.command(
    name="shopifystatus",
    description="View Shopify monitor status.",
)
async def shopifystatus(
    interaction,
):

    data = (
        get_shopify_monitor_status()
    )

    worker = (
        bot.shopify_monitor_task
        is not None
        and not bot.shopify_monitor_task.done()
    )

    embed = discord.Embed(
        title="🛍️ Lotus Shopify Monitor",
        description=(
            f"**Worker:** {'✅' if worker else '❌'}\n"
            f"**Running:** {'✅' if data['running'] else '❌'}\n"
            f"**Stores Scanned:** {data['stores_scanned']}\n"
            f"**Products Seen:** {data['products_seen']}\n"
            f"**Events:** {data['events_created']}\n"
            f"**Flickers:** {data['flickers_detected']}\n"
            f"**Recovered Stores:** {data['stores_recovered']}"
        ),
    )

    embed.add_field(
        name="Last Scan",
        value=(
            data[
                "last_scan"
            ]
            or "Not yet"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Health Probe",
        value=(
            data[
                "last_health_probe"
            ]
            or "Not yet"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Error",
        value=(
            data[
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
# SIMULATOR
# =========================================================

@bot.tree.command(
    name="simulateproduct",
    description="Simulate a product lifecycle event.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    game=GAME_CHOICES,
    event=EVENT_CHOICES,
)
async def simulateproduct(
    interaction,
    game: app_commands.Choice[str],
    event: app_commands.Choice[str],
):

    await interaction.response.defer(
        ephemeral=True
    )

    product_event = (
        ProductEvent(
            event_type=(
                ProductEventType(
                    event.value
                )
            ),
            game=game.value,
            product_name=(
                f"{game.value} Test Product"
            ),
            store_name=(
                "Lotus Simulation Store"
            ),
            product_url=(
                "https://example.com/test"
            ),
            price=119.99,
            currency="USD",
            in_stock=(
                event.value
                in (
                    "STOCK_AVAILABLE",
                    "RESTOCK",
                    "INVENTORY_FLICKER",
                )
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

    await interaction.followup.send(
        (
            "🧪 Event submitted.\n\n"
            f"PostgreSQL: "
            f"{'✅' if result['database_saved'] else '❌'}\n"
            f"Redis: "
            f"{'✅' if result['redis_saved'] else '❌'}"
        ),
        ephemeral=True,
    )


# =========================================================
# TEST ALERT
# =========================================================

@bot.tree.command(
    name="testalert",
    description="Send a test alert through configured routing.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    game=GAME_CHOICES,
)
async def testalert(
    interaction,
    game: app_commands.Choice[str],
    alert_type: str,
):

    await interaction.response.defer(
        ephemeral=True
    )

    if interaction.guild is None:

        return

    config = (
        ALERT_ACCESS.get(
            alert_type
        )
    )

    if not config:

        await interaction.followup.send(
            (
                "❌ Unknown alert type.\n\n"
                "Examples: `major_retailer`, "
                "`preorder`, `page_live`, `deal`, "
                "`international`, `inventory_flicker`, "
                "`release_radar`"
            ),
            ephemeral=True,
        )

        return

    channel_id = safe_int(
        CHANNEL_MAP.get(
            config[
                "channel_variable"
            ]
        )
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
            "❌ Alert channel not found.",
            ephemeral=True,
        )

        return

    role_id = safe_int(
        GAME_ROLES.get(
            game.value
        )
    )

    role = (
        interaction.guild.get_role(
            role_id
        )
        if role_id
        else None
    )

    await channel.send(
        content=(
            role.mention
            if role
            else game.value
        ),
        embed=discord.Embed(
            title="🧪 LOTUS TEST ALERT",
            description=(
                f"**{game.value} Test Product**\n\n"
                f"Alert type: `{alert_type}`"
            ),
        ),
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
            f"✅ Test alert sent "
            f"to {channel.mention}."
        ),
        ephemeral=True,
    )


# =========================================================
# SYSTEM STATUS
# =========================================================

@bot.tree.command(
    name="status",
    description="View Lotus system status.",
)
async def status(
    interaction,
):

    queue = (
        await get_queue_size()
    )

    event_worker = (
        bot.event_worker_task
        is not None
        and not bot.event_worker_task.done()
    )

    shopify_worker = (
        bot.shopify_monitor_task
        is not None
        and not bot.shopify_monitor_task.done()
    )

    health = (
        await get_health_overview()
    )

    embed = discord.Embed(
        title="🟢 Lotus Tracker Bot Status",
        description=(
            f"**PostgreSQL / Alembic:** "
            f"{'✅' if bot.database_ready else '❌'}\n"
            f"**Redis:** "
            f"{'✅' if bot.redis_ready else '❌'}\n"
            f"**Event Worker:** "
            f"{'✅' if event_worker else '❌'}\n"
            f"**Shopify Worker:** "
            f"{'✅' if shopify_worker else '❌'}\n"
            "**Affiliate Pipeline:** ✅\n"
            "**Store Self-Healing:** ✅\n"
            f"**Healthy Stores:** {health['healthy']}\n"
            f"**Degraded Stores:** {health['degraded']}\n"
            f"**Unhealthy Stores:** {health['unhealthy']}\n"
            f"**Queue:** {queue}\n\n"
            "**Version:** 0.6.3"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# GLOBAL COMMAND ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error,
):

    if isinstance(
        error,
        app_commands.MissingPermissions,
    ):

        message = (
            "❌ You do not have permission "
            "to use this command."
        )

    else:

        print(
            (
                "APP COMMAND ERROR: "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        message = (
            "❌ Command failed.\n\n"
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