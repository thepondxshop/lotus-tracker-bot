import asyncio

import discord

from discord.ext import commands

from discord import app_commands

from sqlalchemy import (
    select,
    text,
)


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
# DATABASE MODELS
# =========================================================

from app.models import (
    Store,
)


# =========================================================
# CATEGORY ALERT PREFERENCES
# =========================================================

from app.preference_service import (
    apply_member_preference_roles,
    get_product_preferences,
    initialize_game_alert_roles,
    save_product_preferences,
)


# =========================================================
# PRODUCT FAMILY ALERT PREFERENCES
# =========================================================

from app.family_preference_service import (
    ensure_family_preferences,
    get_family_preferences,
    save_family_preferences,
)


# =========================================================
# PRICING REFERENCES
# =========================================================

from app.pricing_reference import (
    get_pricing_reference,
    remove_pricing_reference,
    set_pricing_reference,
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
    clear_event_queue,
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
    restore_shopify_store,
    retry_shopify_store,
    run_shopify_monitor,
    scan_all_shopify_stores,
    set_shopify_store_active,
)


# =========================================================
# UNIVERSAL RETAILERS
# =========================================================

from app.retailer_registry import (
    get_registered_retailer_platforms,
    normalize_platform,
)

from app.retailers import (
    load_retailer_adapters,
)

from app.universal_retailer_monitor import (
    get_universal_retailer_monitor_status,
    scan_store,
)


# =========================================================
# STORE HEALTH
# =========================================================

from app.store_health import (
    get_health_overview,
)


# =========================================================
# POKEMON CENTER QUEUE
# =========================================================

from app.pokemon_center_monitor import (
    get_pokemon_center_status,
    run_pokemon_center_monitor,
    scan_pokemon_center,
)


# =========================================================
# POKEMON CENTER PRODUCTS
# =========================================================

from app.pokemon_center_products import (
    add_pokemon_product,
    discover_pokemon_products,
    get_pokemon_product_status,
    list_pokemon_products,
    remove_pokemon_product,
    restore_pokemon_product,
    run_pokemon_center_product_monitor,
    scan_pokemon_center_products,
    trigger_product_burst,
)


# =========================================================
# LOTUS TRACKER BOT
# PonDeX Trackers
# Version 1.0.4
#
# Universal Retailer Foundation
# Regional Product Families
# Family Alert Preferences
# Hierarchical MSRP
# Cross-Currency MSRP
# Historical Pricing
# Deal Score
# Scalper Protection
# Smart Quick Cart
# =========================================================


# =========================================================
# INTENTS
# =========================================================

intents = (
    discord.Intents.default()
)

intents.members = True


# =========================================================
# GAME CHOICES
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


# =========================================================
# PRODUCT FAMILY CHOICES
# =========================================================

PRODUCT_FAMILY_CHOICES = [

    app_commands.Choice(
        name="English / Global Standard",
        value="GLOBAL_STANDARD",
    ),

    app_commands.Choice(
        name="Japanese",
        value="JP",
    ),

    app_commands.Choice(
        name="Korean",
        value="KR",
    ),

    app_commands.Choice(
        name="Simplified Chinese",
        value="CN",
    ),

    app_commands.Choice(
        name="Unknown / Unclassified",
        value="UNKNOWN",
    ),
]


# =========================================================
# MSRP FAMILY CHOICES
# =========================================================

MSRP_FAMILY_CHOICES = [

    app_commands.Choice(
        name="English / Global Standard",
        value="GLOBAL_STANDARD",
    ),

    app_commands.Choice(
        name="Japanese",
        value="JP",
    ),

    app_commands.Choice(
        name="Korean",
        value="KR",
    ),

    app_commands.Choice(
        name="Simplified Chinese",
        value="CN",
    ),
]


# =========================================================
# MSRP SCOPE CHOICES
# =========================================================

MSRP_SCOPE_CHOICES = [

    app_commands.Choice(
        name="Exact Product",
        value="EXACT_PRODUCT",
    ),

    app_commands.Choice(
        name="Product Type",
        value="PRODUCT_TYPE",
    ),

    app_commands.Choice(
        name="Game Default",
        value="GAME_DEFAULT",
    ),
]


# =========================================================
# MSRP CONFIDENCE CHOICES
# =========================================================

MSRP_CONFIDENCE_CHOICES = [

    app_commands.Choice(
        name="High â Official / Verified",
        value="HIGH",
    ),

    app_commands.Choice(
        name="Medium â Reliable Reference",
        value="MEDIUM",
    ),

    app_commands.Choice(
        name="Low â Unconfirmed Reference",
        value="LOW",
    ),
]


# =========================================================
# UNIVERSAL RETAILER PLATFORM CHOICES
# =========================================================

RETAILER_PLATFORM_CHOICES = [

    app_commands.Choice(
        name="Square / Weebly",
        value="square_weebly",
    ),
]


# =========================================================
# EVENT CHOICES
# =========================================================

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

    app_commands.Choice(
        name="Pokemon Queue Detected",
        value="QUEUE_DETECTED",
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


# =========================================================
# LABEL HELPERS
# =========================================================

PRODUCT_FAMILY_LABELS = {

    "GLOBAL_STANDARD":
        "ð English / Global Standard",

    "JP":
        "ð¯ðµ Japanese",

    "KR":
        "ð°ð· Korean",

    "CN":
        "ð¨ð³ Simplified Chinese",

    "UNKNOWN":
        "â Unknown / Unclassified",
}


MSRP_SCOPE_LABELS = {

    "EXACT_PRODUCT":
        "Exact Product",

    "PRODUCT_TYPE":
        "Product Type",

    "GAME_DEFAULT":
        "Game Default",
}


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
# GAME ROLE UPDATE
# =========================================================

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
            "â Use this inside the server.",
        )

    if interaction.guild is None:

        return (
            False,
            "â Use this inside the server.",
        )

    selected_games = set(
        selected_games
    )

    errors = []

    for (
        game_name,
        role_value,
    ) in GAME_ROLES.items():

        role_id = (
            safe_int(
                role_value
            )
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

                if (
                    role
                    not in member.roles
                ):

                    await member.add_roles(

                        role,

                        reason=(
                            "Lotus game selection"
                        ),
                    )

                    try:

                        await ensure_family_preferences(

                            member.id,

                            game_name,
                        )

                    except Exception as error:

                        print(
                            (
                                "FAMILY PREF INIT ERROR | "
                                f"User={member.id} | "
                                f"Game={game_name} | "
                                f"{type(error).__name__}: "
                                f"{error}"
                            )
                        )

            elif (
                role
                in member.roles
            ):

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

    try:

        await save_member_to_database(
            member
        )

    except Exception as error:

        print(
            (
                "USER DATABASE SAVE ERROR: "
                f"{type(error).__name__}: "
                f"{error}"
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
        "â **Game preferences updated.**\n\n"
    )

    if current_games:

        message += "\n".join(

            f"â¢ {game}"

            for game in sorted(
                current_games
            )
        )

    else:

        message += (
            "No games currently selected."
        )

    message += (
        "\n\nð Use `/familyprefs` to choose "
        "English, Japanese, Korean, and Chinese alerts."
    )

    if errors:

        message += (
            "\n\nâ ï¸ **Warnings:**\n"
        )

        message += "\n".join(

            f"â¢ {error}"

            for error in errors
        )

    return (
        True,
        message,
    )


# =========================================================
# GAME SELECT
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

            for role
            in member.roles
        }

        options = []

        for (
            game,
            emoji,
            description,
        ) in GAME_DATA:

            role_id = (
                safe_int(
                    GAME_ROLES.get(
                        game
                    )
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


# =========================================================
# PERSISTENT GAME SELECT
# =========================================================

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

        self.shopify_monitor_task = (
            asyncio.create_task(
                run_shopify_monitor()
            )
        )

        print(
            "Lotus Shopify Monitor task created."
        )

        self.pokemon_center_task = (
            asyncio.create_task(
                run_pokemon_center_monitor()
            )
        )

        print(
            "PokÃ©mon Center Queue Monitor task created."
        )

        self.pokemon_product_task = (
            asyncio.create_task(
                run_pokemon_center_product_monitor()
            )
        )

        print(
            "PokÃ©mon Center Product Monitor task created."
        )

        # NOTE:
        # Universal retailer monitor is intentionally NOT
        # started in v1.0.4 Step 6. Retailers are validated
        # manually through /scanretailer first.

        synced = (
            await self.tree.sync()
        )

        print(
            f"Synced {len(synced)} slash command(s)."
        )


bot = (
    LotusTrackerBot()
)


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        "=" * 60
    )

    print(
        "Lotus Tracker Bot is ONLINE!"
    )

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        "Version: 1.0.4"
    )

    print(
        "=" * 60
    )

    await bot.change_presence(

        activity=discord.Activity(

            type=(
                discord.ActivityType.watching
            ),

            name=(
                "TCG drops worldwide ð"
            ),
        )
    )


# =========================================================
# /PING
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
            "ð **Lotus is online.**\n"

            f"Latency: "
            f"`{round(bot.latency * 1000)}ms`\n"

            "**Version:** `1.0.4`"
        ),

        ephemeral=True,
    )


