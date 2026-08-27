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
# Version 1.0.2
#
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
#
# UNKNOWN is intentionally excluded from MSRP administration.
# If Lotus cannot determine the product family, it should
# not guess a trusted MSRP.
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
        name="High — Official / Verified",
        value="HIGH",
    ),

    app_commands.Choice(
        name="Medium — Reliable Reference",
        value="MEDIUM",
    ),

    app_commands.Choice(
        name="Low — Unconfirmed Reference",
        value="LOW",
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
        "🌎 English / Global Standard",

    "JP":
        "🇯🇵 Japanese",

    "KR":
        "🇰🇷 Korean",

    "CN":
        "🇨🇳 Simplified Chinese",

    "UNKNOWN":
        "❓ Unknown / Unclassified",
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

                    # -------------------------------------
                    # Initialize family defaults for newly
                    # followed game.
                    # -------------------------------------

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
        "✅ **Game preferences updated.**\n\n"
    )

    if current_games:

        message += "\n".join(

            f"• {game}"

            for game in sorted(
                current_games
            )
        )

    else:

        message += (
            "No games currently selected."
        )

    message += (
        "\n\n🌎 Use `/familyprefs` to choose "
        "English, Japanese, Korean, and Chinese alerts."
    )

    if errors:

        message += (
            "\n\n⚠️ **Warnings:**\n"
        )

        message += "\n".join(

            f"• {error}"

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

        # =================================================
        # DATABASE
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
        # EVENT WORKER
        # =================================================

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

        # =================================================
        # SHOPIFY MONITOR
        # =================================================

        self.shopify_monitor_task = (
            asyncio.create_task(
                run_shopify_monitor()
            )
        )

        print(
            "Lotus Shopify Monitor task created."
        )

        # =================================================
        # POKEMON CENTER QUEUE
        # =================================================

        self.pokemon_center_task = (
            asyncio.create_task(
                run_pokemon_center_monitor()
            )
        )

        print(
            "Pokémon Center Queue Monitor task created."
        )

        # =================================================
        # POKEMON CENTER PRODUCTS
        # =================================================

        self.pokemon_product_task = (
            asyncio.create_task(
                run_pokemon_center_product_monitor()
            )
        )

        print(
            "Pokémon Center Product Monitor task created."
        )

        # =================================================
        # COMMAND SYNC
        # =================================================

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
        "Version: 1.0.2"
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
                "TCG drops worldwide 🌎"
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
            "🏓 **Lotus is online.**\n"

            f"Latency: "
            f"`{round(bot.latency * 1000)}ms`\n"

            "**Version:** `1.0.2`"
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

        title="🎴 Choose Your TCGs",

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

            "❌ Roles channel not found.",

            ephemeral=True,
        )

        return

    embed = discord.Embed(

        title="🎴 Choose Your Games",

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
            f"✅ Selector posted "
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

            "❌ Use this inside the server.",

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
                f"❌ You are not currently following "
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

            f"⚙️ **{game.value} Product Preferences**\n\n"

            f"{'✅' if sealed else '❌'} "
            "Sealed Products\n"

            f"{'✅' if singles else '❌'} "
            "Singles\n"

            f"{'✅' if accessories else '❌'} "
            "Accessories\n"

            f"{'✅' if unknown else '❌'} "
            "Unknown Product Types\n\n"

            "💾 Saved to Lotus.\n\n"

            "Use `/familyprefs` to separately choose "
            "English, Japanese, Korean, and Chinese products."
        )

        if role_errors:

            message += (
                "\n\n⚠️ **Role warnings:**\n"
            )

            message += "\n".join(

                f"• {error}"

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
                "❌ Lotus cannot manage its alert roles.\n\n"

                "Give the Lotus bot role **Manage Roles** "
                "and place it above the Lotus alert roles."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "❌ Preferences could not be saved.\n\n"

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
            f"⚙️ **{game.value} Product Preferences**\n\n"

            f"{'✅' if preferences['SEALED'] else '❌'} "
            "Sealed Products\n"

            f"{'✅' if preferences['SINGLE'] else '❌'} "
            "Singles\n"

            f"{'✅' if preferences['ACCESSORY'] else '❌'} "
            "Accessories\n"

            f"{'✅' if preferences['UNKNOWN'] else '❌'} "
            "Unknown Product Types"
        ),

        ephemeral=True,
    )


