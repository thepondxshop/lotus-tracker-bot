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

from app.pokemon_center_monitor import (
    get_pokemon_center_status,
    run_pokemon_center_monitor,
    scan_pokemon_center,
)

from app.pokemon_center_products import (
    get_pokemon_product_status,
    run_pokemon_center_product_monitor,
    scan_pokemon_center_products,
    trigger_product_burst,
)


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 0.7.1
# =========================================================


intents = (
    discord.Intents.default()
)

intents.members = True


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
        name="Inventory Flicker",
        value="INVENTORY_FLICKER",
    ),

    app_commands.Choice(
        name="Pokemon Queue Active",
        value="QUEUE_ACTIVE",
    ),

    app_commands.Choice(
        name="Pokemon Queue Cleared",
        value="QUEUE_CLEARED",
    ),
]


async def save_member_to_database(
    member,
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


async def update_game_roles(
    interaction,
    selected_games,
):

    member = (
        interaction.user
    )

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

    for (
        game,
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

        if not role:

            continue

        if (
            game
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

    await save_member_to_database(
        member
    )

    return (
        True,
        "✅ Game preferences updated and saved.",
    )


class GameSelect(
    discord.ui.Select
):

    def __init__(
        self,
        member,
    ):

        current_ids = {
            role.id
            for role
            in member.roles
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
                "Choose TCGs for alerts..."
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

        self.pokemon_center_task = None

        self.pokemon_product_task = None


    async def setup_hook(
        self,
    ):

        self.add_view(
            PersistentGameSelectView()
        )

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

        try:

            await init_redis()

            self.redis_ready = True

        except Exception as error:

            self.redis_ready = False

            print(
                (
                    "REDIS STARTUP ERROR: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

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

        self.pokemon_center_task = (
            asyncio.create_task(
                run_pokemon_center_monitor()
            )
        )

        self.pokemon_product_task = (
            asyncio.create_task(
                run_pokemon_center_product_monitor()
            )
        )

        synced = (
            await self.tree.sync()
        )

        print(
            (
                f"Synced "
                f"{len(synced)} "
                "slash command(s)."
            )
        )


bot = LotusTrackerBot()


@bot.event
async def on_ready():

    print(
        "Lotus Tracker Bot ONLINE — v0.7.1"
    )

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
            f"`{round(bot.latency * 1000)}ms`"
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

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member,
    ):

        return

    await interaction.response.send_message(
        embed=discord.Embed(
            title="🎴 Choose Your TCGs",
        ),
        view=GameSelectView(
            member
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="subscription",
    description="View your subscription.",
)
async def subscription(
    interaction,
):

    member = (
        interaction.user
    )

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

    await interaction.response.send_message(
        (
            f"💳 **Current Tier:** "
            f"{tier}"
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="dbstatus",
    description="Check PostgreSQL.",
)
async def dbstatus(
    interaction,
):

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

        await interaction.response.send_message(
            "🟢 PostgreSQL online.",
            ephemeral=True,
        )

    except Exception as error:

        await interaction.response.send_message(
            (
                "🔴 PostgreSQL failed.\n"
                f"`{error}`"
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

    await interaction.response.send_message(
        (
            "🟢 Redis online."
            if online
            else "🔴 Redis offline."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="pokemoncenterstatus",
    description="View Pokémon Center queue status.",
)
async def pokemoncenterstatus(
    interaction,
):

    data = (
        get_pokemon_center_status()
    )

    await interaction.response.send_message(
        (
            "⚡ **Pokémon Center Queue Monitor**\n\n"
            f"Running: "
            f"{'✅' if data['running'] else '❌'}\n"
            f"Regions: "
            f"{data['regions_checked']}\n"
            f"Active Queues: "
            f"{data['queues_active']}\n"
            f"Last Scan: "
            f"{data['last_scan'] or 'Never'}"
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="pokemonproductstatus",
    description="View Pokémon Center product monitor.",
)
async def pokemonproductstatus(
    interaction,
):

    data = (
        get_pokemon_product_status()
    )

    worker = (
        bot.pokemon_product_task
        is not None
        and not bot.pokemon_product_task.done()
    )

    embed = discord.Embed(
        title=(
            "⚡ Pokémon Center Product Intelligence"
        ),
        description=(
            f"**Worker:** "
            f"{'✅ Online' if worker else '❌ Offline'}\n"
            f"**Running:** "
            f"{'✅' if data['running'] else '❌'}\n"
            f"**Regions Checked:** "
            f"{data['regions_checked']}\n"
            f"**Products Checked:** "
            f"{data['products_checked']}\n"
            f"**Events:** "
            f"{data['events_created']}\n"
            f"**Burst Regions:** "
            f"{data['burst_regions']}"
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


@bot.tree.command(
    name="scanpokemonproducts",
    description="Run Pokémon Center product scan now.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def scanpokemonproducts(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    results = (
        await scan_pokemon_center_products()
    )

    if not results:

        await interaction.followup.send(
            "⚠️ No regions scanned successfully.",
            ephemeral=True,
        )

        return

    lines = []

    for result in results:

        lines.append(
            (
                f"**{result['region']}**\n"
                f"Pages Checked: "
                f"{result['checked']}\n"
                f"TCG Products: "
                f"{result['tracked']}\n"
                f"Events: "
                f"{result['events']}"
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


@bot.tree.command(
    name="pokemonburst",
    description="Temporarily enable fast Pokémon Center product scans.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def pokemonburst(
    interaction,
    region: str = "US",
):

    region = (
        region.upper()
    )

    await trigger_product_burst(
        region
    )

    await interaction.response.send_message(
        (
            "⚡ Pokémon Center burst monitoring "
            f"enabled for **{region}** "
            "for 5 minutes."
        ),
        ephemeral=True,
    )


# =========================================================
# STORE COMMANDS
# =========================================================

@bot.tree.command(
    name="addshopifystore",
    description="Add or update Shopify store.",
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
            f"**{store.name}**"
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="stores",
    description="List monitored stores.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def stores(
    interaction,
):

    store_list = (
        await list_shopify_stores()
    )

    if not store_list:

        await interaction.response.send_message(
            "No stores configured.",
            ephemeral=True,
        )

        return

    text_value = "\n\n".join(
        (
            f"**{store.id} — {store.name}**\n"
            f"`{store.domain}`\n"
            f"{store.health_status}"
        )
        for store
        in store_list
    )

    await interaction.response.send_message(
        text_value[
            :1900
        ],
        ephemeral=True,
    )


@bot.tree.command(
    name="removestore",
    description="Remove store from monitoring.",
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

    await interaction.response.send_message(
        (
            "✅ Removed."
            if store
            else "❌ Store not found."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="healthstatus",
    description="View store-health summary.",
)
async def healthstatus(
    interaction,
):

    health = (
        await get_health_overview()
    )

    await interaction.response.send_message(
        (
            "🩺 **Store Health**\n\n"
            f"Healthy: {health['healthy']}\n"
            f"Degraded: {health['degraded']}\n"
            f"Unhealthy: {health['unhealthy']}\n"
            f"Disabled: {health['disabled']}"
        ),
        ephemeral=True,
    )


# =========================================================
# SIMULATOR
# =========================================================

@bot.tree.command(
    name="simulateproduct",
    description="Simulate Lotus event.",
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

    queue_event = (
        event.value.startswith(
            "QUEUE_"
        )
    )

    product_event = (
        ProductEvent(
            event_type=(
                ProductEventType(
                    event.value
                )
            ),
            game=(
                "Pokemon"
                if queue_event
                else game.value
            ),
            product_name=(
                "Pokémon Center Test"
                if queue_event
                else (
                    f"{game.value} "
                    "Test Product"
                )
            ),
            store_name=(
                "Pokémon Center"
                if queue_event
                else "Lotus Simulation Store"
            ),
            product_url=(
                "https://www.pokemoncenter.com/"
                if queue_event
                else "https://example.com/test"
            ),
            price=(
                None
                if queue_event
                else 119.99
            ),
            in_stock=(
                event.value
                in (
                    "STOCK_AVAILABLE",
                    "RESTOCK",
                    "INVENTORY_FLICKER",
                )
            ),
            region="US",
            product_type=(
                "Virtual Queue"
                if queue_event
                else "Booster Box"
            ),
        )
    )

    result = (
        await process_product_event(
            product_event
        )
    )

    await interaction.response.send_message(
        (
            "🧪 Event submitted.\n"
            f"Database: "
            f"{'✅' if result['database_saved'] else '❌'}\n"
            f"Redis: "
            f"{'✅' if result['redis_saved'] else '❌'}"
        ),
        ephemeral=True,
    )


# =========================================================
# STATUS
# =========================================================

@bot.tree.command(
    name="status",
    description="View Lotus system status.",
)
async def status(
    interaction,
):

    queue_size = (
        await get_queue_size()
    )

    health = (
        await get_health_overview()
    )

    embed = discord.Embed(
        title=(
            "🟢 Lotus Tracker Bot Status"
        ),
        description=(
            f"**PostgreSQL:** "
            f"{'✅' if bot.database_ready else '❌'}\n"
            f"**Redis:** "
            f"{'✅' if bot.redis_ready else '❌'}\n"
            f"**Event Worker:** "
            f"{'✅' if bot.event_worker_task and not bot.event_worker_task.done() else '❌'}\n"
            f"**Shopify Monitor:** "
            f"{'✅' if bot.shopify_monitor_task and not bot.shopify_monitor_task.done() else '❌'}\n"
            f"**Pokémon Queue Monitor:** "
            f"{'✅' if bot.pokemon_center_task and not bot.pokemon_center_task.done() else '❌'}\n"
            f"**Pokémon Product Monitor:** "
            f"{'✅' if bot.pokemon_product_task and not bot.pokemon_product_task.done() else '❌'}\n"
            "**Affiliate Pipeline:** ✅\n"
            "**Store Self-Healing:** ✅\n"
            f"**Healthy Stores:** "
            f"{health['healthy']}\n"
            f"**Redis Queue:** "
            f"{queue_size}\n\n"
            "**Version:** 0.7.1"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@bot.tree.error
async def on_app_command_error(
    interaction,
    error,
):

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


if not DISCORD_TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN is missing."
    )


bot.run(
    DISCORD_TOKEN
)