# =========================================================
# /GAMES
# =========================================================

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

    embed = discord.Embed(

        title="ð´ Choose Your TCGs",

        description=(
            "Select every game you want "
            "Lotus alerts for.\n\n"
            "After choosing a game, use `/alertprefs` "
            "and `/familyprefs` to customize its alerts."
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

    channel_id = (
        safe_int(
            CHANNEL_ROLES
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

            "â Roles channel not found.",

            ephemeral=True,
        )

        return

    embed = discord.Embed(

        title="ð´ Choose Your Games",

        description=(
            "Select every TCG you want Lotus alerts for.\n\n"
            "You can customize product types with `/alertprefs` "
            "and languages/regions with `/familyprefs`."
        ),
    )

    await channel.send(

        embed=embed,

        view=PersistentGameSelectView(),
    )

    await interaction.followup.send(

        (
            f"â Selector posted "
            f"in {channel.mention}."
        ),

        ephemeral=True,
    )


# =========================================================
# /ALERTPREFS
# =========================================================

@bot.tree.command(
    name="alertprefs",
    description="Choose which product types alert you for a TCG.",
)
@app_commands.choices(
    game=GAME_CHOICES,
)
async def alertprefs(
    interaction,
    game: app_commands.Choice[str],
    sealed: bool = True,
    singles: bool = False,
    accessories: bool = False,
    unknown: bool = True,
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member,
    ):

        await interaction.response.send_message(

            "â Use this inside the server.",

            ephemeral=True,
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    followed_games = (
        get_followed_games(
            member
        )
    )

    if (
        game.value
        not in followed_games
    ):

        await interaction.followup.send(

            (
                f"â You are not currently following "
                f"**{game.value}**.\n\n"

                "Use `/games` first."
            ),

            ephemeral=True,
        )

        return

    preferences = {

        "SEALED":
            sealed,

        "SINGLE":
            singles,

        "ACCESSORY":
            accessories,

        "UNKNOWN":
            unknown,
    }

    try:

        await save_product_preferences(

            discord_user_id=(
                member.id
            ),

            game=(
                game.value
            ),

            preferences=(
                preferences
            ),
        )

        role_errors = (
            await apply_member_preference_roles(

                member,

                game.value,

                preferences,
            )
        )

        message = (

            f"âï¸ **{game.value} Product Preferences**\n\n"

            f"{'â' if sealed else 'â'} "
            "Sealed Products\n"

            f"{'â' if singles else 'â'} "
            "Singles\n"

            f"{'â' if accessories else 'â'} "
            "Accessories\n"

            f"{'â' if unknown else 'â'} "
            "Unknown Product Types\n\n"

            "ð¾ Saved to Lotus.\n\n"

            "Use `/familyprefs` to separately choose "
            "English, Japanese, Korean, and Chinese products."
        )

        if role_errors:

            message += (
                "\n\nâ ï¸ **Role warnings:**\n"
            )

            message += "\n".join(

                f"â¢ {error}"

                for error
                in role_errors
            )

        await interaction.followup.send(

            message,

            ephemeral=True,
        )

    except discord.Forbidden:

        await interaction.followup.send(

            (
                "â Lotus cannot manage its alert roles.\n\n"

                "Give the Lotus bot role **Manage Roles** "
                "and place it above the Lotus alert roles."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Preferences could not be saved.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /MYPREFS
# =========================================================

@bot.tree.command(
    name="myprefs",
    description="View your Lotus product-type preferences.",
)
@app_commands.choices(
    game=GAME_CHOICES,
)
async def myprefs(
    interaction,
    game: app_commands.Choice[str],
):

    preferences = (
        await get_product_preferences(

            interaction.user.id,

            game.value,
        )
    )

    await interaction.response.send_message(

        (
            f"âï¸ **{game.value} Product Preferences**\n\n"

            f"{'â' if preferences['SEALED'] else 'â'} "
            "Sealed Products\n"

            f"{'â' if preferences['SINGLE'] else 'â'} "
            "Singles\n"

            f"{'â' if preferences['ACCESSORY'] else 'â'} "
            "Accessories\n"

            f"{'â' if preferences['UNKNOWN'] else 'â'} "
            "Unknown Product Types"
        ),

        ephemeral=True,
    )


# =========================================================
# /FAMILYPREFS
# =========================================================

@bot.tree.command(
    name="familyprefs",
    description="Choose product languages/regions for a TCG.",
)
@app_commands.choices(
    game=GAME_CHOICES,
)
async def familyprefs(
    interaction,
    game: app_commands.Choice[str],
    english: bool = True,
    japanese: bool = False,
    korean: bool = False,
    chinese: bool = False,
    unknown: bool = False,
):

    member = (
        interaction.user
    )

    if not isinstance(
        member,
        discord.Member,
    ):

        await interaction.response.send_message(

            "â Use this inside the server.",

            ephemeral=True,
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    followed_games = (
        get_followed_games(
            member
        )
    )

    if (
        game.value
        not in followed_games
    ):

        await interaction.followup.send(

            (
                f"â You are not currently following "
                f"**{game.value}**.\n\n"

                "Use `/games` first."
            ),

            ephemeral=True,
        )

        return

    preferences = {

        "GLOBAL_STANDARD":
            english,

        "JP":
            japanese,

        "KR":
            korean,

        "CN":
            chinese,

        "UNKNOWN":
            unknown,
    }

    try:

        saved = (
            await save_family_preferences(

                discord_user_id=(
                    member.id
                ),

                game=(
                    game.value
                ),

                preferences=(
                    preferences
                ),
            )
        )

        message = (

            f"ð **{game.value} Product Family Preferences**\n\n"

            f"{'â' if saved['GLOBAL_STANDARD'] else 'â'} "
            "English / Global Standard\n"

            f"{'â' if saved['JP'] else 'â'} "
            "Japanese\n"

            f"{'â' if saved['KR'] else 'â'} "
            "Korean\n"

            f"{'â' if saved['CN'] else 'â'} "
            "Simplified Chinese\n"

            f"{'â' if saved['UNKNOWN'] else 'â'} "
            "Unknown / Unclassified\n\n"

            "ð¾ Saved to Lotus.\n\n"

            "These preferences are specific to "
            f"**{game.value}**."
        )

        await interaction.followup.send(

            message,

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Family preferences could not be saved.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /MYFAMILYPREFS
# =========================================================

@bot.tree.command(
    name="myfamilyprefs",
    description="View your language/region preferences for a TCG.",
)
@app_commands.choices(
    game=GAME_CHOICES,
)
async def myfamilyprefs(
    interaction,
    game: app_commands.Choice[str],
):

    try:

        preferences = (
            await get_family_preferences(

                interaction.user.id,

                game.value,
            )
        )

        await interaction.response.send_message(

            (
                f"ð **{game.value} Product Family Preferences**\n\n"

                f"{'â' if preferences['GLOBAL_STANDARD'] else 'â'} "
                "English / Global Standard\n"

                f"{'â' if preferences['JP'] else 'â'} "
                "Japanese\n"

                f"{'â' if preferences['KR'] else 'â'} "
                "Korean\n"

                f"{'â' if preferences['CN'] else 'â'} "
                "Simplified Chinese\n"

                f"{'â' if preferences['UNKNOWN'] else 'â'} "
                "Unknown / Unclassified\n\n"

                "Product family is based on the actual product, "
                "not the currency the retailer charges."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.response.send_message(

            (
                "â Family preferences could not be loaded.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /SETUPALERTPREFS
# =========================================================

@bot.tree.command(
    name="setupalertprefs",
    description="Initialize product alert roles for a game.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    game=GAME_CHOICES,
)
async def setupalertprefs(
    interaction,
    game: app_commands.Choice[str],
):

    await interaction.response.defer(
        ephemeral=True
    )

    if interaction.guild is None:

        return

    try:

        result = (
            await initialize_game_alert_roles(

                interaction.guild,

                game.value,
            )
        )

        initialized_family_members = 0

        role_id = (
            safe_int(
                GAME_ROLES.get(
                    game.value
                )
            )
        )

        game_role = (

            interaction.guild.get_role(
                role_id
            )

            if role_id

            else None
        )

        if game_role:

            for member in game_role.members:

                if member.bot:

                    continue

                try:

                    await ensure_family_preferences(

                        member.id,

                        game.value,
                    )

                    initialized_family_members += 1

                except Exception as error:

                    print(
                        (
                            "FAMILY PREF INIT ERROR | "
                            f"User={member.id} | "
                            f"Game={game.value} | "
                            f"{type(error).__name__}: "
                            f"{error}"
                        )
                    )

        await interaction.followup.send(

            (
                f"â **{game.value} alert preferences initialized.**\n\n"

                f"Category members initialized: "
                f"`{result['members']}`\n"

                f"Family members initialized: "
                f"`{initialized_family_members}`\n\n"

                "**Default category preferences:**\n"

                "â Sealed Products\n"

                "â Singles\n"

                "â Accessories\n"

                "â Unknown Product Types\n\n"

                "**Default family preferences:**\n"

                "â English / Global Standard\n"

                "â Japanese\n"

                "â Korean\n"

                "â Simplified Chinese\n"

                "â Unknown / Unclassified\n\n"

                "Members can customize these using "
                "`/alertprefs` and `/familyprefs`."
            ),

            ephemeral=True,
        )

    except discord.Forbidden:

        await interaction.followup.send(

            (
                "â Lotus needs **Manage Roles**.\n\n"

                "Also make sure the Lotus bot Discord role "
                "is above its alert roles."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Alert preference setup failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# MSRP ADMINISTRATION
# =========================================================


# =========================================================
# /SETMSRP
# =========================================================

@bot.tree.command(
    name="setmsrp",
    description="Add or update a Lotus MSRP rule.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    game=GAME_CHOICES,
    scope=MSRP_SCOPE_CHOICES,
    family=MSRP_FAMILY_CHOICES,
    confidence=MSRP_CONFIDENCE_CHOICES,
)
async def setmsrp(
    interaction,
    game: app_commands.Choice[str],
    scope: app_commands.Choice[str],
    family: app_commands.Choice[str],
    amount: float,
    match_value: str = "",
    currency: str = "USD",
    source: str = "Verified MSRP",
    confidence: app_commands.Choice[str] = None,
    region: str = "GLOBAL",
):

    await interaction.response.defer(
        ephemeral=True
    )

    if amount <= 0:

        await interaction.followup.send(

            "â MSRP must be greater than 0.",

            ephemeral=True,
        )

        return

    if SessionLocal is None:

        await interaction.followup.send(

            "â PostgreSQL is unavailable.",

            ephemeral=True,
        )

        return

    if (
        scope.value
        != "GAME_DEFAULT"

        and

        not match_value.strip()
    ):

        await interaction.followup.send(

            (
                "â A Match Value is required for "
                "Exact Product and Product Type rules."
            ),

            ephemeral=True,
        )

        return

    actual_match_value = (

        None

        if (
            scope.value
            == "GAME_DEFAULT"
        )

        else (
            match_value.strip()
        )
    )

    confidence_value = (

        confidence.value

        if confidence

        else "HIGH"
    )

    try:

        async with SessionLocal() as session:

            row, created = (
                await set_pricing_reference(

                    session,

                    game=(
                        game.value
                    ),

                    scope_type=(
                        scope.value
                    ),

                    product_family=(
                        family.value
                    ),

                    match_value=(
                        actual_match_value
                    ),

                    amount=(
                        amount
                    ),

                    currency=(
                        currency
                    ),

                    source=(
                        source
                    ),

                    confidence=(
                        confidence_value
                    ),

                    kind="MSRP",

                    region=(
                        region
                    ),
                )
            )

        family_label = (
            PRODUCT_FAMILY_LABELS.get(
                family.value,
                family.value,
            )
        )

        scope_label = (
            MSRP_SCOPE_LABELS.get(
                scope.value,
                scope.value,
            )
        )

        await interaction.followup.send(

            (
                f"{'â MSRP rule added.' if created else 'â MSRP rule updated.'}"
                "\n\n"

                f"**Game:** {row.game}\n"

                f"**Product Family:** "
                f"{family_label}\n"

                f"**Scope:** "
                f"{scope_label}\n"

                f"**Match:** "
                f"{row.match_value or 'All eligible products in game'}\n"

                f"**MSRP:** "
                f"{row.amount:.2f} "
                f"{row.currency}\n"

                f"**Region:** "
                f"{row.region}\n"

                f"**Source:** "
                f"{row.source}\n"

                f"**Confidence:** "
                f"{row.confidence}\n\n"

                "Lotus will only apply this reference to "
                f"**{family_label}** products."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â MSRP rule could not be saved.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /VIEWMSRP
# =========================================================

@bot.tree.command(
    name="viewmsrp",
    description="View a Lotus MSRP rule.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    game=GAME_CHOICES,
    scope=MSRP_SCOPE_CHOICES,
    family=MSRP_FAMILY_CHOICES,
)
async def viewmsrp(
    interaction,
    game: app_commands.Choice[str],
    scope: app_commands.Choice[str],
    family: app_commands.Choice[str],
    match_value: str = "",
    region: str = "GLOBAL",
):

    await interaction.response.defer(
        ephemeral=True
    )

    if SessionLocal is None:

        await interaction.followup.send(

            "â PostgreSQL is unavailable.",

            ephemeral=True,
        )

        return

    if (
        scope.value
        != "GAME_DEFAULT"

        and

        not match_value.strip()
    ):

        await interaction.followup.send(

            (
                "â A Match Value is required for "
                "Exact Product and Product Type rules."
            ),

            ephemeral=True,
        )

        return

    actual_match_value = (

        None

        if (
            scope.value
            == "GAME_DEFAULT"
        )

        else (
            match_value.strip()
        )
    )

    try:

        async with SessionLocal() as session:

            row = (
                await get_pricing_reference(

                    session,

                    game=(
                        game.value
                    ),

                    scope_type=(
                        scope.value
                    ),

                    product_family=(
                        family.value
                    ),

                    match_value=(
                        actual_match_value
                    ),

                    region=(
                        region
                    ),

                    kind="MSRP",
                )
            )

        if row is None:

            await interaction.followup.send(

                (
                    "â No matching MSRP rule found.\n\n"

                    f"**Game:** "
                    f"{game.value}\n"

                    f"**Family:** "
                    f"{PRODUCT_FAMILY_LABELS.get(family.value, family.value)}\n"

                    f"**Scope:** "
                    f"{MSRP_SCOPE_LABELS.get(scope.value, scope.value)}\n"

                    f"**Match:** "
                    f"{actual_match_value or 'Game Default'}\n"

                    f"**Region:** "
                    f"{region.upper()}"
                ),

                ephemeral=True,
            )

            return

        embed = discord.Embed(

            title="ð·ï¸ Lotus MSRP Rule",

            description=(
                f"**{row.product_name}**"
            ),
        )

        embed.add_field(
            name="Game",
            value=row.game,
            inline=True,
        )

        embed.add_field(
            name="Product Family",
            value=(
                PRODUCT_FAMILY_LABELS.get(
                    row.product_family,
                    row.product_family,
                )
            ),
            inline=True,
        )

        embed.add_field(
            name="Scope",
            value=(
                MSRP_SCOPE_LABELS.get(
                    row.scope_type,
                    row.scope_type,
                )
            ),
            inline=True,
        )

        embed.add_field(
            name="Match",
            value=(
                row.match_value
                or "Game Default"
            ),
            inline=True,
        )

        embed.add_field(
            name="MSRP",
            value=(
                f"{row.amount:.2f} "
                f"{row.currency}"
            ),
            inline=True,
        )

        embed.add_field(
            name="Region",
            value=row.region,
            inline=True,
        )

        embed.add_field(
            name="Confidence",
            value=row.confidence,
            inline=True,
        )

        embed.add_field(
            name="Source",
            value=row.source,
            inline=False,
        )

        embed.add_field(
            name="Internal Match Key",
            value=(
                f"`{row.normalized_name}`"
            ),
            inline=False,
        )

        embed.set_footer(
            text=(
                "MSRP isolation: "
                "GLOBAL_STANDARD / JP / KR / CN"
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â MSRP lookup failed.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /REMOVEMSRP
# =========================================================

@bot.tree.command(
    name="removemsrp",
    description="Disable a Lotus MSRP rule.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    game=GAME_CHOICES,
    scope=MSRP_SCOPE_CHOICES,
    family=MSRP_FAMILY_CHOICES,
)
async def removemsrp(
    interaction,
    game: app_commands.Choice[str],
    scope: app_commands.Choice[str],
    family: app_commands.Choice[str],
    match_value: str = "",
    region: str = "GLOBAL",
):

    await interaction.response.defer(
        ephemeral=True
    )

    if SessionLocal is None:

        await interaction.followup.send(

            "â PostgreSQL is unavailable.",

            ephemeral=True,
        )

        return

    if (
        scope.value
        != "GAME_DEFAULT"

        and

        not match_value.strip()
    ):

        await interaction.followup.send(

            (
                "â A Match Value is required for "
                "Exact Product and Product Type rules."
            ),

            ephemeral=True,
        )

        return

    actual_match_value = (

        None

        if (
            scope.value
            == "GAME_DEFAULT"
        )

        else (
            match_value.strip()
        )
    )

    try:

        async with SessionLocal() as session:

            row = (
                await remove_pricing_reference(

                    session,

                    game=(
                        game.value
                    ),

                    scope_type=(
                        scope.value
                    ),

                    product_family=(
                        family.value
                    ),

                    match_value=(
                        actual_match_value
                    ),

                    region=(
                        region
                    ),

                    kind="MSRP",
                )
            )

        if row is None:

            await interaction.followup.send(

                (
                    "â MSRP rule not found.\n\n"

                    f"**Game:** "
                    f"{game.value}\n"

                    f"**Family:** "
                    f"{PRODUCT_FAMILY_LABELS.get(family.value, family.value)}\n"

                    f"**Scope:** "
                    f"{scope.value}\n"

                    f"**Match:** "
                    f"{actual_match_value or 'Game Default'}"
                ),

                ephemeral=True,
            )

            return

        await interaction.followup.send(

            (
                "ðï¸ **MSRP rule disabled.**\n\n"

                f"**Game:** "
                f"{row.game}\n"

                f"**Family:** "
                f"{PRODUCT_FAMILY_LABELS.get(row.product_family, row.product_family)}\n"

                f"**Scope:** "
                f"{MSRP_SCOPE_LABELS.get(row.scope_type, row.scope_type)}\n"

                f"**Match:** "
                f"{row.match_value or 'Game Default'}\n"

                f"**MSRP:** "
                f"{row.amount:.2f} "
                f"{row.currency}\n\n"

                "The historical rule remains stored "
                "but will no longer be used."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â MSRP rule could not be removed.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
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

    games = (
        get_followed_games(
            member
        )
    )

    tier_details = {

        "Free": (
            "âª",
            "$0",
            (
                "â¢ Major retailer alerts\n"
                "â¢ Basic stock alerts\n"
                "â¢ Game selection\n"
                "â¢ Product family preferences"
            ),
        ),

        "Lite": (
            "ð¿",
            "$1.99/month",
            (
                "â¢ Everything in Free\n"
                "â¢ Preorder alerts\n"
                "â¢ Preorder calendar\n"
                "â¢ Priority support\n"
                "â¢ 14-day free trial"
            ),
        ),

        "Premium": (
            "ð",
            "$17.99/month",
            (
                "â¢ Everything in Lite\n"
                "â¢ Shopify / TCG shops\n"
                "â¢ Early page detection\n"
                "â¢ Price drops & deals\n"
                "â¢ International alerts\n"
                "â¢ Pricing Intelligence\n"
                "â¢ Advanced discovery"
            ),
        ),

        "Premium+": (
            "ð",
            "$44.99/month",
            (
                "â¢ Everything in Premium\n"
                "â¢ Inventory Flicker â¡\n"
                "â¢ Release Radar\n"
                "â¢ PokÃ©mon Center Queue Intelligence\n"
                "â¢ Global intelligence\n"
                "â¢ Scalper Protection\n"
                "â¢ Earliest detections"
            ),
        ),
    }

    icon, price, features = (
        tier_details.get(
            tier,
            tier_details[
                "Free"
            ],
        )
    )

    embed = discord.Embed(

        title=(
            f"{icon} PonDeX Subscription"
        ),

        description=(
            f"**Current Tier:** {tier}\n"
            f"**Price:** {price}"
        ),
    )

    embed.add_field(
        name="Your Access",
        value=features,
        inline=False,
    )

    embed.add_field(

        name="Games",

        value=(

            "\n".join(
                f"â¢ {game}"
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


# =========================================================
# /SETTINGS
# =========================================================

@bot.tree.command(
    name="settings",
    description="View Lotus settings.",
)
async def settings(
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

    games = (
        get_followed_games(
            member
        )
    )

    features = [

        (
            "Major Retailer Alerts",
            "Free",
        ),

        (
            "Preorder Alerts",
            "Lite",
        ),

        (
            "Shopify Drops",
            "Premium",
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
            "Pricing Intelligence",
            "Premium",
        ),

        (
            "International",
            "Premium",
        ),

        (
            "Release Radar",
            "Premium+",
        ),

        (
            "Inventory Flicker",
            "Premium+",
        ),

        (
            "Scalper Protection",
            "Premium+",
        ),

        (
            "PokÃ©mon Center Queue",
            "Premium+",
        ),
    ]

    feature_text = "\n".join(

        (
            "â"

            if tier_allows(
                tier,
                required
            )

            else "ð"
        )

        + f" {name}"

        for (
            name,
            required,
        )
        in features
    )

    embed = discord.Embed(

        title="âï¸ Lotus Settings",

        description=(
            f"**Subscription:** {tier}\n\n"

            "`/games` â Choose TCGs\n"
            "`/alertprefs` â Sealed / Singles / Accessories\n"
            "`/familyprefs` â English / JP / KR / CN"
        ),
    )

    embed.add_field(

        name="Games",

        value=(

            "\n".join(
                f"â {game}"
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


# =========================================================
# /DBME
# =========================================================

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

    if (

        profile is None

        and

        isinstance(
            interaction.user,
            discord.Member,
        )

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

            "â Profile could not be loaded.",

            ephemeral=True,
        )

        return

    games_text = (

        "\n".join(

            f"â¢ {game}"

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

    await interaction.followup.send(

        (
            "ð¾ **Lotus Database Profile**\n\n"

            f"Tier: "
            f"**{profile['subscription']}**\n\n"

            f"Games:\n"
            f"{games_text}"
        ),

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

            "ð¢ PostgreSQL is online.",

            ephemeral=True,
        )

    except Exception as error:

        bot.database_ready = False

        await interaction.followup.send(

            (
                "ð´ PostgreSQL failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
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

    bot.redis_ready = (
        online
    )

    await interaction.response.send_message(

        (
            "ð¢ Redis is online."

            if online

            else "ð´ Redis is offline."
        ),

        ephemeral=True,
    )


# =========================================================
# /EVENTSTATUS
# =========================================================

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

    worker_online = (

        bot.event_worker_task
        is not None

        and

        not bot.event_worker_task.done()
    )

    embed = discord.Embed(

        title="ð¡ Lotus Event Engine",

        description=(

            f"**PostgreSQL:** "
            f"{'â' if bot.database_ready else 'â'}\n"

            f"**Redis:** "
            f"{'â' if bot.redis_ready else 'â'}\n"

            f"**Event Worker:** "
            f"{'â' if worker_online else 'â'}\n"

            f"**Queue:** `{queue}`\n\n"

            "**Strict TCG Classification:** â\n"

            "**Product Category Filtering:** â\n"

            "**Product Family Detection:** â\n"

            "**Member Family Preferences:** â\n"

            "**Game + Category + Family Audience:** â\n"

            "**Native Currency:** â\n"

            "**USD Conversion:** â\n"

            "**Historical Pricing:** â\n"

            "**Hierarchical MSRP:** â\n"

            "**Regional MSRP Isolation:** â\n"

            "**Cross-Currency MSRP:** â\n"

            "**Deal Score:** â\n"

            "**Scalper Protection:** â\n"

            "**Smart Quick Cart:** â\n"

            "**Product Images:** â\n"

            "**Affiliate Pipeline:** â\n"

            "**Universal Retailer Foundation:** â\n\n"

            "**Engine Version:** `1.0.4`"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /CLEAREVENTQUEUE
# =========================================================

@bot.tree.command(
    name="cleareventqueue",
    description="Clear stale Lotus product events from Redis.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def cleareventqueue(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    removed = (
        await clear_event_queue()
    )

    await interaction.followup.send(

        (
            "ð§¹ **Lotus event queue cleared.**\n\n"

            f"Removed: "
            f"`{removed}` stale event(s)\n\n"

            "PostgreSQL history was preserved."
        ),

        ephemeral=True,
    )


# =========================================================
# UNIVERSAL RETAILER MANAGEMENT
# PonDeX Trackers
# Version 1.0.4
#
# Current supported platform:
# - Square / Weebly
#
# New retailers are staged INACTIVE.
#
# /scanretailer is always silent during this milestone.
# =========================================================


def normalize_retailer_domain(
    value: str,
) -> str:

    value = (
        str(
            value
            or ""
        )
        .strip()
        .lower()
    )

    value = (
        value
        .replace(
            "https://",
            "",
        )
        .replace(
            "http://",
            "",
        )
    )

    value = (
        value.split(
            "/"
        )[
            0
        ]
    )

    value = (
        value.split(
            "?"
        )[
            0
        ]
    )

    value = (
        value.split(
            "#"
        )[
            0
        ]
    )

    if value.startswith(
        "www."
    ):

        value = (
            value[
                4:
            ]
        )

    return (
        value.strip()
    )


# =========================================================
# /ADDRETAILER
# =========================================================

@bot.tree.command(
    name="addretailer",
    description="Stage a universal retailer for Lotus monitoring.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    platform=RETAILER_PLATFORM_CHOICES,
)
async def addretailer(
    interaction,
    name: str,
    domain: str,
    platform: app_commands.Choice[str],
    region: str = "US",
):

    await interaction.response.defer(
        ephemeral=True
    )

    if SessionLocal is None:

        await interaction.followup.send(
            "â PostgreSQL is unavailable.",
            ephemeral=True,
        )

        return

    clean_name = (
        str(
            name
            or ""
        ).strip()
    )

    clean_domain = (
        normalize_retailer_domain(
            domain
        )
    )

    clean_region = (
        str(
            region
            or "US"
        )
        .strip()
        .upper()
    )

    clean_platform = (
        normalize_platform(
            platform.value
        )
    )

    if not clean_name:

        await interaction.followup.send(
            "â Retailer name is required.",
            ephemeral=True,
        )

        return

    if not clean_domain:

        await interaction.followup.send(
            "â Retailer domain is required.",
            ephemeral=True,
        )

        return

    try:

        load_retailer_adapters()

    except Exception as error:

        await interaction.followup.send(

            (
                "â Retailer adapters could not be loaded.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )

        return

    registered_platforms = set(
        get_registered_retailer_platforms()
    )

    if clean_platform not in registered_platforms:

        await interaction.followup.send(

            (
                "â No Lotus adapter is currently registered "
                f"for `{clean_platform}`."
            ),

            ephemeral=True,
        )

        return

    if clean_platform != "square_weebly":

        await interaction.followup.send(

            (
                "â That retailer platform has not yet passed "
                "Lotus universal-retailer validation."
            ),

            ephemeral=True,
        )

        return

    try:

        async with SessionLocal() as session:

            candidate_domains = {

                clean_domain,

                f"www.{clean_domain}",
            }

            statement = (
                select(
                    Store
                )
                .where(
                    Store.domain.in_(
                        candidate_domains
                    )
                )
                .limit(
                    1
                )
            )

            result = (
                await session.execute(
                    statement
                )
            )

            existing = (
                result.scalar_one_or_none()
            )

            if existing is not None:

                await interaction.followup.send(

                    (
                        "â ï¸ **Retailer already registered.**\n\n"

                        f"**Store ID:** "
                        f"`{existing.id}`\n"

                        f"**Name:** "
                        f"{existing.name}\n"

                        f"**Domain:** "
                        f"`{existing.domain}`\n"

                        f"**Platform:** "
                        f"`{existing.platform or 'Unknown'}`\n"

                        f"**Active:** "
                        f"`{existing.active}`\n\n"

                        "No duplicate store was created."
                    ),

                    ephemeral=True,
                )

                return

            store = Store(

                name=(
                    clean_name
                ),

                domain=(
                    clean_domain
                ),

                platform=(
                    clean_platform
                ),

                region=(
                    clean_region
                ),

                active=False,

                health_status="HEALTHY",

                consecutive_failures=0,

                disabled_reason=(
                    "UNIVERSAL_STAGING"
                ),
            )

            session.add(
                store
            )

            await session.commit()

            await session.refresh(
                store
            )

            store_id = (
                store.id
            )

            store_name = (
                store.name
            )

            store_domain = (
                store.domain
            )

            store_region = (
                store.region
            )

        embed = discord.Embed(

            title=(
                "ð Universal Retailer Staged"
            ),

            description=(
                f"**{store_name}** has been added "
                "to Lotus's Universal Retailer Foundation."
            ),
        )

        embed.add_field(
            name="Store ID",
            value=(
                f"`{store_id}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Platform",
            value="`Square / Weebly`",
            inline=True,
        )

        embed.add_field(
            name="Region",
            value=(
                f"`{store_region}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Domain",
            value=(
                f"`{store_domain}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Monitoring",
            value="â« Staged / Inactive",
            inline=True,
        )

        embed.add_field(
            name="Discord Alerts",
            value="ð Disabled",
            inline=True,
        )

        embed.add_field(

            name="Next Step",

            value=(
                f"Run `/scanretailer store_id:{store_id}` "
                "to perform the controlled silent scan."
            ),

            inline=False,
        )

        embed.set_footer(
            text=(
                "Lotus Universal Retailer Foundation â¢ v1.0.4"
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Retailer could not be added.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /SCANRETAILER
# =========================================================

@bot.tree.command(
    name="scanretailer",
    description="Run a controlled silent universal-retailer scan.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def scanretailer(
    interaction,
    store_id: int,
):

    await interaction.response.defer(
        ephemeral=True
    )

    if SessionLocal is None:

        await interaction.followup.send(
            "â PostgreSQL is unavailable.",
            ephemeral=True,
        )

        return

    try:

        async with SessionLocal() as session:

            statement = (
                select(
                    Store
                )
                .where(
                    Store.id
                    ==
                    store_id
                )
                .limit(
                    1
                )
            )

            result = (
                await session.execute(
                    statement
                )
            )

            store = (
                result.scalar_one_or_none()
            )

            if store is None:

                await interaction.followup.send(
                    "â Retailer Store ID not found.",
                    ephemeral=True,
                )

                return

            scan_store_object = Store(

                id=(
                    store.id
                ),

                name=(
                    store.name
                ),

                domain=(
                    store.domain
                ),

                platform=(
                    store.platform
                ),

                region=(
                    store.region
                ),

                active=(
                    store.active
                ),

                health_status=(
                    store.health_status
                    or "HEALTHY"
                ),

                consecutive_failures=(
                    store.consecutive_failures
                    or 0
                ),
            )

        platform = (
            normalize_platform(
                scan_store_object.platform
            )
        )

        if platform == "shopify":

            await interaction.followup.send(

                (
                    "â This is a Shopify store.\n\n"

                    "Use `/scanshopify` instead."
                ),

                ephemeral=True,
            )

            return

        if platform == "pokemon_center":

            await interaction.followup.send(

                (
                    "â PokÃ©mon Center uses its dedicated "
                    "monitor."
                ),

                ephemeral=True,
            )

            return

        if platform == "major_retailer":

            await interaction.followup.send(

                (
                    "â Major retailers use their dedicated "
                    "monitoring pipeline."
                ),

                ephemeral=True,
            )

            return

        if platform != "square_weebly":

            await interaction.followup.send(

                (
                    "â This platform is not yet approved "
                    "for Universal Retailer scanning.\n\n"

                    f"Platform: `{platform}`"
                ),

                ephemeral=True,
            )

            return

        load_retailer_adapters()

        if (
            platform
            not in set(
                get_registered_retailer_platforms()
            )
        ):

            await interaction.followup.send(

                (
                    "â The Square / Weebly adapter "
                    "is not registered."
                ),

                ephemeral=True,
            )

            return

        before_status = (
            get_universal_retailer_monitor_status()
        )

        scan_result = (
            await scan_store(

                scan_store_object,

                suppress_events=True,
            )
        )

        after_status = (
            get_universal_retailer_monitor_status()
        )

        if not scan_result.get(
            "success"
        ):

            await interaction.followup.send(

                (
                    "â **Universal Retailer Scan Failed**\n\n"

                    f"**Store:** "
                    f"{scan_store_object.name}\n"

                    f"**Domain:** "
                    f"`{scan_store_object.domain}`\n"

                    f"**Platform:** "
                    f"`{platform}`\n\n"

                    f"**Reason:** "
                    f"`{scan_result.get('error') or 'Unknown error'}`\n\n"

                    "No universal retailer alerts were sent."
                ),

                ephemeral=True,
            )

            return

        unknown_before = int(
            before_status.get(
                "unknown_availability",
                0,
            )
            or 0
        )

        unknown_after = int(
            after_status.get(
                "unknown_availability",
                0,
            )
            or 0
        )

        missing_before = int(
            before_status.get(
                "missing_prices",
                0,
            )
            or 0
        )

        missing_after = int(
            after_status.get(
                "missing_prices",
                0,
            )
            or 0
        )

        unknown_stock = max(
            0,
            unknown_after
            -
            unknown_before,
        )

        missing_prices = max(
            0,
            missing_after
            -
            missing_before,
        )

        embed = discord.Embed(

            title=(
                "ð Universal Retailer Scan"
            ),

            description=(
                f"Controlled scan completed for "
                f"**{scan_store_object.name}**."
            ),
        )

        embed.add_field(
            name="Store ID",
            value=(
                f"`{scan_store_object.id}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Platform",
            value="`Square / Weebly`",
            inline=True,
        )

        embed.add_field(
            name="Region",
            value=(
                f"`{scan_store_object.region or 'US'}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Domain",
            value=(
                f"`{scan_store_object.domain}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Relevant TCG Products",
            value=(
                f"`{scan_result.get('products', 0)}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="New Database Rows",
            value=(
                f"`{scan_result.get('created', 0)}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Updated Rows",
            value=(
                f"`{scan_result.get('updated', 0)}`"
            ),
            inline=True,
        )

        embed.add_field(

            name="Baseline",

            value=(

                "ð± Initial Baseline"

                if scan_result.get(
                    "baseline_mode"
                )

                else "â Existing Baseline"
            ),

            inline=True,
        )

        embed.add_field(
            name="Discord Alerts Sent",
            value=(
                f"`{scan_result.get('events', 0)}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Events Suppressed",
            value=(
                f"`{scan_result.get('suppressed', 0)}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Unknown Availability",
            value=(
                f"`{unknown_stock}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Missing Prices",
            value=(
                f"`{missing_prices}`"
            ),
            inline=True,
        )

        embed.add_field(

            name="Safety Mode",

            value=(
                "ð **Forced Silent Scan**\n"
                "No product events were allowed "
                "to reach Discord."
            ),

            inline=False,
        )

        if (
            scan_result.get(
                "events",
                0
            )
            != 0
        ):

            embed.add_field(

                name="â ï¸ Safety Warning",

                value=(
                    "The controlled scan reported a non-zero "
                    "published event count. Do **not** activate "
                    "this retailer yet."
                ),

                inline=False,
            )

        else:

            embed.add_field(
                name="Status",
                value=(
                    "â Scan completed with alerts suppressed."
                ),
                inline=False,
            )

        embed.set_footer(
            text=(
                "Lotus Universal Retailer Foundation â¢ v1.0.4"
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Universal retailer scan failed.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# SHOPIFY STORE MANAGEMENT
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
                f"{'â Added' if created else 'â Updated'} "
                f"**{store.name}**\n"

                f"`{store.domain}`\n"

                f"Region: `{store.region}`"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Store could not be added.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /STORES
# =========================================================

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
                f"**ID {store.id} â "
                f"{store.name}**\n"

                f"`{store.domain}`\n"

                f"Region: `{store.region or 'Unknown'}`\n"

                f"{'ð¢' if store.active else 'â«'} "
                f"{store.health_status}"

                + (

                    f" â¢ {store.disabled_reason}"

                    if store.disabled_reason

                    else ""
                )
            )
        )

    await interaction.followup.send(

        (
            "\n\n".join(
                lines
            )
        )[:1900],

        ephemeral=True,
    )


# =========================================================
# /STOREINFO
# =========================================================

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
            "â Store ID not found.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            f"ðª {store.name}"
        )
    )

    embed.add_field(
        name="Store ID",
        value=str(
            store.id
        ),
    )

    embed.add_field(
        name="Health",
        value=(
            store.health_status
        ),
    )

    embed.add_field(
        name="Active",
        value=(
            "Yes â"
            if store.active
            else "No â"
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
        name="Region",
        value=(
            store.region
            or "Unknown"
        ),
    )

    embed.add_field(
        name="Failures",
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
            store.last_error[
                :1000
            ]
            if store.last_error
            else "None â"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /DISABLESTORE
# =========================================================

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
            "â Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"â« **{store.name}** manually disabled.\n\n"

            "It will not automatically reactivate."
        ),

        ephemeral=True,
    )


# =========================================================
# /ENABLESTORE
# =========================================================

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
            "â Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        f"ð¢ **{store.name}** enabled.",
        ephemeral=True,
    )


# =========================================================
# /REMOVESTORE
# =========================================================

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
            "â Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"ðï¸ **{store.name}** removed "
            "from active monitoring.\n\n"

            "Historical data remains preserved."
        ),

        ephemeral=True,
    )


# =========================================================
# /RESTORESTORE
# =========================================================

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
            "â Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"â»ï¸ **{store.name}** restored "
            "to active monitoring."
        ),

        ephemeral=True,
    )


# =========================================================
# /HEALTHSTATUS
# =========================================================

@bot.tree.command(
    name="healthstatus",
    description="View overall store health.",
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
            "ð©º **Lotus Store Health**\n\n"

            f"ð¢ Healthy: "
            f"`{overview['healthy']}`\n"

            f"ð¡ Degraded: "
            f"`{overview['degraded']}`\n"

            f"ð´ Unhealthy: "
            f"`{overview['unhealthy']}`\n"

            f"â« Disabled: "
            f"`{overview['disabled']}`\n"

            f"ðï¸ Removed: "
            f"`{overview['removed']}`"
        ),

        ephemeral=True,
    )


# =========================================================
# /RETRYSTORE
# =========================================================

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

    reason = (
        result[
            "reason"
        ]
    )

    if reason == "NOT_FOUND":

        await interaction.followup.send(
            "â Store not found.",
            ephemeral=True,
        )

        return

    if reason == "MANUAL":

        await interaction.followup.send(

            (
                "â ï¸ This store was manually disabled.\n"

                "Use `/enablestore`."
            ),

            ephemeral=True,
        )

        return

    if reason == "REMOVED":

        await interaction.followup.send(

            (
                "â ï¸ This store was removed.\n"

                "Use `/restorestore`."
            ),

            ephemeral=True,
        )

        return

    if result[
        "success"
    ]:

        await interaction.followup.send(

            (
                "ð¢ Store responded successfully.\n"

                "Health restored and monitoring enabled."
            ),

            ephemeral=True,
        )

    else:

        await interaction.followup.send(

            (
                "ð´ Store health check failed.\n"

                f"`{reason}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /SCANSHOPIFY
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
                "â ï¸ No active stores "
                "were successfully scanned."
            ),

            ephemeral=True,
        )

        return

    lines = []

    for result in results:

        families = (
            result.get(
                "families",
                {}
            )
        )

        lines.append(

            (
                f"**{result['store']}**\n"

                f"Currency: "
                f"`{result.get('currency', 'Unknown')}`\n"

                f"Relevant TCG Products: "
                f"`{result['seen']}`\n"

                f"New: "
                f"`{result['new']}`\n"

                f"Updated: "
                f"`{result['updated']}`\n"

                f"Events: "
                f"`{result['events']}`\n"

                f"Flickers: "
                f"`{result['flickers']}`\n"

                f"ð Global: "
                f"`{families.get('GLOBAL_STANDARD', 0)}` | "

                f"ð¯ðµ JP: "
                f"`{families.get('JP', 0)}` | "

                f"ð°ð· KR: "
                f"`{families.get('KR', 0)}` | "

                f"ð¨ð³ CN: "
                f"`{families.get('CN', 0)}` | "

                f"â Unknown: "
                f"`{families.get('UNKNOWN', 0)}`"

                + (

                    "\nð± Initial baseline"

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
        )[:1900],

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

    data = (
        get_shopify_monitor_status()
    )

    worker_online = (

        bot.shopify_monitor_task
        is not None

        and

        not bot.shopify_monitor_task.done()
    )

    embed = discord.Embed(

        title="ðï¸ Lotus Shopify Monitor",

        description=(

            f"**Worker:** "
            f"{'â Online' if worker_online else 'â Offline'}\n"

            f"**Running:** "
            f"{'â' if data['running'] else 'â'}\n"

            f"**Stores Scanned:** "
            f"{data['stores_scanned']}\n"

            f"**TCG Products Seen:** "
            f"{data['products_seen']}\n"

            f"**Events:** "
            f"{data['events_created']}\n"

            f"**Flickers:** "
            f"{data['flickers_detected']}\n"

            f"**Recovered Stores:** "
            f"{data['stores_recovered']}\n\n"

            "**Product Families:**\n"

            f"ð Global: "
            f"`{data.get('global_family_products', 0)}`\n"

            f"ð¯ðµ Japanese: "
            f"`{data.get('jp_family_products', 0)}`\n"

            f"ð°ð· Korean: "
            f"`{data.get('kr_family_products', 0)}`\n"

            f"ð¨ð³ Chinese: "
            f"`{data.get('cn_family_products', 0)}`\n"

            f"â Unknown: "
            f"`{data.get('unknown_family_products', 0)}`\n\n"

            "**Routing:**\n"

            "ð¡ Discovery/Page â Early Page Detection\n"

            "ð£ Preorders â Preorder Alerts\n"

            "ð¢ Stock/Restocks â Shopify Drops\n"

            "ð¥ Prices â Deals"
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
            or "None â"
        ),

        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# POKEMON CENTER STATUS
# =========================================================

@bot.tree.command(
    name="pokemoncenterstatus",
    description="View PokÃ©mon Center queue status.",
)
async def pokemoncenterstatus(
    interaction,
):

    data = (
        get_pokemon_center_status()
    )

    worker_online = (

        bot.pokemon_center_task
        is not None

        and

        not bot.pokemon_center_task.done()
    )

    embed = discord.Embed(

        title="â¡ PokÃ©mon Center Queue Intelligence",

        description=(

            f"**Worker:** "
            f"{'â Online' if worker_online else 'â Offline'}\n"

            f"**Running:** "
            f"{'â' if data['running'] else 'â'}\n"

            f"**Regions Checked:** "
            f"{data['regions_checked']}\n"

            f"**Queues Active:** "
            f"{data['queues_active']}\n"

            f"**Events Created:** "
            f"{data['events_created']}"
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
            or "None â"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /SCANPOKEMONCENTER
# =========================================================

@bot.tree.command(
    name="scanpokemoncenter",
    description="Run a PokÃ©mon Center queue scan now.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def scanpokemoncenter(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        results = (
            await scan_pokemon_center()
        )

        if not results:

            await interaction.followup.send(

                (
                    "â ï¸ PokÃ©mon Center scan "
                    "returned no successful regions."
                ),

                ephemeral=True,
            )

            return

        lines = []

        for result in results:

            lines.append(

                (
                    f"**{result['region']}**\n"

                    f"HTTP: "
                    f"`{result['http_status']}`\n"

                    f"Queue: "
                    f"{'ð¨ ACTIVE' if result['queue_active'] else 'â Clear'}"
                )
            )

        await interaction.followup.send(

            (
                "\n\n".join(
                    lines
                )
            )[:1900],

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â PokÃ©mon Center scan failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /ADDPOKEMONPRODUCT
# =========================================================

@bot.tree.command(
    name="addpokemonproduct",
    description="Add a PokÃ©mon Center product to Lotus monitoring.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def addpokemonproduct(
    interaction,
    url: str,
    region: str = "US",
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        product, created = (
            await add_pokemon_product(
                url,
                region,
            )
        )

        await interaction.followup.send(

            (
                f"{'â Added' if created else 'â Reactivated'} "
                "**PokÃ©mon Center product**\n\n"

                f"**ID:** "
                f"`{product.id}`\n"

                f"**Code:** "
                f"`{product.product_code or 'Unknown'}`\n"

                f"**Region:** "
                f"`{product.region}`\n"

                f"**Scan Status:** "
                f"`{product.scan_status}`\n"

                f"**URL:** "
                f"{product.url}"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Product could not be added.\n\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /POKEMONPRODUCTS
# =========================================================

@bot.tree.command(
    name="pokemonproducts",
    description="View known PokÃ©mon Center products.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def pokemonproducts(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    products = (
        await list_pokemon_products(
            active_only=False
        )
    )

    if not products:

        await interaction.followup.send(
            "No PokÃ©mon Center products registered.",
            ephemeral=True,
        )

        return

    lines = []

    for product in products:

        if product.last_state:

            state_text = (
                product.last_state
            )

        elif (
            product.scan_status
            in (
                "BLOCKED",
                "ERROR",
                "PARSE_ERROR",
            )
        ):

            state_text = (
                "UNKNOWN"
            )

        else:

            state_text = (
                "NOT_SCANNED"
            )

        scan_icon = {

            "SUCCESS":
                "â",

            "BLOCKED":
                "ð«",

            "PARSE_ERROR":
                "ð§©",

            "ERROR":
                "â ï¸",

        }.get(
            product.scan_status,
            "âª",
        )

        lines.append(

            (
                f"**ID {product.id} â "
                f"{product.product_code or 'Unknown'}**\n"

                f"{'ð¢ Active' if product.active else 'â« Removed'}\n"

                f"Region: "
                f"`{product.region}`\n"

                f"State: "
                f"`{state_text}`\n"

                f"Scan: "
                f"{scan_icon} "
                f"`{product.scan_status}`\n"

                f"HTTP: "
                f"`{product.last_http_status or 'None'}`\n"

                f"Blocks: "
                f"`{product.block_count}`\n"

                f"Title: "
                f"{product.title or 'Unknown'}"
            )
        )

    await interaction.followup.send(

        (
            "\n\n".join(
                lines
            )
        )[:1900],

        ephemeral=True,
    )


# =========================================================
# /REMOVEPOKEMONPRODUCT
# =========================================================

@bot.tree.command(
    name="removepokemonproduct",
    description="Stop monitoring a PokÃ©mon Center product.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def removepokemonproduct(
    interaction,
    product_id: int,
):

    product = (
        await remove_pokemon_product(
            product_id
        )
    )

    if product is None:

        await interaction.response.send_message(
            "â Product ID not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            "â« PokÃ©mon Center product removed "
            "from active monitoring.\n"

            f"`{product.product_code or product.id}`"
        ),

        ephemeral=True,
    )


# =========================================================
# /RESTOREPOKEMONPRODUCT
# =========================================================

@bot.tree.command(
    name="restorepokemonproduct",
    description="Restore a removed PokÃ©mon Center product.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def restorepokemonproduct(
    interaction,
    product_id: int,
):

    product = (
        await restore_pokemon_product(
            product_id
        )
    )

    if product is None:

        await interaction.response.send_message(
            "â Product ID not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            "â»ï¸ PokÃ©mon Center product restored.\n"

            f"`{product.product_code or product.id}`"
        ),

        ephemeral=True,
    )


# =========================================================
# /DISCOVERPOKEMONPRODUCTS
# =========================================================

@bot.tree.command(
    name="discoverpokemonproducts",
    description="Run PokÃ©mon Center indexed product discovery.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def discoverpokemonproducts(
    interaction,
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        count = (
            await discover_pokemon_products()
        )

        await interaction.followup.send(

            (
                "ð PokÃ©mon Center discovery complete.\n\n"

                f"**New products added:** "
                f"`{count}`"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Product discovery failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /SCANPOKEMONPRODUCTS
# =========================================================

@bot.tree.command(
    name="scanpokemonproducts",
    description="Scan known PokÃ©mon Center products now.",
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

    try:

        result = (
            await scan_pokemon_center_products()
        )

        await interaction.followup.send(

            (
                "â¡ **PokÃ©mon Center Product Scan**\n\n"

                f"Known Products: "
                f"`{result['known']}`\n"

                f"Actually Checked: "
                f"`{result['checked']}`\n"

                f"Successful Parses: "
                f"`{result['successful']}`\n"

                f"Parse Errors: "
                f"`{result['parse_errors']}`\n"

                f"Blocked: "
                f"`{result['blocked']}`\n"

                f"Skipped Due to Backoff: "
                f"`{result['skipped']}`\n"

                f"Events: "
                f"`{result['events']}`"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "â Product scan failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /POKEMONPRODUCTSTATUS
# =========================================================

@bot.tree.command(
    name="pokemonproductstatus",
    description="View PokÃ©mon Center product intelligence.",
)
async def pokemonproductstatus(
    interaction,
):

    data = (
        get_pokemon_product_status()
    )

    worker_online = (

        bot.pokemon_product_task
        is not None

        and

        not bot.pokemon_product_task.done()
    )

    embed = discord.Embed(

        title=(
            "â¡ PokÃ©mon Center Product Intelligence"
        ),

        description=(

            f"**Worker:** "
            f"{'â Online' if worker_online else 'â Offline'}\n"

            f"**Running:** "
            f"{'â' if data['running'] else 'â'}\n"

            f"**Known Products:** "
            f"{data['known_products']}\n"

            f"**Actually Checked:** "
            f"{data['products_checked']}\n"

            f"**Successful Parses:** "
            f"{data['successful_products']}\n"

            f"**Parse Errors:** "
            f"{data['parse_errors']}\n"

            f"**Blocked:** "
            f"{data['blocked_products']}\n"

            f"**Events:** "
            f"{data['events_created']}"
        ),
    )

    embed.add_field(
        name="Last Error",
        value=(
            data[
                "last_error"
            ]
            or "None â"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /POKEMONBURST
# =========================================================

@bot.tree.command(
    name="pokemonburst",
    description="Temporarily enable fast PokÃ©mon Center monitoring.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def pokemonburst(
    interaction,
    region: str = "US",
):

    try:

        success = (
            await trigger_product_burst(
                region
            )
        )

        if not success:

            await interaction.response.send_message(

                (
                    "â ï¸ Burst mode could not be enabled "
                    "because Redis is unavailable."
                ),

                ephemeral=True,
            )

            return

        await interaction.response.send_message(

            (
                "â¡ PokÃ©mon Center burst monitoring "
                f"enabled for **{region.upper()}** "
                "for 5 minutes."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.response.send_message(

            (
                "â Burst mode failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

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
@app_commands.choices(
    game=GAME_CHOICES,
    event=EVENT_CHOICES,
    family=PRODUCT_FAMILY_CHOICES,
)
async def simulateproduct(
    interaction,
    game: app_commands.Choice[str],
    event: app_commands.Choice[str],
    family: app_commands.Choice[str],
):

    await interaction.response.defer(
        ephemeral=True
    )

    queue_event = (
        event.value.startswith(
            "QUEUE_"
        )
    )

    source_type = (

        "queue"

        if queue_event

        else "simulation"
    )

    if queue_event:

        family_value = (
            "UNKNOWN"
        )

    else:

        family_value = (
            family.value
        )

    language_map = {

        "GLOBAL_STANDARD":
            "English",

        "JP":
            "Japanese",

        "KR":
            "Korean",

        "CN":
            "Simplified Chinese",

        "UNKNOWN":
            "Unknown",
    }

    product_event = ProductEvent(

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

            "PokÃ©mon Center Test"

            if queue_event

            else (
                f"{game.value} "
                f"{PRODUCT_FAMILY_LABELS.get(family_value, family_value)} "
                "Test Booster Box"
            )
        ),

        store_name=(
            "PokÃ©mon Center"
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

        old_price=None,

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

        language=(
            language_map.get(
                family_value,
                "Unknown",
            )
        ),

        product_type=(
            "Virtual Queue"
            if queue_event
            else "Booster Box"
        ),

        product_category=(
            "UNKNOWN"
            if queue_event
            else "SEALED"
        ),

        product_family=(
            family_value
        ),

        source_type=(
            source_type
        ),

        retailer_key=(
            "pokemon_center"
            if queue_event
            else "simulation"
        ),

        image_url=None,

        variant_id=None,

        purchase_limit=None,

        cart_base_url=None,
    )

    result = (
        await process_product_event(
            product_event
        )
    )

    await interaction.followup.send(

        (
            "ð§ª Event submitted.\n\n"

            f"Event: "
            f"`{event.value}`\n"

            f"Game: "
            f"`{product_event.game}`\n"

            f"Category: "
            f"`{product_event.product_category}`\n"

            f"Family: "
            f"`{product_event.product_family}`\n"

            f"Database: "
            f"{'â' if result['database_saved'] else 'â'}\n"

            f"Redis: "
            f"{'â' if result['redis_saved'] else 'â'}"
        ),

        ephemeral=True,
    )


# =========================================================
# /TESTALERT
# =========================================================

@bot.tree.command(
    name="testalert",
    description="Send a test alert through routing.",
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
                "â Unknown alert type.\n\n"

                "Examples:\n"

                "`major_retailer`\n"

                "`shopify`\n"

                "`preorder`\n"

                "`page_live`\n"

                "`deal`\n"

                "`international`\n"

                "`inventory_flicker`\n"

                "`release_radar`\n"

                "`pokemon_queue`"
            ),

            ephemeral=True,
        )

        return

    channel_id = (
        safe_int(
            CHANNEL_MAP.get(
                config[
                    "channel_variable"
                ]
            )
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
            "â Alert channel not found.",
            ephemeral=True,
        )

        return

    await channel.send(

        embed=discord.Embed(

            title="ð§ª LOTUS TEST ALERT",

            description=(

                f"**{game.value} Test Product**\n"

                f"Route: "
                f"`{alert_type}`\n"

                "Version: `1.0.4`"
            ),
        )
    )

    await interaction.followup.send(

        (
            f"â Test alert sent "
            f"to {channel.mention}."
        ),

        ephemeral=True,
    )


# =========================================================
# /STATUS
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

    health = (
        await get_health_overview()
    )

    event_worker_online = (

        bot.event_worker_task
        is not None

        and

        not bot.event_worker_task.done()
    )

    shopify_online = (

        bot.shopify_monitor_task
        is not None

        and

        not bot.shopify_monitor_task.done()
    )

    pokemon_queue_online = (

        bot.pokemon_center_task
        is not None

        and

        not bot.pokemon_center_task.done()
    )

    pokemon_products_online = (

        bot.pokemon_product_task
        is not None

        and

        not bot.pokemon_product_task.done()
    )

    universal_status = (
        get_universal_retailer_monitor_status()
    )

    embed = discord.Embed(

        title="ð¢ Lotus Tracker Bot Status",

        description=(

            f"**PostgreSQL / Alembic:** "
            f"{'â' if bot.database_ready else 'â'}\n"

            f"**Redis:** "
            f"{'â' if bot.redis_ready else 'â'}\n"

            f"**Event Worker:** "
            f"{'â' if event_worker_online else 'â'}\n"

            f"**Shopify Monitor:** "
            f"{'â' if shopify_online else 'â'}\n"

            f"**PokÃ©mon Queue Monitor:** "
            f"{'â' if pokemon_queue_online else 'â'}\n"

            f"**PokÃ©mon Product Monitor:** "
            f"{'â' if pokemon_products_online else 'â'}\n"

            "**Universal Retailer Monitor:** "
            "ð§ª Manual Validation Only\n\n"

            "**Strict TCG Classification:** â\n"

            "**Category Preferences:** â\n"

            "**Singles Filtering:** â\n"

            "**Product Family Detection:** â\n"

            "**English / JP / KR / CN Preferences:** â\n"

            "**Game + Category + Family Audience:** â\n"

            "**Currency-Independent Family Detection:** â\n"

            "**Regional MSRP Isolation:** â\n"

            "**Exact Product MSRP:** â\n"

            "**Product Type MSRP:** â\n"

            "**Game Default MSRP:** â\n"

            "**Cross-Currency MSRP:** â\n"

            "**30-Day Pricing History:** â\n"

            "**Deal Score:** â\n"

            "**Scalper Protection:** â\n"

            "**Smart Quick Cart:** â\n"

            "**Native Currency:** â\n"

            "**USD Conversion:** â\n"

            "**Early Page Routing:** â\n"

            "**Product Images:** â\n"

            "**Affiliate Pipeline:** â\n"

            "**Store Self-Healing:** â\n"

            "**Inventory Flicker:** â\n"

            "**Universal Retailer Foundation:** â\n"

            f"**Universal Adapters Loaded:** "
            f"{'â' if universal_status.get('adapters_loaded') else 'âª'}\n\n"

            f"**Healthy Stores:** "
            f"{health['healthy']}\n"

            f"**Degraded Stores:** "
            f"{health['degraded']}\n"

            f"**Unhealthy Stores:** "
            f"{health['unhealthy']}\n"

            f"**Redis Queue:** "
            f"`{queue}`\n\n"

            "**Version:** `1.0.4`"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# GLOBAL ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error,
):

    original = getattr(
        error,
        "original",
        error,
    )

    if isinstance(
        error,
        app_commands.MissingPermissions,
    ):

        message = (
            "â You do not have permission "
            "to use this command."
        )

    else:

        print(
            (
                "APP COMMAND ERROR | "
                f"{type(original).__name__}: "
                f"{original}"
            )
        )

        message = (

            "â Command failed.\n\n"

            f"`{type(original).__name__}: "
            f"{original}`"
        )

    try:

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

    except Exception as send_error:

        print(
            (
                "APP ERROR RESPONSE FAILED | "
                f"{type(send_error).__name__}: "
                f"{send_error}"
            )
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