# =========================================================
# /FAMILYPREFS
#
# These are PER GAME.
#
# Example:
#
# One Piece:
# English ✅
# Japanese ✅
#
# Pokemon:
# English ✅
# Japanese ❌
#
# Family != store currency.
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

            "❌ Use this inside the server.",

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
                f"❌ You are not currently following "
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

            f"🌎 **{game.value} Product Family Preferences**\n\n"

            f"{'✅' if saved['GLOBAL_STANDARD'] else '❌'} "
            "English / Global Standard\n"

            f"{'✅' if saved['JP'] else '❌'} "
            "Japanese\n"

            f"{'✅' if saved['KR'] else '❌'} "
            "Korean\n"

            f"{'✅' if saved['CN'] else '❌'} "
            "Simplified Chinese\n"

            f"{'✅' if saved['UNKNOWN'] else '❌'} "
            "Unknown / Unclassified\n\n"

            "💾 Saved to Lotus.\n\n"

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
                "❌ Family preferences could not be saved.\n\n"

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
                f"🌎 **{game.value} Product Family Preferences**\n\n"

                f"{'✅' if preferences['GLOBAL_STANDARD'] else '❌'} "
                "English / Global Standard\n"

                f"{'✅' if preferences['JP'] else '❌'} "
                "Japanese\n"

                f"{'✅' if preferences['KR'] else '❌'} "
                "Korean\n"

                f"{'✅' if preferences['CN'] else '❌'} "
                "Simplified Chinese\n"

                f"{'✅' if preferences['UNKNOWN'] else '❌'} "
                "Unknown / Unclassified\n\n"

                "Product family is based on the actual product, "
                "not the currency the retailer charges."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.response.send_message(

            (
                "❌ Family preferences could not be loaded.\n\n"

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

        # -------------------------------------------------
        # Initialize family defaults for people who
        # currently follow this game.
        # -------------------------------------------------

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
                f"✅ **{game.value} alert preferences initialized.**\n\n"

                f"Category members initialized: "
                f"`{result['members']}`\n"

                f"Family members initialized: "
                f"`{initialized_family_members}`\n\n"

                "**Default category preferences:**\n"

                "✅ Sealed Products\n"

                "❌ Singles\n"

                "❌ Accessories\n"

                "✅ Unknown Product Types\n\n"

                "**Default family preferences:**\n"

                "✅ English / Global Standard\n"

                "❌ Japanese\n"

                "❌ Korean\n"

                "❌ Simplified Chinese\n"

                "❌ Unknown / Unclassified\n\n"

                "Members can customize these using "
                "`/alertprefs` and `/familyprefs`."
            ),

            ephemeral=True,
        )

    except discord.Forbidden:

        await interaction.followup.send(

            (
                "❌ Lotus needs **Manage Roles**.\n\n"

                "Also make sure the Lotus bot Discord role "
                "is above its alert roles."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "❌ Alert preference setup failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# MSRP ADMINISTRATION
#
# Product family is REQUIRED.
#
# This prevents:
#
# JP box sold in USD
#
# from accidentally matching:
#
# GLOBAL_STANDARD Booster Box $119.99
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

            "❌ MSRP must be greater than 0.",

            ephemeral=True,
        )

        return

    if SessionLocal is None:

        await interaction.followup.send(

            "❌ PostgreSQL is unavailable.",

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
                "❌ A Match Value is required for "
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
                f"{'✅ MSRP rule added.' if created else '✅ MSRP rule updated.'}"
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
                "❌ MSRP rule could not be saved.\n\n"

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

            "❌ PostgreSQL is unavailable.",

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
                "❌ A Match Value is required for "
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
                    "❌ No matching MSRP rule found.\n\n"

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

            title="🏷️ Lotus MSRP Rule",

            description=(
                f"**{row.product_name}**"
            ),
        )

        embed.add_field(

            name="Game",

            value=(
                row.game
            ),

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

            value=(
                row.region
            ),

            inline=True,
        )

        embed.add_field(

            name="Confidence",

            value=(
                row.confidence
            ),

            inline=True,
        )

        embed.add_field(

            name="Source",

            value=(
                row.source
            ),

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
                "❌ MSRP lookup failed.\n\n"

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

            "❌ PostgreSQL is unavailable.",

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
                "❌ A Match Value is required for "
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
                    "❌ MSRP rule not found.\n\n"

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
                "🗑️ **MSRP rule disabled.**\n\n"

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
                "❌ MSRP rule could not be removed.\n\n"

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
            "⚪",
            "$0",
            (
                "• Major retailer alerts\n"
                "• Basic stock alerts\n"
                "• Game selection\n"
                "• Product family preferences"
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
                "• Shopify / TCG shops\n"
                "• Early page detection\n"
                "• Price drops & deals\n"
                "• International alerts\n"
                "• Pricing Intelligence\n"
                "• Advanced discovery"
            ),
        ),

        "Premium+": (
            "💎",
            "$44.99/month",
            (
                "• Everything in Premium\n"
                "• Inventory Flicker ⚡\n"
                "• Release Radar\n"
                "• Pokémon Center Queue Intelligence\n"
                "• Global intelligence\n"
                "• Scalper Protection\n"
                "• Earliest detections"
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
            "Pokémon Center Queue",
            "Premium+",
        ),
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
        )
        in features
    )

    embed = discord.Embed(

        title="⚙️ Lotus Settings",

        description=(
            f"**Subscription:** {tier}\n\n"

            "`/games` — Choose TCGs\n"
            "`/alertprefs` — Sealed / Singles / Accessories\n"
            "`/familyprefs` — English / JP / KR / CN"
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

            "❌ Profile could not be loaded.",

            ephemeral=True,
        )

        return

    games_text = (

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

    await interaction.followup.send(

        (
            "💾 **Lotus Database Profile**\n\n"

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

            "🟢 PostgreSQL is online.",

            ephemeral=True,
        )

    except Exception as error:

        bot.database_ready = False

        await interaction.followup.send(

            (
                "🔴 PostgreSQL failed.\n"

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
            "🟢 Redis is online."

            if online

            else "🔴 Redis is offline."
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

        title="📡 Lotus Event Engine",

        description=(

            f"**PostgreSQL:** "
            f"{'✅' if bot.database_ready else '❌'}\n"

            f"**Redis:** "
            f"{'✅' if bot.redis_ready else '❌'}\n"

            f"**Event Worker:** "
            f"{'✅' if worker_online else '❌'}\n"

            f"**Queue:** `{queue}`\n\n"

            "**Strict TCG Classification:** ✅\n"

            "**Product Category Filtering:** ✅\n"

            "**Product Family Detection:** ✅\n"

            "**Member Family Preferences:** ✅\n"

            "**Game + Category + Family Audience:** ✅\n"

            "**Native Currency:** ✅\n"

            "**USD Conversion:** ✅\n"

            "**Historical Pricing:** ✅\n"

            "**Hierarchical MSRP:** ✅\n"

            "**Regional MSRP Isolation:** ✅\n"

            "**Cross-Currency MSRP:** ✅\n"

            "**Deal Score:** ✅\n"

            "**Scalper Protection:** ✅\n"

            "**Smart Quick Cart:** ✅\n"

            "**Product Images:** ✅\n"

            "**Affiliate Pipeline:** ✅\n\n"

            "**Engine Version:** `1.0.2`"
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
            "🧹 **Lotus event queue cleared.**\n\n"

            f"Removed: "
            f"`{removed}` stale event(s)\n\n"

            "PostgreSQL history was preserved."
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
                f"{'✅ Added' if created else '✅ Updated'} "
                f"**{store.name}**\n"

                f"`{store.domain}`\n"

                f"Region: `{store.region}`"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "❌ Store could not be added.\n\n"

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
                f"**ID {store.id} — "
                f"{store.name}**\n"

                f"`{store.domain}`\n"

                f"Region: `{store.region or 'Unknown'}`\n"

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
            else "None ✅"
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

            "❌ Store not found.",

            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"⚫ **{store.name}** manually disabled.\n\n"

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

            "❌ Store not found.",

            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        f"🟢 **{store.name}** enabled.",

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

            "❌ Store not found.",

            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"🗑️ **{store.name}** removed "
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
            "🩺 **Lotus Store Health**\n\n"

            f"🟢 Healthy: "
            f"`{overview['healthy']}`\n"

            f"🟡 Degraded: "
            f"`{overview['degraded']}`\n"

            f"🔴 Unhealthy: "
            f"`{overview['unhealthy']}`\n"

            f"⚫ Disabled: "
            f"`{overview['disabled']}`\n"

            f"🗑️ Removed: "
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

            "❌ Store not found.",

            ephemeral=True,
        )

        return

    if reason == "MANUAL":

        await interaction.followup.send(

            (
                "⚠️ This store was manually disabled.\n"

                "Use `/enablestore`."
            ),

            ephemeral=True,
        )

        return

    if reason == "REMOVED":

        await interaction.followup.send(

            (
                "⚠️ This store was removed.\n"

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
                "🟢 Store responded successfully.\n"

                "Health restored and monitoring enabled."
            ),

            ephemeral=True,
        )

    else:

        await interaction.followup.send(

            (
                "🔴 Store health check failed.\n"

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
                "⚠️ No active stores "
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

                f"🌎 Global: "
                f"`{families.get('GLOBAL_STANDARD', 0)}` | "

                f"🇯🇵 JP: "
                f"`{families.get('JP', 0)}` | "

                f"🇰🇷 KR: "
                f"`{families.get('KR', 0)}` | "

                f"🇨🇳 CN: "
                f"`{families.get('CN', 0)}` | "

                f"❓ Unknown: "
                f"`{families.get('UNKNOWN', 0)}`"

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

        title="🛍️ Lotus Shopify Monitor",

        description=(

            f"**Worker:** "
            f"{'✅ Online' if worker_online else '❌ Offline'}\n"

            f"**Running:** "
            f"{'✅' if data['running'] else '❌'}\n"

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

            f"🌎 Global: "
            f"`{data.get('global_family_products', 0)}`\n"

            f"🇯🇵 Japanese: "
            f"`{data.get('jp_family_products', 0)}`\n"

            f"🇰🇷 Korean: "
            f"`{data.get('kr_family_products', 0)}`\n"

            f"🇨🇳 Chinese: "
            f"`{data.get('cn_family_products', 0)}`\n"

            f"❓ Unknown: "
            f"`{data.get('unknown_family_products', 0)}`\n\n"

            "**Routing:**\n"

            "📡 Discovery/Page → Early Page Detection\n"

            "🟣 Preorders → Preorder Alerts\n"

            "🟢 Stock/Restocks → Shopify Drops\n"

            "🔥 Prices → Deals"
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


# =========================================================
# POKEMON CENTER STATUS
# =========================================================

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

    worker_online = (

        bot.pokemon_center_task
        is not None

        and

        not bot.pokemon_center_task.done()
    )

    embed = discord.Embed(

        title="⚡ Pokémon Center Queue Intelligence",

        description=(

            f"**Worker:** "
            f"{'✅ Online' if worker_online else '❌ Offline'}\n"

            f"**Running:** "
            f"{'✅' if data['running'] else '❌'}\n"

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
            or "None ✅"
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
    description="Run a Pokémon Center queue scan now.",
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
                    "⚠️ Pokémon Center scan "
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
                    f"{'🚨 ACTIVE' if result['queue_active'] else '✅ Clear'}"
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
                "❌ Pokémon Center scan failed.\n"

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
    description="Add a Pokémon Center product to Lotus monitoring.",
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
                f"{'✅ Added' if created else '✅ Reactivated'} "
                "**Pokémon Center product**\n\n"

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
                "❌ Product could not be added.\n\n"

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
    description="View known Pokémon Center products.",
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

            "No Pokémon Center products registered.",

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
                "✅",

            "BLOCKED":
                "🚫",

            "PARSE_ERROR":
                "🧩",

            "ERROR":
                "⚠️",

        }.get(
            product.scan_status,
            "⚪",
        )

        lines.append(

            (
                f"**ID {product.id} — "
                f"{product.product_code or 'Unknown'}**\n"

                f"{'🟢 Active' if product.active else '⚫ Removed'}\n"

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
    description="Stop monitoring a Pokémon Center product.",
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

            "❌ Product ID not found.",

            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            "⚫ Pokémon Center product removed "
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
    description="Restore a removed Pokémon Center product.",
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

            "❌ Product ID not found.",

            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            "♻️ Pokémon Center product restored.\n"

            f"`{product.product_code or product.id}`"
        ),

        ephemeral=True,
    )


# =========================================================
# /DISCOVERPOKEMONPRODUCTS
# =========================================================

@bot.tree.command(
    name="discoverpokemonproducts",
    description="Run Pokémon Center indexed product discovery.",
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
                "🔎 Pokémon Center discovery complete.\n\n"

                f"**New products added:** "
                f"`{count}`"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "❌ Product discovery failed.\n"

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
    description="Scan known Pokémon Center products now.",
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
                "⚡ **Pokémon Center Product Scan**\n\n"

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
                "❌ Product scan failed.\n"

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
    description="View Pokémon Center product intelligence.",
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
            "⚡ Pokémon Center Product Intelligence"
        ),

        description=(

            f"**Worker:** "
            f"{'✅ Online' if worker_online else '❌ Offline'}\n"

            f"**Running:** "
            f"{'✅' if data['running'] else '❌'}\n"

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
            or "None ✅"
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
    description="Temporarily enable fast Pokémon Center monitoring.",
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
                    "⚠️ Burst mode could not be enabled "
                    "because Redis is unavailable."
                ),

                ephemeral=True,
            )

            return

        await interaction.response.send_message(

            (
                "⚡ Pokémon Center burst monitoring "
                f"enabled for **{region.upper()}** "
                "for 5 minutes."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.response.send_message(

            (
                "❌ Burst mode failed.\n"

                f"`{type(error).__name__}: "
                f"{error}`"
            ),

            ephemeral=True,
        )


# =========================================================
# /SIMULATEPRODUCT
#
# family lets us test:
#
# English box
# Japanese box
# Korean box
# Chinese box
#
# without relying on a live retailer.
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

            "Pokémon Center Test"

            if queue_event

            else (
                f"{game.value} "
                f"{PRODUCT_FAMILY_LABELS.get(family_value, family_value)} "
                "Test Booster Box"
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
            "🧪 Event submitted.\n\n"

            f"Event: "
            f"`{event.value}`\n"

            f"Game: "
            f"`{product_event.game}`\n"

            f"Category: "
            f"`{product_event.product_category}`\n"

            f"Family: "
            f"`{product_event.product_family}`\n"

            f"Database: "
            f"{'✅' if result['database_saved'] else '❌'}\n"

            f"Redis: "
            f"{'✅' if result['redis_saved'] else '❌'}"
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
                "❌ Unknown alert type.\n\n"

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

            "❌ Alert channel not found.",

            ephemeral=True,
        )

        return

    await channel.send(

        embed=discord.Embed(

            title="🧪 LOTUS TEST ALERT",

            description=(

                f"**{game.value} Test Product**\n"

                f"Route: "
                f"`{alert_type}`\n"

                "Version: `1.0.2`"
            ),
        )
    )

    await interaction.followup.send(

        (
            f"✅ Test alert sent "
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

    embed = discord.Embed(

        title="🟢 Lotus Tracker Bot Status",

        description=(

            f"**PostgreSQL / Alembic:** "
            f"{'✅' if bot.database_ready else '❌'}\n"

            f"**Redis:** "
            f"{'✅' if bot.redis_ready else '❌'}\n"

            f"**Event Worker:** "
            f"{'✅' if event_worker_online else '❌'}\n"

            f"**Shopify Monitor:** "
            f"{'✅' if shopify_online else '❌'}\n"

            f"**Pokémon Queue Monitor:** "
            f"{'✅' if pokemon_queue_online else '❌'}\n"

            f"**Pokémon Product Monitor:** "
            f"{'✅' if pokemon_products_online else '❌'}\n\n"

            "**Strict TCG Classification:** ✅\n"

            "**Category Preferences:** ✅\n"

            "**Singles Filtering:** ✅\n"

            "**Product Family Detection:** ✅\n"

            "**English / JP / KR / CN Preferences:** ✅\n"

            "**Game + Category + Family Audience:** ✅\n"

            "**Currency-Independent Family Detection:** ✅\n"

            "**Regional MSRP Isolation:** ✅\n"

            "**Exact Product MSRP:** ✅\n"

            "**Product Type MSRP:** ✅\n"

            "**Game Default MSRP:** ✅\n"

            "**Cross-Currency MSRP:** ✅\n"

            "**30-Day Pricing History:** ✅\n"

            "**Deal Score:** ✅\n"

            "**Scalper Protection:** ✅\n"

            "**Smart Quick Cart:** ✅\n"

            "**Native Currency:** ✅\n"

            "**USD Conversion:** ✅\n"

            "**Early Page Routing:** ✅\n"

            "**Product Images:** ✅\n"

            "**Affiliate Pipeline:** ✅\n"

            "**Store Self-Healing:** ✅\n"

            "**Inventory Flicker:** ✅\n\n"

            f"**Healthy Stores:** "
            f"{health['healthy']}\n"

            f"**Degraded Stores:** "
            f"{health['degraded']}\n"

            f"**Unhealthy Stores:** "
            f"{health['unhealthy']}\n"

            f"**Redis Queue:** "
            f"`{queue}`\n\n"

            "**Version:** `1.0.2`"
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

    # Unwrap CommandInvokeError where possible.

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
            "❌ You do not have permission "
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

            "❌ Command failed.\n\n"

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