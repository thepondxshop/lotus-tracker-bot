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
# TIER-AWARE ALERT-TYPE PREFERENCES
# Step 6K-2B
# =========================================================

from app.alert_preference_service import (
    ensure_alert_preference_schema,
    get_alert_preferences,
    get_available_alert_definitions,
    save_alert_preferences_for_tier,
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
    run_universal_retailer_monitor,
    scan_store,
)


# =========================================================
# UNIVERSAL RETAILER ONBOARDING
# Step 6J-3E1
# =========================================================

from app.retailer_onboarding import (
    validate_staged_retailer,
)


# =========================================================
# RETAILER PLATFORM FINGERPRINTING
# Step 6J-3E3
# =========================================================

from app.retailer_platform_detector import (
    detect_retailer_platform,
    platform_display_name,
)


# =========================================================
# OFFICIAL PRODUCT FEEDS
# Step 6J-3F12
# =========================================================

from app.affiliate_feeds import (
    probe_official_feed,
)


# =========================================================
# MAJOR RETAILER FOUNDATION
# Step 6K-1A
# =========================================================

from app.major_retailers import (
    demote_major_retailer,
    detect_major_retailer,
    ensure_major_pipeline_schema,
    get_major_pipeline_status,
    get_major_promotion_gate,
    get_major_retailer_catalog_status,
    get_major_retailer_framework_status,
    get_major_retailer_onboarding_status,
    list_major_pipeline_states,
    list_staged_major_retailers,
    probe_major_retailer,
    promote_major_retailer,
    run_major_retailer_monitor,
    run_major_retailer_pipeline_scan,
    scan_major_retailer,
    set_major_kill_switch,
    stage_major_retailer,
    validate_major_retailer,
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
# Version 1.0.6
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
        name="High \u2014 Official / Verified",
        value="HIGH",
    ),

    app_commands.Choice(
        name="Medium \u2014 Reliable Reference",
        value="MEDIUM",
    ),

    app_commands.Choice(
        name="Low \u2014 Unconfirmed Reference",
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

    app_commands.Choice(
        name="WooCommerce",
        value="woocommerce",
    ),
    app_commands.Choice(
        name="BigCommerce",
        value="bigcommerce",
    ),

    app_commands.Choice(
        name="PrestaShop",
        value="prestashop",
    ),

    app_commands.Choice(
        name="Shopware 6",
        value="shopware",
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
        "\U0001f30e English / Global Standard",

    "JP":
        "\U0001f1ef\U0001f1f5 Japanese",

    "KR":
        "\U0001f1f0\U0001f1f7 Korean",

    "CN":
        "\U0001f1e8\U0001f1f3 Simplified Chinese",

    "UNKNOWN":
        "\u2753 Unknown / Unclassified",
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
            "\u274c Use this inside the server.",
        )

    if interaction.guild is None:

        return (
            False,
            "\u274c Use this inside the server.",
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
        "\u2705 **Game preferences updated.**\n\n"
    )

    if current_games:

        message += "\n".join(

            f"\u2022 {game}"

            for game in sorted(
                current_games
            )
        )

    else:

        message += (
            "No games currently selected."
        )

    message += (
        "\n\n\U0001f30e Use `/familyprefs` to choose "
        "English, Japanese, Korean, and Chinese alerts."
    )

    if errors:

        message += (
            "\n\n\u26a0\ufe0f **Warnings:**\n"
        )

        message += "\n".join(

            f"\u2022 {error}"

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

        self.universal_retailer_monitor_task = None

        self.major_retailer_monitor_task = None


    async def setup_hook(
        self,
    ):

        self.add_view(
            PersistentGameSelectView()
        )

        try:

            await init_database()

            await ensure_alert_preference_schema()

            await ensure_major_pipeline_schema()

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
            "Pok\xe9mon Center Queue Monitor task created."
        )

        self.pokemon_product_task = (
            asyncio.create_task(
                run_pokemon_center_product_monitor()
            )
        )

        print(
            "Pok\xe9mon Center Product Monitor task created."
        )

        # Step 6I-B:
        # Start the capability-safe universal retailer monitor.
        # Only Store rows explicitly marked active are scanned.
        # DISCOVERY_PRICE_ONLY retailers can never emit stock-dependent
        # events through the Step 6I capability enforcement layer.
        self.universal_retailer_monitor_task = (
            asyncio.create_task(
                run_universal_retailer_monitor()
            )
        )

        print(
            "Lotus Universal Retailer Monitor task created "
            "(capability-safe automatic mode)."
        )

        # Step 6K-2C:
        # The major-retailer worker is safe to start because it remains idle
        # until a retailer passes validation and is explicitly promoted.
        self.major_retailer_monitor_task = (
            asyncio.create_task(
                run_major_retailer_monitor()
            )
        )

        print(
            "Lotus Major Retailer Monitor task created "
            "(promotion-gated; idle until production retailers exist)."
        )

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
        "Version: 1.0.6"
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
                "TCG drops worldwide \U0001f30e"
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
            "\U0001f3d3 **Lotus is online.**\n"

            f"Latency: "
            f"`{round(bot.latency * 1000)}ms`\n"

            "**Version:** `1.0.6`"
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

        title="\U0001f3b4 Choose Your TCGs",

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

            "\u274c Roles channel not found.",

            ephemeral=True,
        )

        return

    embed = discord.Embed(

        title="\U0001f3b4 Choose Your Games",

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
            f"\u2705 Selector posted "
            f"in {channel.mention}."
        ),

        ephemeral=True,
    )


# =========================================================
# TIER-AWARE ALERT PREFERENCE UI
# Step 6K-2B
#
# Important Discord detail:
# Slash-command boolean parameters are static for every member, so they
# cannot truly hide Premium/Premium+ options from Free/Lite members.
# The runtime Select menu below is generated after Lotus knows the member's
# tier, which means unavailable controls genuinely do not appear.
# =========================================================

PRODUCT_PREF_LABELS = {
    "SEALED": ("Sealed Products", "📦"),
    "SINGLE": ("Singles", "🃏"),
    "ACCESSORY": ("Accessories", "🧰"),
    "UNKNOWN": ("Unknown Product Types", "❓"),
}


class LotusProductPreferenceSelect(discord.ui.Select):
    def __init__(self, member: discord.Member, game: str, current: dict):
        self.owner_id = member.id
        self.game = game
        options = []
        for key, (label, emoji) in PRODUCT_PREF_LABELS.items():
            options.append(
                discord.SelectOption(
                    label=label,
                    value=key,
                    emoji=emoji,
                    default=bool(current.get(key, False)),
                )
            )
        super().__init__(
            placeholder="Product types — select everything you want...",
            min_values=0,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ These preferences belong to another member.", ephemeral=True
            )
            return
        selected = set(self.values)
        preferences = {
            key: key in selected
            for key in PRODUCT_PREF_LABELS
        }
        try:
            await save_product_preferences(
                discord_user_id=self.owner_id,
                game=self.game,
                preferences=preferences,
            )
            role_errors = await apply_member_preference_roles(
                interaction.user,
                self.game,
                preferences,
            )
            message = f"✅ **{self.game} product preferences saved.**"
            if role_errors:
                message += "\n\n⚠️ " + " • ".join(role_errors[:5])
            await interaction.response.send_message(message, ephemeral=True)
        except Exception as error:
            await interaction.response.send_message(
                f"❌ Product preferences could not be saved.\n`{type(error).__name__}: {error}`",
                ephemeral=True,
            )


class LotusAlertTypePreferenceSelect(discord.ui.Select):
    def __init__(
        self,
        member: discord.Member,
        game: str,
        tier: str,
        current: dict,
    ):
        self.owner_id = member.id
        self.game = game
        self.panel_tier = tier
        definitions = get_available_alert_definitions(tier)
        options = [
            discord.SelectOption(
                label=item.label,
                value=item.key,
                description=item.description[:100],
                emoji=item.emoji,
                default=bool(current.get(item.key, True)),
            )
            for item in definitions
        ]
        self.visible_keys = {item.key for item in definitions}
        super().__init__(
            placeholder=f"Alert notifications available on {tier}...",
            min_values=0,
            max_values=len(options),
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ These preferences belong to another member.", ephemeral=True
            )
            return
        current_tier = get_subscription(interaction.user)
        selected = set(self.values)
        try:
            await save_alert_preferences_for_tier(
                discord_user_id=self.owner_id,
                game=self.game,
                selected_keys=selected,
                tier=current_tier,
            )
            if current_tier != self.panel_tier:
                note = (
                    f"\n\nℹ️ Your tier is now **{current_tier}**. "
                    "Run `/alertprefs` again to refresh the visible options."
                )
            else:
                note = ""
            await interaction.response.send_message(
                f"✅ **{self.game} alert notifications saved.**{note}",
                ephemeral=True,
            )
        except Exception as error:
            await interaction.response.send_message(
                f"❌ Alert preferences could not be saved.\n`{type(error).__name__}: {error}`",
                ephemeral=True,
            )


class LotusAlertPreferenceView(discord.ui.View):
    def __init__(
        self,
        member: discord.Member,
        game: str,
        tier: str,
        product_preferences: dict,
        alert_preferences: dict,
    ):
        super().__init__(timeout=300)
        self.add_item(
            LotusProductPreferenceSelect(
                member,
                game,
                product_preferences,
            )
        )
        self.add_item(
            LotusAlertTypePreferenceSelect(
                member,
                game,
                tier,
                alert_preferences,
            )
        )


# =========================================================
# /ALERTPREFS
# =========================================================

@bot.tree.command(
    name="alertprefs",
    description="Choose product and notification alerts for a TCG.",
)
@app_commands.choices(game=GAME_CHOICES)
async def alertprefs(
    interaction,
    game: app_commands.Choice[str],
):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Use this inside the server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    if game.value not in get_followed_games(member):
        await interaction.followup.send(
            f"❌ You are not currently following **{game.value}**.\n\nUse `/games` first.",
            ephemeral=True,
        )
        return

    try:
        tier = get_subscription(member)
        product_preferences = await get_product_preferences(member.id, game.value)
        alert_preferences = await get_alert_preferences(member.id, game.value)
        visible = get_available_alert_definitions(tier)

        enabled_count = sum(
            1 for item in visible
            if alert_preferences.get(item.key, True)
        )

        embed = discord.Embed(
            title=f"⚙️ {game.value} Alert Preferences",
            description=(
                f"**Subscription:** {tier}\n\n"
                "Use the first menu for product types and the second menu for "
                "notification types. Changes save immediately.\n\n"
                "**Tier-aware controls:** Lotus only shows alert types included "
                "with your current subscription. Hidden higher-tier settings are "
                "still backend-blocked and are not erased if you downgrade."
            ),
        )
        embed.add_field(
            name="Notification Types",
            value=f"`{enabled_count}/{len(visible)}` currently enabled",
            inline=True,
        )
        embed.add_field(
            name="Sold-Out Alerts",
            value=(
                "✅ On" if alert_preferences.get("SOLD_OUT", True) else "❌ Off"
            ),
            inline=True,
        )
        embed.set_footer(
            text="Available + Enabled = Effective • Backend tier enforcement always applies"
        )

        await interaction.followup.send(
            embed=embed,
            view=LotusAlertPreferenceView(
                member,
                game.value,
                tier,
                product_preferences,
                alert_preferences,
            ),
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(
            f"❌ Preferences could not be loaded.\n`{type(error).__name__}: {error}`",
            ephemeral=True,
        )


# =========================================================
# /MYPREFS
# =========================================================

@bot.tree.command(
    name="myprefs",
    description="View your Lotus preferences for a TCG.",
)
@app_commands.choices(game=GAME_CHOICES)
async def myprefs(
    interaction,
    game: app_commands.Choice[str],
):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Use this inside the server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        tier = get_subscription(member)
        product_preferences = await get_product_preferences(member.id, game.value)
        alert_preferences = await get_alert_preferences(member.id, game.value)
        visible = get_available_alert_definitions(tier)

        product_lines = []
        for key, (label, _) in PRODUCT_PREF_LABELS.items():
            product_lines.append(
                f"{'✅' if product_preferences.get(key, False) else '❌'} {label}"
            )

        alert_lines = []
        for item in visible:
            alert_lines.append(
                f"{'✅' if alert_preferences.get(item.key, True) else '❌'} "
                f"{item.emoji} {item.label}"
            )

        embed = discord.Embed(
            title=f"⚙️ {game.value} Preferences",
            description=(
                f"**Subscription:** {tier}\n"
                "Only notification controls included with your tier are shown."
            ),
        )
        embed.add_field(
            name="Product Types",
            value="\n".join(product_lines),
            inline=False,
        )
        embed.add_field(
            name="Alert Notifications",
            value="\n".join(alert_lines) if alert_lines else "None available",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as error:
        await interaction.followup.send(
            f"❌ Preferences could not be loaded.\n`{type(error).__name__}: {error}`",
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

            "\u274c Use this inside the server.",

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
                f"\u274c You are not currently following "
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

            f"\U0001f30e **{game.value} Product Family Preferences**\n\n"

            f"{'\u2705' if saved['GLOBAL_STANDARD'] else '\u274c'} "
            "English / Global Standard\n"

            f"{'\u2705' if saved['JP'] else '\u274c'} "
            "Japanese\n"

            f"{'\u2705' if saved['KR'] else '\u274c'} "
            "Korean\n"

            f"{'\u2705' if saved['CN'] else '\u274c'} "
            "Simplified Chinese\n"

            f"{'\u2705' if saved['UNKNOWN'] else '\u274c'} "
            "Unknown / Unclassified\n\n"

            "\U0001f4be Saved to Lotus.\n\n"

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
                "\u274c Family preferences could not be saved.\n\n"

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
                f"\U0001f30e **{game.value} Product Family Preferences**\n\n"

                f"{'\u2705' if preferences['GLOBAL_STANDARD'] else '\u274c'} "
                "English / Global Standard\n"

                f"{'\u2705' if preferences['JP'] else '\u274c'} "
                "Japanese\n"

                f"{'\u2705' if preferences['KR'] else '\u274c'} "
                "Korean\n"

                f"{'\u2705' if preferences['CN'] else '\u274c'} "
                "Simplified Chinese\n"

                f"{'\u2705' if preferences['UNKNOWN'] else '\u274c'} "
                "Unknown / Unclassified\n\n"

                "Product family is based on the actual product, "
                "not the currency the retailer charges."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.response.send_message(

            (
                "\u274c Family preferences could not be loaded.\n\n"

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
                f"\u2705 **{game.value} alert preferences initialized.**\n\n"

                f"Category members initialized: "
                f"`{result['members']}`\n"

                f"Family members initialized: "
                f"`{initialized_family_members}`\n\n"

                "**Default category preferences:**\n"

                "\u2705 Sealed Products\n"

                "\u274c Singles\n"

                "\u274c Accessories\n"

                "\u2705 Unknown Product Types\n\n"

                "**Default family preferences:**\n"

                "\u2705 English / Global Standard\n"

                "\u274c Japanese\n"

                "\u274c Korean\n"

                "\u274c Simplified Chinese\n"

                "\u274c Unknown / Unclassified\n\n"

                "Members can customize these using "
                "`/alertprefs` and `/familyprefs`."
            ),

            ephemeral=True,
        )

    except discord.Forbidden:

        await interaction.followup.send(

            (
                "\u274c Lotus needs **Manage Roles**.\n\n"

                "Also make sure the Lotus bot Discord role "
                "is above its alert roles."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "\u274c Alert preference setup failed.\n"

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

            "\u274c MSRP must be greater than 0.",

            ephemeral=True,
        )

        return

    if SessionLocal is None:

        await interaction.followup.send(

            "\u274c PostgreSQL is unavailable.",

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
                "\u274c A Match Value is required for "
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
                f"{'\u2705 MSRP rule added.' if created else '\u2705 MSRP rule updated.'}"
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
                "\u274c MSRP rule could not be saved.\n\n"

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

            "\u274c PostgreSQL is unavailable.",

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
                "\u274c A Match Value is required for "
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
                    "\u274c No matching MSRP rule found.\n\n"

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

            title="\U0001f3f7\ufe0f Lotus MSRP Rule",

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
                "\u274c MSRP lookup failed.\n\n"

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

            "\u274c PostgreSQL is unavailable.",

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
                "\u274c A Match Value is required for "
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
                    "\u274c MSRP rule not found.\n\n"

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
                "\U0001f5d1\ufe0f **MSRP rule disabled.**\n\n"

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
                "\u274c MSRP rule could not be removed.\n\n"

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
            "\u26aa",
            "$0",
            (
                "\u2022 Major retailer alerts\n"
                "\u2022 Basic stock alerts\n"
                "\u2022 Game selection\n"
                "\u2022 Product family preferences"
            ),
        ),

        "Lite": (
            "\U0001f33f",
            "$1.99/month",
            (
                "\u2022 Everything in Free\n"
                "\u2022 Preorder alerts\n"
                "\u2022 Preorder calendar\n"
                "\u2022 Priority support\n"
                "\u2022 14-day free trial"
            ),
        ),

        "Premium": (
            "\U0001f451",
            "$17.99/month",
            (
                "\u2022 Everything in Lite\n"
                "\u2022 Shopify / TCG shops\n"
                "\u2022 Early page detection\n"
                "\u2022 Price drops & deals\n"
                "\u2022 International alerts\n"
                "\u2022 Pricing Intelligence\n"
                "\u2022 Advanced discovery"
            ),
        ),

        "Premium+": (
            "\U0001f48e",
            "$44.99/month",
            (
                "\u2022 Everything in Premium\n"
                "\u2022 Inventory Flicker \u26a1\n"
                "\u2022 Release Radar\n"
                "\u2022 Pok\xe9mon Center Queue Intelligence\n"
                "\u2022 Global intelligence\n"
                "\u2022 Scalper Protection\n"
                "\u2022 Earliest detections"
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
                f"\u2022 {game}"
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
            "Pok\xe9mon Center Queue",
            "Premium+",
        ),
    ]

    feature_text = "\n".join(

        (
            "\u2705"

            if tier_allows(
                tier,
                required
            )

            else "\U0001f512"
        )

        + f" {name}"

        for (
            name,
            required,
        )
        in features
    )

    embed = discord.Embed(

        title="\u2699\ufe0f Lotus Settings",

        description=(
            f"**Subscription:** {tier}\n\n"

            "`/games` \u2014 Choose TCGs\n"
            "`/alertprefs` \u2014 Sealed / Singles / Accessories\n"
            "`/familyprefs` \u2014 English / JP / KR / CN"
        ),
    )

    embed.add_field(

        name="Games",

        value=(

            "\n".join(
                f"\u2705 {game}"
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

            "\u274c Profile could not be loaded.",

            ephemeral=True,
        )

        return

    games_text = (

        "\n".join(

            f"\u2022 {game}"

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
            "\U0001f4be **Lotus Database Profile**\n\n"

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

            "\U0001f7e2 PostgreSQL is online.",

            ephemeral=True,
        )

    except Exception as error:

        bot.database_ready = False

        await interaction.followup.send(

            (
                "\U0001f534 PostgreSQL failed.\n"

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
            "\U0001f7e2 Redis is online."

            if online

            else "\U0001f534 Redis is offline."
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

        title="\U0001f4e1 Lotus Event Engine",

        description=(

            f"**PostgreSQL:** "
            f"{'\u2705' if bot.database_ready else '\u274c'}\n"

            f"**Redis:** "
            f"{'\u2705' if bot.redis_ready else '\u274c'}\n"

            f"**Event Worker:** "
            f"{'\u2705' if worker_online else '\u274c'}\n"

            f"**Queue:** `{queue}`\n\n"

            "**Strict TCG Classification:** \u2705\n"

            "**Product Category Filtering:** \u2705\n"

            "**Product Family Detection:** \u2705\n"

            "**Member Family Preferences:** \u2705\n"

            "**Game + Category + Family Audience:** \u2705\n"

            "**Native Currency:** \u2705\n"

            "**USD Conversion:** \u2705\n"

            "**Historical Pricing:** \u2705\n"

            "**Hierarchical MSRP:** \u2705\n"

            "**Regional MSRP Isolation:** \u2705\n"

            "**Cross-Currency MSRP:** \u2705\n"

            "**Deal Score:** \u2705\n"

            "**Scalper Protection:** \u2705\n"

            "**Smart Quick Cart:** \u2705\n"

            "**Product Images:** \u2705\n"

            "**Affiliate Pipeline:** \u2705\n"

            "**Universal Retailer Foundation:** \u2705\n"

            "**Auto Platform Fingerprinting:** \u2705\n\n"

            "**Engine Version:** `1.0.6`"
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
            "\U0001f9f9 **Lotus event queue cleared.**\n\n"

            f"Removed: "
            f"`{removed}` stale event(s)\n\n"

            "PostgreSQL history was preserved."
        ),

        ephemeral=True,
    )


# =========================================================
# UNIVERSAL RETAILER MANAGEMENT
# PonDeX Trackers
# Version 1.0.6
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
# /DETECTRETAILER
# Step 6J-3E3 — Automatic Platform Fingerprinting Diagnostic
# =========================================================
#
# Read-only diagnostic command. No Store row is created or changed.
# This lets us inspect Lotus's platform decision before onboarding.
# =========================================================

@bot.tree.command(
    name="detectretailer",
    description="Detect a retailer storefront platform without adding it.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def detectretailer(
    interaction,
    domain: str,
):

    await interaction.response.defer(
        ephemeral=True
    )

    clean_domain = (
        normalize_retailer_domain(
            domain
        )
    )

    if not clean_domain:

        await interaction.followup.send(
            "❌ Retailer domain is required.",
            ephemeral=True,
        )

        return

    try:

        detection = (
            await detect_retailer_platform(
                clean_domain
            )
        )

    except asyncio.CancelledError:

        raise

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Retailer platform detection failed.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )

        return

    detected_label = (
        platform_display_name(
            detection.platform
        )
    )

    confidence_icon = {
        "HIGH": "🟢",
        "MEDIUM": "🟡",
        "LOW": "🟠",
        "UNKNOWN": "🔴",
    }.get(
        detection.confidence,
        "⚪",
    )

    if detection.platform == "shopify":

        title = "🛍️ Shopify Storefront Detected"
        action_text = (
            "This store belongs in Lotus's dedicated Shopify pipeline. "
            "Use `/addshopifystore` rather than `/addretailer`."
        )

    elif detection.auto_stage_allowed:

        title = "🧠 Retailer Platform Detected"
        action_text = (
            "✅ This fingerprint is strong enough for automatic staging. "
            "You can use `/addretailer` without choosing a platform."
        )

    else:

        title = "⚠️ Retailer Platform Needs Review"
        action_text = (
            "Lotus will not automatically stage this domain at the current "
            "confidence level. Review the fingerprint before using a manual "
            "platform override."
        )

    embed = discord.Embed(
        title=title,
        description=(
            f"Platform fingerprint completed for `{clean_domain}`."
        ),
    )

    embed.add_field(
        name="Detected Platform",
        value=f"`{detected_label}`",
        inline=True,
    )

    embed.add_field(
        name="Confidence",
        value=(
            f"{confidence_icon} "
            f"`{detection.confidence}`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Detection Score",
        value=f"`{detection.score}`",
        inline=True,
    )

    if detection.homepage_status is not None:

        homepage_value = (
            f"HTTP `{detection.homepage_status}`"
        )

        if detection.homepage_url:
            homepage_value += (
                f"\n`{detection.homepage_url[:850]}`"
            )

        embed.add_field(
            name="Homepage Probe",
            value=homepage_value,
            inline=False,
        )

    ranked_scores = sorted(
        detection.scores.items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    )

    score_lines = []

    for candidate, score in ranked_scores:

        score_lines.append(
            f"**{platform_display_name(candidate)}:** `{score}`"
        )

    embed.add_field(
        name="Candidate Scores",
        value=(
            "\n".join(score_lines)
            or "No platform scores."
        ),
        inline=False,
    )

    signal_lines = [
        f"• {signal}"
        for signal in detection.signals[:6]
    ]

    embed.add_field(
        name="Strongest Signals",
        value=(
            "\n".join(signal_lines)
            if signal_lines
            else "No decisive storefront signals were found."
        ),
        inline=False,
    )

    if detection.errors:

        error_preview = "\n".join(
            f"• `{error[:220]}`"
            for error in detection.errors[:4]
        )

        embed.add_field(
            name="Probe Notes",
            value=error_preview,
            inline=False,
        )

    embed.add_field(
        name="Next Step",
        value=action_text,
        inline=False,
    )

    embed.set_footer(
        text=(
            "Lotus Universal Retailer Foundation • "
            "6J-3F Shopware 6 Platform Fingerprinting"
        )
    )

    await interaction.followup.send(
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# /FEEDSTATUS
# Step 6J-3F12 — Official Product Feed Diagnostic
# =========================================================

@bot.tree.command(
    name="feedstatus",
    description="Check an official retailer product-feed integration.",
)
@app_commands.checks.has_permissions(administrator=True)
async def feedstatus(
    interaction,
    store_id: int,
):
    await interaction.response.defer(ephemeral=True)

    if SessionLocal is None:
        await interaction.followup.send(
            "❌ PostgreSQL is unavailable.",
            ephemeral=True,
        )
        return

    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Store)
                .where(Store.id == store_id)
                .limit(1)
            )
            store = result.scalar_one_or_none()

        if store is None:
            await interaction.followup.send(
                "❌ Retailer Store ID not found.",
                ephemeral=True,
            )
            return

        probe = await probe_official_feed(
            store.domain,
            store_name=store.name,
        )

        if not probe.get("supported"):
            embed = discord.Embed(
                title="ℹ️ No Official Feed Integration",
                description=(
                    f"Lotus does not currently have an approved official "
                    f"product-feed source configured for **{store.name}**."
                ),
            )
            embed.add_field(name="Store ID", value=f"`{store.id}`", inline=True)
            embed.add_field(
                name="Platform",
                value=f"`{platform_display_name(store.platform)}`",
                inline=True,
            )
            embed.add_field(name="Domain", value=f"`{store.domain}`", inline=False)
            embed.set_footer(
                text="Lotus Universal Retailer Foundation • 6J-3F12 Official Feeds"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        configured = bool(probe.get("api_key_configured"))
        catalog_found = bool(probe.get("merchant_catalog_found"))
        sample_products = int(probe.get("sample_products", 0) or 0)
        sample_price_hits = int(probe.get("sample_price_hits", 0) or 0)
        feed_ready = configured and catalog_found and sample_products > 0

        embed = discord.Embed(
            title=(
                "✅ Official Product Feed Ready"
                if feed_ready
                else "⚠️ Official Product Feed Needs Setup"
            ),
            description=(
                f"Official-feed diagnostic completed for **{store.name}**. "
                "This check is read-only and cannot activate the retailer or "
                "send product alerts."
            ),
        )

        embed.add_field(name="Store ID", value=f"`{store.id}`", inline=True)
        embed.add_field(
            name="Storefront",
            value=f"`{platform_display_name(store.platform)}`",
            inline=True,
        )
        embed.add_field(
            name="Provider",
            value=f"`{probe.get('provider') or 'Unknown'}`",
            inline=True,
        )
        embed.add_field(name="Domain", value=f"`{store.domain}`", inline=False)
        embed.add_field(
            name="Feed Enabled",
            value="✅ Yes" if probe.get("enabled") else "❌ No",
            inline=True,
        )
        embed.add_field(
            name="API Key",
            value="✅ Configured" if configured else "❌ Missing",
            inline=True,
        )
        embed.add_field(
            name="Merchant Catalog",
            value="✅ Found" if catalog_found else "❌ Not Found",
            inline=True,
        )
        embed.add_field(
            name="Merchant ID",
            value=f"`{probe.get('merchant_id') or 'AUTO / UNKNOWN'}`",
            inline=True,
        )
        embed.add_field(
            name="Sample Products",
            value=f"`{sample_products}`",
            inline=True,
        )
        embed.add_field(
            name="Sample Price Hits",
            value=f"`{sample_price_hits}`",
            inline=True,
        )
        embed.add_field(
            name="Stock Capability",
            value=(
                "✅ Verified"
                if probe.get("stock_capability_verified")
                else "🔒 Unverified — stock alerts capability-gated"
            ),
            inline=False,
        )

        last_error = probe.get("last_error")
        if last_error:
            embed.add_field(
                name="Feed Note / Error",
                value=f"`{str(last_error)[:900]}`",
                inline=False,
            )

        if feed_ready:
            next_step = (
                f"Run `/scanretailer store_id:{store.id}` for a forced-silent "
                "feed-backed baseline/review. Keep the retailer inactive until "
                "catalog and price coverage are verified."
            )
        elif not configured:
            next_step = (
                "Add `LINKCONNECTOR_API_KEY` in Railway after your LinkConnector "
                "account and Miniature Market campaign are approved, then rerun "
                f"`/feedstatus store_id:{store.id}`."
            )
        else:
            next_step = (
                "Confirm that the Miniature Market campaign/product catalog is "
                "available to this LinkConnector account. You may also provide "
                "`LINKCONNECTOR_MINIATURE_MARKET_MERCHANT_ID` if known, then "
                f"rerun `/feedstatus store_id:{store.id}`."
            )

        embed.add_field(name="Next Step", value=next_step, inline=False)
        embed.set_footer(
            text="Lotus Universal Retailer Foundation • 6J-3F12 Official Feed Diagnostic"
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    except asyncio.CancelledError:
        raise
    except Exception as error:
        await interaction.followup.send(
            (
                "❌ Official-feed diagnostic failed.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# /MAJORSTATUS
# Step 6K-2C — Major Retailer Production Event Pipeline
# =========================================================

@bot.tree.command(
    name="majorstatus",
    description="View the dedicated major-retailer framework status.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorstatus(interaction):
    status = get_major_retailer_framework_status()
    catalog = get_major_retailer_catalog_status()
    onboarding = await get_major_retailer_onboarding_status()
    pipeline = await get_major_pipeline_status()

    definitions = int(status.get("definitions_loaded", 0) or 0)
    adapters = int(status.get("adapters_registered", 0) or 0)
    production_ready = int(pipeline.get("production_retailers", 0) or 0)
    staged = int(onboarding.get("staged_major_retailers", 0) or 0)

    embed = discord.Embed(
        title="🏬 Major Retailer Foundation",
        description=(
            "Lotus now has safe auto-onboarding plus a persistent production event pipeline. "
            "Major retailers remain silent until they pass validation and are explicitly promoted."
        ),
    )
    embed.add_field(name="Framework", value="✅ READY", inline=True)
    embed.add_field(name="Version", value=f"`{status.get('version', '1.0.6')}`", inline=True)
    embed.add_field(name="Milestone", value=f"`{status.get('step', '6K-2C')}`", inline=True)
    embed.add_field(name="Retailer Definitions", value=f"`{definitions}`", inline=True)
    embed.add_field(name="Adapters Registered", value=f"`{adapters}`", inline=True)
    embed.add_field(name="Production Ready", value=f"`{production_ready}`", inline=True)
    embed.add_field(name="Database-Staged", value=f"`{staged}`", inline=True)
    embed.add_field(
        name="Auto Detection",
        value="✅ Domain + storefront fingerprint + adapter-family recommendation",
        inline=False,
    )
    embed.add_field(
        name="Autonomous Shop Discovery",
        value="🔒 Not enabled yet — candidate discovery from release/community intelligence comes later",
        inline=False,
    )
    embed.add_field(
        name="Background Monitoring",
        value="✅ Promotion-gated • idle unless a retailer is in PRODUCTION",
        inline=True,
    )
    embed.add_field(
        name="Stock Safety",
        value="✅ Unknown availability stays unknown",
        inline=True,
    )
    embed.add_field(
        name="Inventory Separation",
        value="✅ Online stock and local-store stock remain separate capabilities",
        inline=False,
    )
    embed.add_field(
        name="Target",
        value="⏸️ Parked — Redsky CAPTCHA path retired; official feed/partner path required later",
        inline=False,
    )
    embed.add_field(
        name="Next Adapter",
        value=(
            "✅ **Walmart 6K-3A validation adapter installed**\n"
            "🔒 Production blocked until online-stock validation passes\n"
            "➡️ Next after Walmart validation: **Best Buy**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Global Kill Switch",
        value="🛑 ON" if pipeline.get("global_kill_switch") else "✅ OFF",
        inline=True,
    )
    embed.add_field(
        name="Promotion Rule",
        value="Two clean persistent validations + health probe + staged store + unchanged adapter signature",
        inline=False,
    )
    embed.set_footer(text="Lotus Major Retailer Foundation • 6K-2C Production Pipeline")

    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# /MAJORRETAILERS
# Step 6K-2A — Planned + Database-Staged Major Retailers
# =========================================================

@bot.tree.command(
    name="majorretailers",
    description="List planned and staged major retailers.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorretailers(interaction):
    catalog = get_major_retailer_catalog_status()
    try:
        staged_rows = await list_staged_major_retailers()
    except Exception:
        staged_rows = []
    try:
        pipeline_rows = await list_major_pipeline_states()
    except Exception:
        pipeline_rows = []
    runtime_by_key = {str(row.get("retailer_key")): row for row in pipeline_rows}

    lines = []
    for item in catalog:
        adapter_ready = bool(item.get("adapter_registered"))
        runtime = runtime_by_key.get(str(item.get("key"))) or {}
        runtime_mode = str(runtime.get("mode") or "").upper()
        if str(item.get("key")) == "target":
            state = "⏸️ Parked — Official Source Required"
        elif runtime_mode == "PRODUCTION" and not runtime.get("kill_switch"):
            state = "🟢 Production"
        elif runtime.get("kill_switch"):
            state = "🛑 Kill Switch"
        elif adapter_ready:
            state = "🟡 Adapter / Validation Pending"
        else:
            state = "⚪ Planned"

        lines.append(
            f"**{item.get('display_name')}** — `{item.get('domain')}`\n"
            f"{state} • Region `{item.get('region')}`"
        )

    embed = discord.Embed(
        title="🏪 Lotus Major Retailers",
        description="\n\n".join(lines) if lines else "No retailer definitions loaded.",
    )

    if staged_rows:
        staged_lines = []
        for row in staged_rows:
            staged_lines.append(
                f"**ID {row.get('store_id')} — {row.get('name')}** • `{row.get('domain')}` • "
                f"`{row.get('region')}` • {'🟢 Active' if row.get('active') else '⚫ Inactive'}"
            )

        chunks = []
        current = ""
        for line in staged_lines:
            candidate = line if not current else current + "\n" + line
            if len(candidate) > 900:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)

        for index, chunk in enumerate(chunks[:4], start=1):
            label = "Database-Staged Major Retailers" if index == 1 else f"Database-Staged ({index})"
            embed.add_field(name=label, value=chunk, inline=False)

    embed.add_field(
        name="Quick Add",
        value=(
            "Use `/detectmajorretailer domain:<domain>` for a read-only fingerprint, then "
            "`/addmajorretailer name:<name> domain:<domain> region:<region>` to stage it inactive."
        ),
        inline=False,
    )
    embed.add_field(
        name="Safety",
        value=(
            "Detection/staging never activates a retailer. Each retailer still needs an approved adapter/feed, "
            "controlled silent validation, and explicit production enablement."
        ),
        inline=False,
    )
    embed.set_footer(text="Lotus Major Retailer Foundation • 6K-2C Production Pipeline")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# /DETECTMAJORRETAILER
# Step 6K-2A — Read-Only Major Store Fingerprinting
# =========================================================

@bot.tree.command(
    name="detectmajorretailer",
    description="Fingerprint a major retailer domain and recommend its Lotus adapter strategy.",
)
@app_commands.checks.has_permissions(administrator=True)
async def detectmajorretailer(
    interaction,
    domain: str,
    region: str = "US",
):
    await interaction.response.defer(ephemeral=True)
    try:
        result = await detect_major_retailer(domain, region=region)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        await interaction.followup.send(
            f"❌ Major retailer detection failed.\n\n`{type(error).__name__}: {str(error)[:850]}`",
            ephemeral=True,
        )
        return

    known = bool(result.get("known_retailer"))
    adapter = bool(result.get("adapter_registered"))
    reusable = bool(result.get("reusable_family"))

    if adapter:
        title = "✅ Major Retailer Adapter Recognized"
    elif known:
        title = "🧠 Known Major Retailer Detected"
    elif reusable:
        title = "🧩 Reusable Major Retailer Family Detected"
    else:
        title = "🔎 Major Retailer Needs Adapter Review"

    embed = discord.Embed(
        title=title,
        description=(
            "Read-only detection completed. No Store row was created and no monitoring or alerts were enabled."
        ),
    )
    embed.add_field(name="Domain", value=f"`{result.get('domain')}`", inline=False)
    embed.add_field(
        name="Catalog Match",
        value=(
            f"✅ {result.get('display_name')} (`{result.get('retailer_key')}`)"
            if known
            else "⚪ New / not in built-in catalog"
        ),
        inline=False,
    )
    embed.add_field(
        name="Underlying Platform",
        value=f"`{result.get('underlying_platform_label') or 'Unknown'}`",
        inline=True,
    )
    embed.add_field(
        name="Fingerprint",
        value=f"`{result.get('platform_confidence')}` • Score `{result.get('platform_score', 0)}`",
        inline=True,
    )
    embed.add_field(
        name="Homepage Probe",
        value=(
            f"HTTP `{result.get('homepage_status')}`"
            if result.get("homepage_status") is not None
            else "`UNKNOWN`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Recommended Strategy",
        value=f"`{result.get('recommended_strategy')}`",
        inline=False,
    )
    embed.add_field(
        name="Adapter Family",
        value=(
            f"{'✅ Reusable' if reusable else '🛠️ Custom'} — "
            f"**{result.get('adapter_family_name')}** (`{result.get('adapter_family_key')}`)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Dedicated Adapter",
        value="✅ Registered" if adapter else "⚪ Not registered",
        inline=True,
    )
    embed.add_field(
        name="Affiliate Provider",
        value=f"`{result.get('affiliate_provider') or 'UNKNOWN / NOT CONFIGURED'}`",
        inline=True,
    )

    signals = [str(x) for x in (result.get("platform_signals") or [])[:6]]
    if signals:
        embed.add_field(
            name="Fingerprint Signals",
            value="\n".join(f"• {signal}" for signal in signals)[:1000],
            inline=False,
        )
    errors = [str(x) for x in (result.get("platform_errors") or [])[:4]]
    if errors:
        embed.add_field(
            name="Probe Notes",
            value="\n".join(f"• {error}" for error in errors)[:1000],
            inline=False,
        )

    embed.add_field(
        name="Next Step",
        value=str(result.get("next_step") or "Review the detection result.")[:1000],
        inline=False,
    )
    embed.add_field(
        name="Safety",
        value="🔒 Read-only detection — no database write, background monitoring, or Discord product alert.",
        inline=False,
    )
    embed.set_footer(text="Lotus Major Retailer Foundation • 6K-2A Detection")
    await interaction.followup.send(embed=embed, ephemeral=True)


# =========================================================
# /ADDMAJORRETAILER
# Step 6K-2A — Detect + Persist Inactive Major Retailer
# =========================================================

@bot.tree.command(
    name="addmajorretailer",
    description="Auto-detect and stage a major retailer inactive for adapter review.",
)
@app_commands.checks.has_permissions(administrator=True)
async def addmajorretailer(
    interaction,
    name: str,
    domain: str,
    region: str = "US",
):
    await interaction.response.defer(ephemeral=True)
    try:
        result = await stage_major_retailer(name=name, domain=domain, region=region)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        await interaction.followup.send(
            f"❌ Major retailer could not be staged.\n\n`{type(error).__name__}: {str(error)[:850]}`",
            ephemeral=True,
        )
        return

    detection = dict(result.get("detection") or {})
    created = bool(result.get("created"))
    adapter = bool(detection.get("adapter_registered"))

    embed = discord.Embed(
        title=(
            "✅ Major Retailer Staged"
            if created
            else "⚠️ Retailer Already Registered"
        ),
        description=(
            f"**{result.get('store_name')}** is stored in Lotus as an inactive major retailer. "
            "Detection does not grant monitoring capability or send alerts."
            if created
            else "Lotus found an existing Store row for this domain, so no duplicate was created."
        ),
    )
    embed.add_field(name="Store ID", value=f"`{result.get('store_id')}`", inline=True)
    embed.add_field(name="Region", value=f"`{result.get('region')}`", inline=True)
    embed.add_field(name="Monitoring", value="🔒 Inactive", inline=True)
    embed.add_field(name="Domain", value=f"`{result.get('domain')}`", inline=False)
    embed.add_field(
        name="Catalog Match",
        value=(
            f"✅ {detection.get('display_name')} (`{detection.get('retailer_key')}`)"
            if detection.get("known_retailer")
            else "⚪ New major retailer"
        ),
        inline=False,
    )
    embed.add_field(
        name="Underlying Platform",
        value=f"`{detection.get('underlying_platform_label') or 'Unknown'}`",
        inline=True,
    )
    embed.add_field(
        name="Adapter Strategy",
        value=f"`{detection.get('recommended_strategy') or 'REVIEW'}`",
        inline=True,
    )
    embed.add_field(
        name="Reusable Family",
        value=(
            f"✅ `{detection.get('adapter_family_key')}`"
            if detection.get("reusable_family")
            else f"🛠️ `{detection.get('adapter_family_key') or 'CUSTOM_MAJOR'}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Dedicated Adapter",
        value="✅ Registered" if adapter else "⚪ Pending",
        inline=True,
    )
    embed.add_field(name="Discord Alerts", value="🔇 Disabled", inline=True)
    embed.add_field(name="Database Persistence", value="✅ Staging row only", inline=True)
    embed.add_field(
        name="Next Step",
        value=str(detection.get("next_step") or "Build and silently validate an adapter.")[:1000],
        inline=False,
    )
    embed.add_field(
        name="Safety",
        value=(
            "No product polling starts from this command. New stores remain inactive until a trustworthy "
            "adapter/feed is installed, silently validated, and explicitly enabled."
        ),
        inline=False,
    )
    embed.set_footer(text="Lotus Major Retailer Foundation • 6K-2A Safe Staging")
    await interaction.followup.send(embed=embed, ephemeral=True)


# =========================================================
# /MAJORPROBE
# Step 6K-1A — Read-Only Adapter Probe
# =========================================================

@bot.tree.command(
    name="majorprobe",
    description="Run a read-only health probe for a dedicated major-retailer adapter.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorprobe(interaction, retailer: str):
    await interaction.response.defer(ephemeral=True)
    result = await probe_major_retailer(retailer)

    if result.get("error") == "UNKNOWN_RETAILER":
        await interaction.followup.send(
            "❌ Unknown major retailer key. Use `/majorretailers` to view planned retailers.",
            ephemeral=True,
        )
        return

    if result.get("error") == "ADAPTER_NOT_REGISTERED":
        embed = discord.Embed(
            title="⚪ Major Retailer Adapter Pending",
            description=(
                f"**{result.get('display_name') or retailer}** is registered in "
                "the 6K framework, but its retailer-specific adapter has not "
                "been installed yet."
            ),
        )
        embed.add_field(name="Retailer Key", value=f"`{result.get('retailer_key')}`", inline=True)
        embed.add_field(name="Domain", value=f"`{result.get('domain')}`", inline=True)
        embed.add_field(name="Network Requests", value="`0`", inline=True)
        embed.add_field(name="Next Step", value="Build and silently validate the retailer adapter.", inline=False)
        embed.set_footer(text="Lotus Major Retailer Foundation • 6K-2A")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    probe = result.get("probe") or {}
    capabilities = result.get("capabilities") or {}
    embed = discord.Embed(
        title=(
            "✅ Major Retailer Probe Passed"
            if result.get("success")
            else "⚠️ Major Retailer Probe Needs Review"
        ),
        description=f"Read-only probe completed for **{result.get('display_name') or retailer}**.",
    )
    embed.add_field(name="Retailer Key", value=f"`{result.get('retailer_key')}`", inline=True)
    embed.add_field(name="Domain", value=f"`{result.get('domain')}`", inline=True)
    embed.add_field(name="Confidence", value=f"`{probe.get('confidence') or 'UNKNOWN'}`", inline=True)
    embed.add_field(
        name="Capability",
        value=f"`{capabilities.get('availability_capability') or 'DISCOVERY_ONLY'}`",
        inline=True,
    )
    embed.add_field(
        name="Online Availability",
        value="✅ Verified" if capabilities.get("online_availability") else "🔒 Not verified",
        inline=True,
    )
    embed.add_field(
        name="Local Store Availability",
        value="✅ Verified" if capabilities.get("local_store_availability") else "🔒 Separate / not verified",
        inline=True,
    )
    if result.get("error"):
        embed.add_field(name="Error", value=f"`{str(result.get('error'))[:900]}`", inline=False)
    diagnostics = dict(result.get("diagnostics") or {})
    if diagnostics:
        probe_lines = []
        for key in (
            "integration_state",
            "source_strategy",
            "discovery_source",
            "browse_requests",
            "browse_http_ok",
            "candidate_links",
            "last_non_success_status",
            "last_error",
        ):
            if key not in diagnostics:
                continue
            value = diagnostics.get(key)
            probe_lines.append(
                f"{key.replace('_', ' ').title()}: `{str(value)[:160]}`"
            )
        if probe_lines:
            embed.add_field(
                name="Adapter Diagnostics",
                value="\n".join(probe_lines)[:1000],
                inline=False,
            )
    embed.set_footer(text="Lotus Major Retailer Foundation • 6K-3A")
    await interaction.followup.send(embed=embed, ephemeral=True)


# =========================================================
# /MAJORSCAN
# Step 6K-1C2 — Controlled Silent Major-Retailer Scan
# =========================================================

@bot.tree.command(
    name="majorscan",
    description="Run a controlled silent scan for a dedicated major-retailer adapter.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorscan(
    interaction,
    retailer: str,
    limit: app_commands.Range[int, 1, 40] = 20,
):
    await interaction.response.defer(ephemeral=True)
    result = await scan_major_retailer(
        retailer,
        limit=int(limit),
        suppress_events=True,
    )

    if result.get("error") == "UNKNOWN_RETAILER":
        await interaction.followup.send(
            "❌ Unknown major retailer key. Use `/majorretailers` to view planned retailers.",
            ephemeral=True,
        )
        return

    if result.get("error") == "ADAPTER_NOT_REGISTERED":
        embed = discord.Embed(
            title="⚪ Major Retailer Adapter Pending",
            description=(
                f"**{result.get('display_name') or retailer}** is registered in "
                "the major-retailer framework, but its adapter has not been installed yet."
            ),
        )
        embed.add_field(name="Retailer Key", value=f"`{result.get('retailer_key')}`", inline=True)
        embed.add_field(name="Domain", value=f"`{result.get('domain')}`", inline=True)
        embed.add_field(name="Discord Alerts", value="🔇 Disabled", inline=True)
        embed.set_footer(text="Lotus Major Retailer Foundation • 6K-2A")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if not result.get("success"):
        embed = discord.Embed(
            title="❌ Major Retailer Silent Scan Failed",
            description=f"Controlled scan failed for **{result.get('display_name') or retailer}**.",
        )
        embed.add_field(name="Retailer", value=f"`{result.get('retailer_key') or retailer}`", inline=True)
        embed.add_field(name="Reason", value=f"`{str(result.get('error') or 'UNKNOWN')[:900]}`", inline=False)
        embed.add_field(name="Safety", value="🔇 No database writes or Discord product alerts were allowed.", inline=False)
        embed.set_footer(text="Lotus Major Retailer Foundation • 6K-2A")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    products = list(result.get("normalized_products") or [])
    diagnostics = dict(result.get("diagnostics") or {})

    price_hits = sum(1 for item in products if item.get("price") is not None)
    known_stock = sum(
        1
        for item in products
        if bool((item.get("platform_data") or {}).get("availability_known"))
    )
    in_stock = sum(
        1
        for item in products
        if (item.get("platform_data") or {}).get("availability_state") == "IN_STOCK"
    )
    out_stock = sum(
        1
        for item in products
        if (item.get("platform_data") or {}).get("availability_state") == "OUT_OF_STOCK"
    )
    preorders = sum(
        1
        for item in products
        if (
            (item.get("platform_data") or {}).get("availability_state") == "PREORDER"
            or (item.get("platform_data") or {}).get("lifecycle_state") == "PREORDER"
        )
    )

    embed = discord.Embed(
        title="🏬 Major Retailer Silent Scan",
        description=(
            f"Controlled scan completed for **{result.get('display_name') or retailer}**. "
            "This milestone validates adapter output only; nothing was persisted or sent as a product alert."
        ),
    )
    embed.add_field(name="Retailer", value=f"`{result.get('retailer_key')}`", inline=True)
    embed.add_field(name="Region", value=f"`{result.get('region') or 'US'}`", inline=True)
    embed.add_field(name="Production", value="🔒 Disabled", inline=True)
    embed.add_field(name="Raw Products", value=f"`{result.get('products', 0)}`", inline=True)
    embed.add_field(name="Accepted", value=f"`{result.get('accepted', 0)}`", inline=True)
    embed.add_field(name="Rejected", value=f"`{result.get('rejected', 0)}`", inline=True)
    embed.add_field(name="Price Hits", value=f"`{price_hits}`", inline=True)
    embed.add_field(name="Known Online Stock", value=f"`{known_stock}`", inline=True)
    embed.add_field(name="Unknown Online Stock", value=f"`{max(len(products) - known_stock, 0)}`", inline=True)
    embed.add_field(name="In Stock", value=f"`{in_stock}`", inline=True)
    embed.add_field(name="Out of Stock", value=f"`{out_stock}`", inline=True)
    embed.add_field(name="Preorders", value=f"`{preorders}`", inline=True)

    # Future-proof adapter diagnostics. Each retailer owns its diagnostic
    # vocabulary; render values generically instead of hardcoding old
    # Target/Redsky fields into every retailer scan.
    preferred_diag_keys = [
        "integration_state",
        "source_strategy",
        "discovery_source",
        "browse_requests",
        "browse_http_ok",
        "browse_http_403",
        "browse_http_429",
        "browse_http_5xx",
        "browse_challenge_pages",
        "candidate_links",
        "detail_requests",
        "detail_http_ok",
        "detail_http_403",
        "detail_http_429",
        "detail_http_5xx",
        "detail_challenge_pages",
        "direct_walmart_accepted",
        "third_party_rejected",
        "unknown_seller_rejected",
        "unsupported_games_rejected",
        "price_hits",
        "missing_prices",
        "preorder_hits",
        "coming_soon_hits",
        "release_date_hints",
        "availability_hint_add_to_cart",
        "availability_hint_out_of_stock",
        "availability_hint_preorder",
        "availability_hint_unknown",
        "rate_limit_retries",
        "rate_limit_backoff_seconds",
        "last_non_success_status",
        "last_error",
        "seller_samples",
        "source_pages_ok",
    ]

    ordered_keys = []
    for key in preferred_diag_keys:
        if key in diagnostics and key not in ordered_keys:
            ordered_keys.append(key)
    for key in sorted(diagnostics.keys()):
        if key not in ordered_keys:
            ordered_keys.append(key)

    diag_lines = []
    for key in ordered_keys:
        value = diagnostics.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            rendered = ", ".join(
                f"{k}={v}"
                for k, v in list(value.items())[:8]
            )
        elif isinstance(value, (list, tuple, set)):
            rendered = ", ".join(str(item) for item in list(value)[:8])
        else:
            rendered = str(value)
        rendered = rendered.replace("`", "'")
        label = str(key).replace("_", " ").title()
        diag_lines.append(
            f"{label}: `{rendered[:760]}`"
        )

    # Discord limits every embed field value to 1024 characters.
    # Keep diagnostics readable and split them across bounded fields rather than
    # allowing a successful scan to fail while Discord renders the response.
    diagnostic_chunks = []
    current_chunk = []
    current_length = 0

    for line in diag_lines:
        line = str(line or "")
        # A single diagnostic line should never consume the entire Discord field.
        if len(line) > 960:
            line = line[:957] + "..."

        added_length = len(line) + (1 if current_chunk else 0)
        if current_chunk and current_length + added_length > 1000:
            diagnostic_chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += added_length

    if current_chunk:
        diagnostic_chunks.append("\n".join(current_chunk))

    # Leave room under Discord's 25-field embed limit for Sample + Safety.
    diagnostic_chunks = diagnostic_chunks[:6]
    for index, chunk in enumerate(diagnostic_chunks):
        field_name = (
            "Adapter Diagnostics"
            if index == 0
            else f"Adapter Diagnostics ({index + 1})"
        )
        embed.add_field(name=field_name, value=chunk or "No diagnostics.", inline=False)

    if products:
        sample_lines = []
        for item in products[:5]:
            pdata = item.get("platform_data") or {}
            price = item.get("price")
            price_text = f"${price:.2f}" if isinstance(price, (int, float)) else "price ?"
            stock = pdata.get("availability_state") or "UNKNOWN"
            sample_lines.append(
                f"• **{str(item.get('title') or 'Unknown')[:120]}**\n"
                f"  `{item.get('external_product_id')}` • `{price_text}` • `{stock}`"
            )
        embed.add_field(name="Sample", value="\n".join(sample_lines)[:1000], inline=False)

    embed.add_field(
        name="Safety",
        value="🔇 Forced silent validation — no database persistence and no Discord product alerts.",
        inline=False,
    )
    embed.set_footer(text="Lotus Major Retailer Foundation • 6K-3A Controlled Scan")
    await interaction.followup.send(embed=embed, ephemeral=True)


# =========================================================
# STEP 6K-2C — MAJOR RETAILER PRODUCTION EVENT PIPELINE
# =========================================================

def _major_gate_text(gate: dict) -> str:
    if gate.get("ready"):
        return "✅ READY FOR EXPLICIT PRODUCTION PROMOTION"
    reasons = list(gate.get("reasons") or [])
    if not reasons:
        return "⚠️ Not ready"
    return "\n".join(f"• `{reason}`" for reason in reasons[:12])


@bot.tree.command(
    name="majorpipeline",
    description="View major-retailer production pipeline and promotion state.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorpipeline(
    interaction,
    retailer: str = "",
):
    await interaction.response.defer(ephemeral=True)
    status = await get_major_pipeline_status()

    if retailer.strip():
        gate = await get_major_promotion_gate(retailer)
        rows = await list_major_pipeline_states()
        key = str(gate.get("retailer_key") or retailer)
        row = next((item for item in rows if item.get("retailer_key") == key), {})

        embed = discord.Embed(
            title="🛡️ Major Retailer Production Gate",
            description=f"Runtime state for **{gate.get('display_name') or key}**.",
        )
        embed.add_field(name="Retailer Key", value=f"`{key}`", inline=True)
        embed.add_field(name="Mode", value=f"`{row.get('mode') or 'VALIDATION'}`", inline=True)
        embed.add_field(
            name="Kill Switch",
            value="🛑 ON" if row.get("kill_switch") else "✅ OFF",
            inline=True,
        )
        embed.add_field(
            name="Baseline",
            value="✅ Ready" if gate.get("baseline_ready") else "⚪ Not ready",
            inline=True,
        )
        embed.add_field(
            name="Validation Passes",
            value=(
                f"`{gate.get('validation_passes', 0)}/"
                f"{gate.get('required_validation_passes', 2)}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Staged Store",
            value=(f"`ID {gate.get('staged_store_id')}`" if gate.get("staged_store_id") else "⚪ Not staged"),
            inline=True,
        )
        embed.add_field(name="Promotion Gate", value=_major_gate_text(gate)[:1024], inline=False)
        embed.add_field(
            name="Last Scan",
            value=(
                f"Accepted `{row.get('last_accepted', 0)}` • "
                f"Rejected `{row.get('last_rejected', 0)}` • "
                f"Candidate Events `{row.get('last_candidate_events', 0)}` • "
                f"Emitted `{row.get('last_emitted_events', 0)}`"
            ),
            inline=False,
        )
        if row.get("last_error"):
            embed.add_field(name="Last Note / Error", value=f"`{str(row.get('last_error'))[:950]}`", inline=False)
        embed.set_footer(text="Lotus Major Retailer Pipeline • 6K-2C • v1.0.6")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    rows = await list_major_pipeline_states()
    production = [
        row for row in rows
        if str(row.get("mode") or "").upper() == "PRODUCTION"
        and not row.get("kill_switch")
    ]
    embed = discord.Embed(
        title="🛡️ Major Retailer Production Pipeline",
        description=(
            "The worker is promotion-gated. Validation may persist safe baselines, "
            "but product events are queued only for explicitly promoted retailers."
        ),
    )
    embed.add_field(name="Pipeline", value="✅ READY", inline=True)
    embed.add_field(name="Version", value=f"`{status.get('version', '1.0.6')}`", inline=True)
    embed.add_field(name="Milestone", value=f"`{status.get('step', '6K-2C')}`", inline=True)
    embed.add_field(
        name="Global Kill Switch",
        value="🛑 ON" if status.get("global_kill_switch") else "✅ OFF",
        inline=True,
    )
    embed.add_field(name="Production Retailers", value=f"`{len(production)}`", inline=True)
    embed.add_field(name="Runtime Rows", value=f"`{len(rows)}`", inline=True)
    embed.add_field(name="Pending Event Outbox", value=f"`{status.get('pending_outbox_events', 0)}`", inline=True)
    embed.add_field(
        name="Safety Invariants",
        value=(
            "✅ Missing products never imply sold out\n"
            "✅ UNKNOWN stock never emits stock lifecycle events\n"
            "✅ Online/local inventory remain separate\n"
            "✅ Adapter changes force revalidation\n"
            "✅ 3 consecutive production failures auto-demote"
        ),
        inline=False,
    )
    if rows:
        lines = []
        for row in rows[:15]:
            mode = str(row.get("mode") or "VALIDATION").upper()
            icon = "🟢" if mode == "PRODUCTION" and not row.get("kill_switch") else "🟡"
            if row.get("kill_switch"):
                icon = "🛑"
            lines.append(
                f"{icon} `{row.get('retailer_key')}` • {mode} • "
                f"validation `{row.get('validation_passes', 0)}/2`"
            )
        embed.add_field(name="Runtime Retailers", value="\n".join(lines)[:1024], inline=False)
    embed.set_footer(text="Use /majorvalidate before /majorpromote")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="majorvalidate",
    description="Persist a silent major-retailer baseline/validation scan. Never sends product alerts.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorvalidate(
    interaction,
    retailer: str,
    limit: app_commands.Range[int, 1, 40] = 20,
):
    await interaction.response.defer(ephemeral=True)
    result = await validate_major_retailer(retailer, limit=int(limit))

    if not result.get("success"):
        runtime = result.get("runtime") or {}
        embed = discord.Embed(
            title="⚠️ Major Retailer Validation Blocked",
            description=f"Validation did not pass for `{result.get('retailer_key') or retailer}`.",
        )
        embed.add_field(name="Reason", value=f"`{str(result.get('error') or 'UNKNOWN')[:950]}`", inline=False)
        if runtime:
            embed.add_field(
                name="Validation State",
                value=f"Passes `{runtime.get('validation_passes', 0)}/2` • Baseline `{runtime.get('baseline_ready', False)}`",
                inline=False,
            )
        probe = result.get("probe") or {}
        if probe:
            embed.add_field(
                name="Health Probe",
                value="✅ Passed" if probe.get("success") else "❌ Did not pass",
                inline=True,
            )
        embed.add_field(name="Discord Product Alerts", value="🔇 `0` — validation is always silent", inline=False)
        embed.set_footer(text="Lotus Major Retailer Pipeline • 6K-2C")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    runtime = result.get("runtime") or {}
    gate = result.get("promotion_gate") or await get_major_promotion_gate(retailer)
    embed = discord.Embed(
        title="✅ Major Retailer Silent Validation",
        description=(
            f"Persistent validation completed for **{result.get('display_name') or retailer}**. "
            "Snapshots were saved, but no product alerts were sent."
        ),
    )
    embed.add_field(name="Accepted", value=f"`{result.get('accepted', 0)}`", inline=True)
    embed.add_field(name="Rejected", value=f"`{result.get('rejected', 0)}`", inline=True)
    embed.add_field(name="Snapshots Saved", value=f"`{result.get('snapshots_upserted', 0)}`", inline=True)
    embed.add_field(
        name="Initial Baseline",
        value="🌱 Yes" if result.get("initial_baseline") else "No",
        inline=True,
    )
    embed.add_field(
        name="Validation Passes",
        value=f"`{runtime.get('validation_passes', 0)}/2`",
        inline=True,
    )
    embed.add_field(
        name="Candidate Events Suppressed",
        value=f"`{result.get('events_suppressed_validation', 0)}`",
        inline=True,
    )
    embed.add_field(
        name="Known Stock / Trusted Stock",
        value=(
            f"`{(result.get('quality_metrics') or {}).get('known_stock', 0)}` / "
            f"`{(result.get('quality_metrics') or {}).get('trusted_stock', 0)}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Unknown Stock Safety",
        value=(
            f"`{result.get('unknown_stock_ignored', 0)}` known→unknown transitions ignored for sold-out logic"
        ),
        inline=False,
    )
    embed.add_field(name="Promotion Gate", value=_major_gate_text(gate)[:1024], inline=False)
    embed.add_field(name="Discord Product Alerts", value="🔇 `0` — forced validation mode", inline=False)
    embed.set_footer(text="Two clean validations + staged store + health probe are required before promotion")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="majorpromote",
    description="Promote a fully validated major retailer to production monitoring.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorpromote(interaction, retailer: str):
    await interaction.response.defer(ephemeral=True)
    result = await promote_major_retailer(retailer)
    if not result.get("success"):
        gate = result.get("gate") or await get_major_promotion_gate(retailer)
        embed = discord.Embed(
            title="🔒 Major Retailer Promotion Blocked",
            description="Lotus refused to activate this retailer because the production gate is not satisfied.",
        )
        embed.add_field(name="Retailer", value=f"`{result.get('retailer_key') or retailer}`", inline=True)
        embed.add_field(name="Gate", value=_major_gate_text(gate)[:1024], inline=False)
        embed.set_footer(text="There is no force/bypass promotion path in 6K-2C")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title="🟢 Major Retailer Promoted",
        description=(
            f"`{result.get('retailer_key')}` is now eligible for the background major-retailer worker. "
            "Only capability-safe state changes can become Lotus events."
        ),
    )
    embed.add_field(name="Mode", value="`PRODUCTION`", inline=True)
    embed.add_field(name="Kill Switch", value="✅ OFF", inline=True)
    embed.add_field(name="Missing Product Inference", value="🔒 Disabled", inline=True)
    embed.set_footer(text="Use /majorkill immediately if a retailer source becomes unreliable")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="majordemote",
    description="Return a major retailer to silent validation mode.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majordemote(
    interaction,
    retailer: str,
    reason: str = "MANUAL_DEMOTION",
):
    await interaction.response.defer(ephemeral=True)
    result = await demote_major_retailer(retailer, reason=reason)
    await interaction.followup.send(
        (
            f"🟡 `{result.get('retailer_key') or retailer}` is now in `VALIDATION` mode.\n"
            "Background production events are disabled; saved baselines are preserved."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="majorkill",
    description="Turn the major-retailer emergency kill switch on/off for one retailer or all.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorkill(
    interaction,
    retailer: str,
    enabled: bool,
):
    await interaction.response.defer(ephemeral=True)
    result = await set_major_kill_switch(retailer, enabled)
    if not result.get("success"):
        await interaction.followup.send(
            f"❌ Kill-switch update failed: `{result.get('error') or 'UNKNOWN'}`",
            ephemeral=True,
        )
        return
    scope = result.get("scope")
    target = "ALL MAJOR RETAILERS" if scope == "GLOBAL" else f"`{result.get('retailer_key')}`"
    await interaction.followup.send(
        f"{'🛑' if enabled else '✅'} Kill switch **{'ON' if enabled else 'OFF'}** for {target}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="majorrun",
    description="Run the persistent pipeline now; events emit only if the retailer is promoted.",
)
@app_commands.checks.has_permissions(administrator=True)
async def majorrun(
    interaction,
    retailer: str,
    limit: app_commands.Range[int, 1, 40] = 20,
):
    await interaction.response.defer(ephemeral=True)
    result = await run_major_retailer_pipeline_scan(
        retailer,
        limit=int(limit),
        force_validation=False,
    )
    if not result.get("success"):
        await interaction.followup.send(
            (
                "❌ Major pipeline scan failed.\n\n"
                f"Retailer: `{result.get('retailer_key') or retailer}`\n"
                f"Reason: `{str(result.get('error') or 'UNKNOWN')[:900]}`"
            ),
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="⚙️ Major Retailer Pipeline Run",
        description=f"Completed for **{result.get('display_name') or retailer}**.",
    )
    embed.add_field(name="Mode", value=f"`{result.get('pipeline_mode')}`", inline=True)
    embed.add_field(name="Accepted", value=f"`{result.get('accepted', 0)}`", inline=True)
    embed.add_field(name="Snapshots", value=f"`{result.get('snapshots_upserted', 0)}`", inline=True)
    embed.add_field(name="Candidate Events", value=f"`{result.get('candidate_events', 0)}`", inline=True)
    embed.add_field(name="Events Emitted", value=f"`{result.get('events_emitted', 0)}`", inline=True)
    embed.add_field(name="Outbox Pending", value=f"`{result.get('outbox_pending', 0)}`", inline=True)
    embed.add_field(name="Validation-Suppressed", value=f"`{result.get('events_suppressed_validation', 0)}`", inline=True)
    embed.add_field(name="Capability-Blocked", value=f"`{result.get('events_blocked_capability', 0)}`", inline=True)
    embed.add_field(name="Confidence-Blocked", value=f"`{result.get('events_blocked_confidence', 0)}`", inline=True)
    embed.add_field(name="Cooldown-Blocked", value=f"`{result.get('events_blocked_cooldown', 0)}`", inline=True)
    embed.add_field(
        name="Safety",
        value=(
            "Missing products → no stock inference\n"
            "UNKNOWN availability → no stock lifecycle event\n"
            "Local inventory → not mixed with online inventory"
        ),
        inline=False,
    )
    embed.set_footer(text="Lotus Major Retailer Pipeline • 6K-2C • v1.0.6")
    await interaction.followup.send(embed=embed, ephemeral=True)


# =========================================================
# UNIVERSAL VALIDATION DIAGNOSTIC FORMATTER
# Step 6J-3F2
# =========================================================

def format_universal_discovery_diagnostics(value) -> str:
    diagnostics = value if isinstance(value, dict) else {}
    if not diagnostics:
        return "No adapter diagnostics were returned."

    feed_active = bool(diagnostics.get("official_feed_active"))
    feed_provider = diagnostics.get("official_feed_provider")

    feed_keys = []
    if feed_active:
        feed_keys = [
            ("official_feed_provider", "Official feed provider"),
            ("official_feed_enabled", "Official feed enabled"),
            ("official_feed_configured", "Official feed configured"),
            ("official_feed_active", "Official feed active"),
            ("official_feed_cache_hit", "Official feed cache hit"),
            ("official_feed_merchant_id", "Official feed merchant ID"),
            ("official_feed_api_calls", "Official feed API calls"),
            ("official_feed_search_calls", "Official feed search calls"),
            ("official_feed_rows_seen", "Official feed rows seen"),
            ("official_feed_rows_deduped", "Official feed rows deduped"),
            ("official_feed_products", "Official feed products"),
            ("official_feed_supported_products", "Official feed supported TCG"),
            ("official_feed_price_hits", "Official feed price hits"),
            ("official_feed_stock_hits", "Official feed stock hits"),
            ("official_feed_keywords_completed", "Official feed keywords done"),
            ("official_feed_truncated", "Official feed bounded/truncated"),
        ]
    elif feed_provider:
        # When the feed is not active, keep this compact so the existing
        # Shopware fallback diagnostics remain visible in Discord.
        feed_keys = [
            ("official_feed_provider", "Official feed provider"),
            ("official_feed_enabled", "Official feed enabled"),
            ("official_feed_configured", "Official feed configured"),
            ("official_feed_merchant_id", "Official feed merchant ID"),
        ]

    keys = tuple(feed_keys) + (
        ("pages_checked", "Pages checked"),
        ("pages_successful", "Pages OK"),
        ("listing_roots_found", "Listing roots"),
        ("listing_pages_successful", "Listing pages OK"),
        ("listing_cards_seen", "Listing cards"),
        ("listing_pages_with_game_text", "Listing pages with game text"),
        ("listing_pages_with_add_to_cart", "Listing pages with Add to cart"),
        ("loose_anchor_candidates", "Loose anchor candidates"),
        ("loose_anchor_products", "Loose anchor products"),
        ("browser_profile_requests", "Browser-profile requests"),
        ("browser_profile_pages_successful", "Browser-profile pages OK"),
        ("listing_options_seen", "Listing option blocks"),
        ("navigation_ids_seen", "Navigation IDs"),
        ("listing_slot_ids_seen", "Listing slot IDs"),
        ("synthetic_widget_urls_found", "Native widget URLs"),
        ("synthetic_widget_pages_successful", "Native widget pages OK"),
        ("synthetic_widget_pages_with_game_text", "Native widget game pages"),
        ("synthetic_widget_pages_with_add_to_cart", "Native widget cart-text pages"),
        ("synthetic_widget_product_info_pages", "Native widget metadata pages"),
        ("synthetic_widget_buy_form_pages", "Native widget buy-form pages"),
        ("synthetic_widget_out_of_stock_pages", "Native widget sold-out pages"),
        ("synthetic_widget_cards_seen", "Native widget cards"),
        ("listing_card_product_info_hits", "Card metadata hits"),
        ("listing_card_price_hits", "Card price hits"),
        ("listing_card_stock_hits", "Card stock hits"),
        ("listing_card_internal_id_hits", "Card internal IDs"),
        ("initial_enrichment_requested", "Product enrich requested"),
        ("initial_enrichment_http_ok", "Product enrich HTTP OK"),
        ("initial_enrichment_product_ok", "Product enrich parsed"),
        ("initial_enrichment_price_hits", "Product enrich price hits"),
        ("initial_enrichment_availability_hits", "Product enrich stock hits"),
        ("initial_enrichment_max_body_bytes", "Enrich max body bytes"),
        ("initial_enrichment_h1_hits", "Enrich H1 hits"),
        ("initial_enrichment_sku_hits", "Enrich SKU hits"),
        ("initial_enrichment_dollar_hits", "Enrich dollar hits"),
        ("initial_enrichment_meta_price_hits", "Enrich meta-price hits"),
        ("initial_enrichment_jsonld_hits", "Enrich JSON-LD hits"),
        ("initial_enrichment_markup_stock_hits", "Enrich schema-stock hits"),
        ("initial_enrichment_buy_form_hits", "Enrich buy-form hits"),
        ("discovered_internal_product_ids", "Internal product IDs"),
        ("direct_detail_requested", "Direct detail requested"),
        ("direct_detail_http_ok", "Direct detail HTTP OK"),
        ("direct_detail_price_hits", "Direct detail price hits"),
        ("direct_detail_availability_hits", "Direct detail stock hits"),
        ("listing_fragment_urls_found", "Fragment URLs"),
        ("listing_fragment_cards_seen", "Fragment cards"),
        ("sitemap_product_pages_successful", "Product pages OK"),
        ("product_urls_discovered", "Product URLs"),
        ("http_429", "HTTP 429"),
    )

    lines = []
    for key, label in keys:
        if key in diagnostics and diagnostics.get(key) is not None:
            lines.append(f"**{label}:** `{diagnostics.get(key)}`")

    feed_error = diagnostics.get("official_feed_last_error")
    if feed_error:
        lines.append(f"**Official feed note:** `{str(feed_error)[:220]}`")

    last_error = diagnostics.get("last_error")
    if last_error:
        lines.append(f"**Adapter error:** `{str(last_error)[:220]}`")

    return "\n".join(lines[:48]) or "Adapter diagnostics were empty."


# =========================================================
# /ADDRETAILER
# Step 6J-3E3 — Auto Detect + Stage + Silent Validation
# =========================================================
#
# New default workflow:
# /addretailer name:<name> domain:<domain> region:<region>
#
# Lotus fingerprints the storefront first. A platform override remains
# optional for administrator recovery/testing, but is no longer required.
# Ambiguous fingerprints are refused before any Store row is created.
# =========================================================

@bot.tree.command(
    name="addretailer",
    description="Auto-detect, stage, and silently validate a universal retailer.",
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    platform=RETAILER_PLATFORM_CHOICES,
)
@app_commands.describe(
    region="Retailer region code, for example US, CA, GB, JP, or EU.",
    platform=(
        "Optional manual override. Leave this blank for Lotus to "
        "detect the storefront platform automatically."
    ),
)
async def addretailer(
    interaction,
    name: str,
    domain: str,
    region: str = "US",
    platform: app_commands.Choice[str] | None = None,
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

    if not clean_name:

        await interaction.followup.send(
            "❌ Retailer name is required.",
            ephemeral=True,
        )

        return

    if not clean_domain:

        await interaction.followup.send(
            "❌ Retailer domain is required.",
            ephemeral=True,
        )

        return

    # =====================================================
    # DUPLICATE SAFETY CHECK
    # =====================================================

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
                        "⚠️ **Retailer already registered.**\n\n"
                        f"**Store ID:** `{existing.id}`\n"
                        f"**Name:** {existing.name}\n"
                        f"**Domain:** `{existing.domain}`\n"
                        f"**Platform:** `{existing.platform or 'Unknown'}`\n"
                        f"**Active:** `{existing.active}`\n\n"
                        "No duplicate store was created."
                    ),
                    ephemeral=True,
                )

                return

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Could not perform retailer duplicate check.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )

        return

    # =====================================================
    # STEP 6J-3E3
    # AUTOMATIC PLATFORM FINGERPRINTING
    # =====================================================

    detection = None
    detection_mode = "MANUAL_OVERRIDE"
    detection_confidence = "MANUAL"
    detection_score = None
    detection_signals = [
        "Administrator-selected platform override"
    ]

    if platform is None:

        detection_mode = "AUTOMATIC"

        try:

            detection = (
                await detect_retailer_platform(
                    clean_domain
                )
            )

        except asyncio.CancelledError:

            raise

        except Exception as error:

            await interaction.followup.send(
                (
                    "❌ Retailer platform fingerprinting failed.\n\n"
                    f"`{type(error).__name__}: {error}`\n\n"
                    "No store was created."
                ),
                ephemeral=True,
            )

            return

        if detection.platform == "shopify":

            embed = discord.Embed(
                title="🛍️ Shopify Storefront Detected",
                description=(
                    f"**{clean_name}** was not added to the Universal "
                    "Retailer pipeline because Lotus detected Shopify."
                ),
            )

            embed.add_field(
                name="Domain",
                value=f"`{clean_domain}`",
                inline=False,
            )

            embed.add_field(
                name="Confidence",
                value=(
                    f"`{detection.confidence}` "
                    f"• Score `{detection.score}`"
                ),
                inline=True,
            )

            embed.add_field(
                name="Next Step",
                value=(
                    "Use `/addshopifystore` so this retailer is handled "
                    "by Lotus's dedicated Shopify monitor."
                ),
                inline=False,
            )

            embed.set_footer(
                text=(
                    "Lotus Retailer Fingerprinting • "
                    "No Store row created"
                )
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )

            return

        if not detection.auto_stage_allowed:

            detected_label = (
                platform_display_name(
                    detection.platform
                )
            )

            ranked_scores = sorted(
                detection.scores.items(),
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            )

            score_text = "\n".join(
                f"**{platform_display_name(candidate)}:** `{score}`"
                for candidate, score in ranked_scores
            )

            signal_text = "\n".join(
                f"• {signal}"
                for signal in detection.signals[:6]
            )

            embed = discord.Embed(
                title="⚠️ Retailer Platform Needs Review",
                description=(
                    f"Lotus did **not** stage **{clean_name}** because the "
                    "storefront fingerprint was not strong enough for "
                    "automatic onboarding."
                ),
            )

            embed.add_field(
                name="Domain",
                value=f"`{clean_domain}`",
                inline=False,
            )

            embed.add_field(
                name="Best Match",
                value=f"`{detected_label}`",
                inline=True,
            )

            embed.add_field(
                name="Confidence",
                value=f"`{detection.confidence}`",
                inline=True,
            )

            embed.add_field(
                name="Score",
                value=f"`{detection.score}`",
                inline=True,
            )

            embed.add_field(
                name="Candidate Scores",
                value=(
                    score_text
                    or "No platform scores."
                ),
                inline=False,
            )

            embed.add_field(
                name="Detected Signals",
                value=(
                    signal_text
                    or "No decisive storefront signals were found."
                ),
                inline=False,
            )

            embed.add_field(
                name="Next Step",
                value=(
                    "Run `/detectretailer` to review the fingerprint. "
                    "If you independently confirm the platform, rerun "
                    "`/addretailer` and use the optional `platform` override."
                ),
                inline=False,
            )

            embed.set_footer(
                text=(
                    "Lotus 6J-3E3 • Ambiguous platforms are never "
                    "auto-staged"
                )
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )

            return

        clean_platform = (
            normalize_platform(
                detection.platform
            )
        )

        detection_confidence = (
            detection.confidence
        )

        detection_score = (
            detection.score
        )

        detection_signals = (
            detection.signals[:6]
        )

    else:

        clean_platform = (
            normalize_platform(
                platform.value
            )
        )

    # =====================================================
    # ADAPTER SAFETY
    # =====================================================

    try:

        load_retailer_adapters()

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Retailer adapters could not be loaded.\n\n"
                f"`{type(error).__name__}: {error}`"
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
                "❌ No Lotus adapter is currently registered "
                f"for `{clean_platform}`.\n\n"
                "No store was created."
            ),
            ephemeral=True,
        )

        return

    if clean_platform not in {
        "square_weebly",
        "woocommerce",
        "bigcommerce",
        "prestashop",
        "shopware",
    }:

        await interaction.followup.send(
            (
                "❌ That retailer platform has not yet passed "
                "Lotus universal-retailer validation.\n\n"
                "No store was created."
            ),
            ephemeral=True,
        )

        return

    # =====================================================
    # STAGE STORE — ALWAYS INACTIVE
    # =====================================================

    try:

        async with SessionLocal() as session:

            store = Store(
                name=clean_name,
                domain=clean_domain,
                platform=clean_platform,
                region=clean_region,
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

            store_id = store.id
            store_name = store.name
            store_domain = store.domain
            store_region = store.region

        # =================================================
        # IMMEDIATE SILENT VALIDATION
        # =================================================
        #
        # Existing retailer_onboarding safety remains intact:
        # - suppress_events=True
        # - automatic_mode=False
        # - store remains inactive after validation
        # =================================================

        onboarding_result = None
        onboarding_error = None

        try:

            onboarding_result = (
                await validate_staged_retailer(
                    store_id
                )
            )

        except asyncio.CancelledError:

            raise

        except Exception as error:

            onboarding_error = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            print(
                (
                    "UNIVERSAL ONBOARDING COMMAND ERROR | "
                    f"Store={store_name} | "
                    f"StoreID={store_id} | "
                    f"Platform={clean_platform} | "
                    f"DetectionMode={detection_mode} | "
                    f"Error={onboarding_error}"
                )
            )

        platform_label = (
            platform_display_name(
                clean_platform
            )
        )

        if (
            onboarding_result is not None
            and onboarding_result.validated
        ):

            embed = discord.Embed(
                title="✅ Universal Retailer Validated",
                description=(
                    f"**{store_name}** was fingerprinted, staged, and "
                    "immediately passed Lotus's silent validation scan."
                ),
            )

            monitoring_value = (
                "🟡 Validated / Inactive"
            )

            validation_value = (
                "✅ Passed"
            )

            next_step_value = (
                f"Run `/enablestore store_id:{store_id}` after reviewing "
                "this validation result."
            )

        else:

            embed = discord.Embed(
                title="⚠️ Universal Retailer Needs Review",
                description=(
                    f"**{store_name}** was fingerprinted and staged, but "
                    "Lotus could not fully validate it automatically. It "
                    "remains inactive and cannot send alerts."
                ),
            )

            monitoring_value = (
                "🔴 Staged / Inactive"
            )

            validation_value = (
                "❌ Failed / Review Required"
            )

            next_step_value = (
                f"Review the platform/validation result, then run "
                f"`/scanretailer store_id:{store_id}` or use "
                f"`/setretailerplatform store_id:{store_id}` if the "
                "platform fingerprint appears incorrect."
            )

        embed.add_field(
            name="Store ID",
            value=f"`{store_id}`",
            inline=True,
        )

        embed.add_field(
            name="Platform",
            value=f"`{platform_label}`",
            inline=True,
        )

        embed.add_field(
            name="Region",
            value=f"`{store_region}`",
            inline=True,
        )

        embed.add_field(
            name="Domain",
            value=f"`{store_domain}`",
            inline=False,
        )

        if detection_mode == "AUTOMATIC":

            detection_value = (
                "🧠 Automatic"
            )

            confidence_value = (
                f"`{detection_confidence}`"
            )

            if detection_score is not None:
                confidence_value += (
                    f" • Score `{detection_score}`"
                )

        else:

            detection_value = (
                "🛠️ Manual Override"
            )

            confidence_value = (
                "`MANUAL`"
            )

        embed.add_field(
            name="Platform Detection",
            value=detection_value,
            inline=True,
        )

        embed.add_field(
            name="Fingerprint Confidence",
            value=confidence_value,
            inline=True,
        )

        embed.add_field(
            name="Monitoring",
            value=monitoring_value,
            inline=True,
        )

        signal_text = "\n".join(
            f"• {signal}"
            for signal in detection_signals[:5]
        )

        embed.add_field(
            name="Fingerprint Signals",
            value=(
                signal_text
                or "No fingerprint signal details."
            ),
            inline=False,
        )

        embed.add_field(
            name="Discord Alerts",
            value="🔇 Disabled",
            inline=True,
        )

        embed.add_field(
            name="Validation",
            value=validation_value,
            inline=True,
        )

        if onboarding_result is not None:

            embed.add_field(
                name="Products Found",
                value=f"`{onboarding_result.products}`",
                inline=True,
            )

            embed.add_field(
                name="Availability Coverage",
                value=(
                    f"`{onboarding_result.availability_coverage}`"
                ),
                inline=True,
            )

            embed.add_field(
                name="Price Coverage",
                value=(
                    f"`{onboarding_result.price_coverage}`"
                ),
                inline=True,
            )

            embed.add_field(
                name="Scan Mode",
                value=(
                    f"`{onboarding_result.scan_mode or 'UNKNOWN'}`"
                ),
                inline=True,
            )

            embed.add_field(
                name="Historical Alerts Suppressed",
                value=(
                    f"`{onboarding_result.suppressed}`"
                ),
                inline=True,
            )

            embed.add_field(
                name="Validation Reason",
                value=(
                    f"`{onboarding_result.validation_reason}`"
                ),
                inline=False,
            )

            if not onboarding_result.validated:
                embed.add_field(
                    name="Discovery Diagnostics",
                    value=format_universal_discovery_diagnostics(
                        onboarding_result.diagnostics
                    )[:1000],
                    inline=False,
                )

        elif onboarding_error:

            embed.add_field(
                name="Validation Error",
                value=(
                    f"`{onboarding_error[:900]}`"
                ),
                inline=False,
            )

        embed.add_field(
            name="Next Step",
            value=next_step_value,
            inline=False,
        )

        embed.set_footer(
            text=(
                "Lotus Universal Retailer Foundation • "
                "6J-3F Auto Fingerprint + Silent Validation"
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Retailer could not be added.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )


# =========================================================
# /SETRETAILERPLATFORM
# Step 6J-3E2 — Safe Platform Correction
# + Immediate Silent Revalidation
# =========================================================
#
# Purpose:
# - Correct a universal retailer that was staged under
#   the wrong adapter/platform.
# - Only inactive retailers may be changed.
# - Reset staging/validation state safely.
# - Immediately rerun Lotus silent validation.
# - NEVER activate the retailer automatically.
#
# Example:
# /setretailerplatform store_id:13 platform:WooCommerce
# =========================================================

@bot.tree.command(
    name="setretailerplatform",
    description=(
        "Correct an inactive retailer platform "
        "and silently revalidate it."
    ),
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.choices(
    platform=RETAILER_PLATFORM_CHOICES,
)
async def setretailerplatform(
    interaction,
    store_id: int,
    platform: app_commands.Choice[str],
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

    clean_platform = (
        normalize_platform(
            platform.value
        )
    )

    approved_platforms = {
        "square_weebly",
        "woocommerce",
        "bigcommerce",
        "prestashop",
        "shopware",
    }

    if clean_platform not in approved_platforms:

        await interaction.followup.send(
            (
                "❌ That platform is not currently approved "
                "for Lotus Universal Retailer monitoring.\n\n"
                f"Platform: `{clean_platform}`"
            ),
            ephemeral=True,
        )

        return

    try:

        load_retailer_adapters()

    except Exception as error:

        await interaction.followup.send(
            (
                "❌ Retailer adapters could not be loaded.\n\n"
                f"`{type(error).__name__}: {error}`"
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
                "❌ No Lotus adapter is currently registered "
                f"for `{clean_platform}`."
            ),
            ephemeral=True,
        )

        return

    try:

        # =================================================
        # LOAD + SAFETY CHECK
        # =================================================

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
                    "❌ Retailer Store ID not found.",
                    ephemeral=True,
                )

                return

            # =================================================
            # ACTIVE STORE PROTECTION
            # =================================================
            #
            # Never switch adapters underneath an actively
            # monitored retailer. That could create false
            # events or corrupt its monitoring baseline.
            # =================================================

            if store.active:

                await interaction.followup.send(
                    (
                        "❌ **Platform correction blocked.**\n\n"
                        f"**{store.name}** is currently active.\n\n"
                        "A retailer must be inactive before its "
                        "platform/adapter can be changed."
                    ),
                    ephemeral=True,
                )

                return

            old_platform = (
                normalize_platform(
                    store.platform
                )
            )

            store_name = (
                store.name
                or "Unknown Store"
            )

            store_domain = (
                store.domain
                or "Unknown"
            )

            store_region = (
                store.region
                or "US"
            )

            # =================================================
            # SAFE PLATFORM CORRECTION
            # =================================================

            store.platform = (
                clean_platform
            )

            # Store MUST remain inactive.
            store.active = False

            # Reset staging/validation state so the new adapter
            # receives a clean controlled validation attempt.
            store.health_status = "HEALTHY"
            store.consecutive_failures = 0
            store.disabled_reason = "UNIVERSAL_STAGING"
            store.last_error = None

            await session.commit()

        # =================================================
        # LOG CORRECTION
        # =================================================

        print(
            (
                "UNIVERSAL RETAILER PLATFORM CORRECTED | "
                f"Store={store_name} | "
                f"StoreID={store_id} | "
                f"Domain={store_domain} | "
                f"OldPlatform={old_platform} | "
                f"NewPlatform={clean_platform} | "
                "Active=False"
            )
        )

        # =================================================
        # IMMEDIATE SILENT REVALIDATION
        # =================================================
        #
        # retailer_onboarding.py guarantees:
        # - suppress_events=True
        # - automatic_mode=False
        # - no automatic activation
        # =================================================

        onboarding_result = (
            await validate_staged_retailer(
                store_id
            )
        )

        # =================================================
        # DISPLAY LABELS
        # =================================================

        platform_labels = {
            "square_weebly": "Square / Weebly",
            "woocommerce": "WooCommerce",
            "bigcommerce": "BigCommerce",
            "prestashop": "PrestaShop",
            "shopware": "Shopware 6",
        }

        old_platform_label = (
            platform_labels.get(
                old_platform,
                old_platform
                or "Unknown",
            )
        )

        new_platform_label = (
            platform_labels.get(
                clean_platform,
                clean_platform,
            )
        )

        # =================================================
        # RESULT EMBED
        # =================================================

        if onboarding_result.validated:

            embed = discord.Embed(
                title=(
                    "✅ Retailer Platform Corrected "
                    "& Validated"
                ),
                description=(
                    f"**{store_name}** was switched to the "
                    f"**{new_platform_label}** adapter and "
                    "successfully passed Lotus's controlled "
                    "silent validation."
                ),
            )

        else:

            embed = discord.Embed(
                title=(
                    "⚠️ Retailer Platform Corrected "
                    "— Review Required"
                ),
                description=(
                    f"**{store_name}** was switched to the "
                    f"**{new_platform_label}** adapter, but "
                    "validation still requires review.\n\n"
                    "The retailer remains inactive and cannot "
                    "send Discord alerts."
                ),
            )

        embed.add_field(
            name="Store ID",
            value=f"`{store_id}`",
            inline=True,
        )

        embed.add_field(
            name="Region",
            value=f"`{store_region}`",
            inline=True,
        )

        embed.add_field(
            name="Monitoring",
            value=(
                "🟡 Validated / Inactive"
                if onboarding_result.validated
                else
                "🔴 Staged / Inactive"
            ),
            inline=True,
        )

        embed.add_field(
            name="Domain",
            value=f"`{store_domain}`",
            inline=False,
        )

        embed.add_field(
            name="Previous Platform",
            value=f"`{old_platform_label}`",
            inline=True,
        )

        embed.add_field(
            name="New Platform",
            value=f"`{new_platform_label}`",
            inline=True,
        )

        embed.add_field(
            name="Discord Alerts",
            value="🔇 Disabled",
            inline=True,
        )

        embed.add_field(
            name="Products Found",
            value=(
                f"`{onboarding_result.products}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Availability Coverage",
            value=(
                f"`{onboarding_result.availability_coverage}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Price Coverage",
            value=(
                f"`{onboarding_result.price_coverage}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Scan Mode",
            value=(
                f"`{onboarding_result.scan_mode or 'UNKNOWN'}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Historical Alerts Suppressed",
            value=(
                f"`{onboarding_result.suppressed}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Validation",
            value=(
                "✅ Passed"
                if onboarding_result.validated
                else
                "❌ Failed / Review Required"
            ),
            inline=True,
        )

        embed.add_field(
            name="Validation Reason",
            value=(
                f"`{onboarding_result.validation_reason}`"
            ),
            inline=False,
        )

        if onboarding_result.validated:

            embed.add_field(
                name="Next Step",
                value=(
                    f"Store `{store_id}` is validated but still "
                    "inactive. Do **not** enable it until we review "
                    "this validation result together."
                ),
                inline=False,
            )

        else:

            embed.add_field(
                name="Next Step",
                value=(
                    "Leave this retailer inactive and review the "
                    "new validation result before making any "
                    "additional adapter changes."
                ),
                inline=False,
            )

        embed.set_footer(
            text=(
                "Lotus Universal Retailer Foundation • "
                "6J-3E2 Safe Platform Correction"
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except asyncio.CancelledError:

        raise

    except Exception as error:

        print(
            (
                "UNIVERSAL RETAILER PLATFORM CORRECTION ERROR | "
                f"StoreID={store_id} | "
                f"NewPlatform={clean_platform} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        await interaction.followup.send(
            (
                "❌ Retailer platform correction failed.\n\n"
                f"`{type(error).__name__}: {error}`\n\n"
                "The retailer was not intentionally activated."
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
            "\u274c PostgreSQL is unavailable.",
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
                    "\u274c Retailer Store ID not found.",
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
                    "\u274c This is a Shopify store.\n\n"

                    "Use `/scanshopify` instead."
                ),

                ephemeral=True,
            )

            return

        if platform == "pokemon_center":

            await interaction.followup.send(

                (
                    "\u274c Pok\xe9mon Center uses its dedicated "
                    "monitor."
                ),

                ephemeral=True,
            )

            return

        if platform == "major_retailer":

            await interaction.followup.send(

                (
                    "\u274c Major retailers use their dedicated "
                    "monitoring pipeline."
                ),

                ephemeral=True,
            )

            return

        if platform not in {
            "square_weebly",
            "woocommerce",
            "bigcommerce",
            "prestashop",
            "shopware",
        }:

            await interaction.followup.send(

                (
                    "\u274c This platform is not yet approved "
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
                    "\u274c The universal retailer adapter "
                    f"for `{platform}` is not registered."
                ),

                ephemeral=True,
            )

            return

        scan_result = (
            await scan_store(

                scan_store_object,

                suppress_events=True,
            )
        )

        if not scan_result.get(
            "success"
        ):

            failure_embed = discord.Embed(
                title="❌ Universal Retailer Scan Failed",
                description=(
                    f"Controlled silent scan failed for "
                    f"**{scan_store_object.name}**. "
                    "No universal retailer alerts were sent."
                ),
            )
            failure_embed.add_field(
                name="Store ID",
                value=f"`{scan_store_object.id}`",
                inline=True,
            )
            failure_embed.add_field(
                name="Platform",
                value=f"`{platform_display_name(platform)}`",
                inline=True,
            )
            failure_embed.add_field(
                name="Domain",
                value=f"`{scan_store_object.domain}`",
                inline=False,
            )
            failure_embed.add_field(
                name="Reason",
                value=f"`{scan_result.get('error') or 'Unknown error'}`",
                inline=False,
            )
            failure_embed.add_field(
                name="Discovery Diagnostics",
                value=format_universal_discovery_diagnostics(
                    scan_result.get("diagnostics")
                )[:1000],
                inline=False,
            )
            failure_embed.add_field(
                name="Safety",
                value="🔇 Forced silent scan — Discord alerts remained disabled.",
                inline=False,
            )
            failure_embed.set_footer(
                text="Lotus Universal Retailer Foundation • 6J-3F9 Shopware Product Enrichment Diagnostics"
            )

            await interaction.followup.send(
                embed=failure_embed,
                ephemeral=True,
            )

            return

        # Step 6J-3B2:
        # Use scan_store()'s per-store diagnostics directly.
        # The automatic universal monitor can run concurrently with this
        # controlled scan, so global before/after MONITOR_STATUS deltas can
        # include products from other active stores and inflate these values.
        unknown_stock = int(
            scan_result.get(
                "unknown_availability",
                0,
            )
            or 0
        )

        missing_prices = int(
            scan_result.get(
                "missing_prices",
                0,
            )
            or 0
        )

        embed = discord.Embed(

            title=(
                "\U0001f310 Universal Retailer Scan"
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

        scan_platform_label = {
            "square_weebly": "Square / Weebly",
            "woocommerce": "WooCommerce",
            "bigcommerce": "BigCommerce",
            "prestashop": "PrestaShop",
            "shopware": "Shopware 6",
        }.get(platform, platform)

        embed.add_field(
            name="Platform",
            value=f"`{scan_platform_label}`",
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

                "\U0001f331 Initial Baseline"

                if scan_result.get(
                    "baseline_mode"
                )

                else "\u2705 Existing Baseline"
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
            name="Backorders",
            value=(
                f"`{scan_result.get('backorders', 0)}`"
            ),
            inline=True,
        )

        # F12: Shopware retailers may use an approved official product feed
        # for authoritative discovery + price data while stock remains
        # capability-gated. Unknown availability is therefore expected for
        # feed-backed products and must never be interpreted as sold out.
        shopware_diagnostics = (
            scan_result.get("diagnostics")
            if isinstance(scan_result.get("diagnostics"), dict)
            else {}
        )
        official_feed_active = bool(
            shopware_diagnostics.get("official_feed_active")
        )

        if platform == "shopware" and (
            official_feed_active
            or int(scan_result.get("products", 0) or 0) < 40
            or unknown_stock > 0
            or missing_prices > 0
        ):
            embed.add_field(
                name=(
                    "Official Feed + Shopware Diagnostics"
                    if official_feed_active
                    else "Shopware Discovery Diagnostics"
                ),
                value=format_universal_discovery_diagnostics(
                    shopware_diagnostics
                )[:1000],
                inline=False,
            )

            if official_feed_active:
                embed.add_field(
                    name="Official Feed Readiness",
                    value=(
                        "🟡 The approved product feed is supplying discovery "
                        "and price intelligence. Availability remains "
                        "**UNKNOWN by design** until an independently verified "
                        "stock source exists, so restock/sold-out/stock alerts "
                        "remain capability-gated. Keep this retailer inactive "
                        "until feed catalog and price coverage are reviewed."
                    ),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Shopware Readiness",
                    value=(
                        "⚠️ Discovery is working, but this retailer is still in "
                        "compatibility review. Keep it inactive until product "
                        "coverage plus price/availability quality are verified."
                    ),
                    inline=False,
                )

        embed.add_field(

            name="Safety Mode",

            value=(
                "\U0001f507 **Forced Silent Scan**\n"
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

                name="\u26a0\ufe0f Safety Warning",

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
                    "\u2705 Scan completed with alerts suppressed."
                ),
                inline=False,
            )

        embed.set_footer(
            text=(
                "Lotus Universal Retailer Foundation • "
                "6J-3F9 Shopware Product Enrichment"
            )
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "\u274c Universal retailer scan failed.\n\n"

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
                f"{'\u2705 Added' if created else '\u2705 Updated'} "
                f"**{store.name}**\n"

                f"`{store.domain}`\n"

                f"Region: `{store.region}`"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "\u274c Store could not be added.\n\n"

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
    description="List all Lotus monitored stores.",
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

    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Store).order_by(Store.id.asc())
            )
            store_list = list(result.scalars().all())
    except Exception as error:
        await interaction.followup.send(
            (
                "❌ Could not load stores.\n\n"
                f"`{type(error).__name__}: {error}`"
            ),
            ephemeral=True,
        )
        return

    if not store_list:
        await interaction.followup.send(
            "No monitored stores.",
            ephemeral=True,
        )
        return

    platform_labels = {
        "shopify": "Shopify",
        "square_weebly": "Square / Weebly",
        "woocommerce": "WooCommerce",
        "bigcommerce": "BigCommerce",
        "prestashop": "PrestaShop",
        "shopware": "Shopware 6",
        "pokemon_center": "Pokémon Center",
        "major_retailer": "Major Retailer",
    }

    lines = []

    for store in store_list:
        platform = normalize_platform(
            getattr(store, "platform", None)
        )
        platform_label = platform_labels.get(
            platform,
            platform or "Unknown",
        )
        health = getattr(store, "health_status", None) or "UNKNOWN"
        disabled_reason = getattr(store, "disabled_reason", None)

        lines.append(
            (
                f"**ID {store.id} — {store.name}**\n"
                f"`{store.domain}`\n"
                f"Platform: `{platform_label}`\n"
                f"Region: `{store.region or 'Unknown'}`\n"
                f"{'🟢' if store.active else '⚫'} {health}"
                + (
                    f" • {disabled_reason}"
                    if disabled_reason
                    else ""
                )
            )
        )

    chunks = []
    current = ""

    for entry in lines:
        candidate = entry if not current else current + "\n\n" + entry
        if len(candidate) > 1900:
            if current:
                chunks.append(current)
            current = entry
        else:
            current = candidate

    if current:
        chunks.append(current)

    await interaction.followup.send(
        chunks[0],
        ephemeral=True,
    )

    for chunk in chunks[1:]:
        await interaction.followup.send(
            chunk,
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
            "\u274c Store ID not found.",
            ephemeral=True,
        )

        return

    embed = discord.Embed(
        title=(
            f"\U0001f3ea {store.name}"
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
            "Yes \u2705"
            if store.active
            else "No \u274c"
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
            else "None \u2705"
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
            "\u274c Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"\u26ab **{store.name}** manually disabled.\n\n"

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
            "\u274c Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        f"\U0001f7e2 **{store.name}** enabled.",
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
            "\u274c Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"\U0001f5d1\ufe0f **{store.name}** removed "
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
            "\u274c Store not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            f"\u267b\ufe0f **{store.name}** restored "
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
            "\U0001fa7a **Lotus Store Health**\n\n"

            f"\U0001f7e2 Healthy: "
            f"`{overview['healthy']}`\n"

            f"\U0001f7e1 Degraded: "
            f"`{overview['degraded']}`\n"

            f"\U0001f534 Unhealthy: "
            f"`{overview['unhealthy']}`\n"

            f"\u26ab Disabled: "
            f"`{overview['disabled']}`\n"

            f"\U0001f5d1\ufe0f Removed: "
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
            "\u274c Store not found.",
            ephemeral=True,
        )

        return

    if reason == "MANUAL":

        await interaction.followup.send(

            (
                "\u26a0\ufe0f This store was manually disabled.\n"

                "Use `/enablestore`."
            ),

            ephemeral=True,
        )

        return

    if reason == "REMOVED":

        await interaction.followup.send(

            (
                "\u26a0\ufe0f This store was removed.\n"

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
                "\U0001f7e2 Store responded successfully.\n"

                "Health restored and monitoring enabled."
            ),

            ephemeral=True,
        )

    else:

        await interaction.followup.send(

            (
                "\U0001f534 Store health check failed.\n"

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

    before = get_shopify_monitor_status()

    if before.get("scan_in_progress"):

        started = (
            before.get("scan_started_at")
            or "Unknown"
        )

        await interaction.followup.send(
            (
                "⏳ **A Shopify scan is already in progress.**\n\n"
                "The manual scan was not started because Step 6K-2C1 "
                "prevents overlapping scans.\n\n"
                f"Started: `{started}`\n"
                f"Active Shopify Stores: "
                f"`{before.get('active_shopify_stores', 0)}`\n\n"
                "Wait for the current cycle to finish, then check "
                "`/shopifystatus`. This is not the same as having "
                "zero active stores."
            ),
            ephemeral=True,
        )
        return

    results = (
        await scan_all_shopify_stores()
    )

    after = get_shopify_monitor_status()

    if not results:

        outcome = (
            after.get("last_scan_outcome")
            or "UNKNOWN"
        )

        if outcome == "SKIPPED_OVERLAP":

            message = (
                "⏳ **A Shopify scan started before this command could "
                "acquire the scan lock.**\n\n"
                "No second scan was started. Check `/shopifystatus` "
                "for the current cycle."
            )

        elif int(after.get("active_shopify_stores", 0) or 0) == 0:

            message = (
                "⚠️ **No active Shopify stores are currently eligible "
                "for scanning.**\n\n"
                "Run `/stores` to review their Active/Platform state."
            )

        else:

            last_error = (
                after.get("last_error")
                or "No specific error was recorded."
            )

            message = (
                "⚠️ **The Shopify cycle finished, but no store "
                "completed successfully.**\n\n"
                f"Active Shopify Stores: "
                f"`{after.get('active_shopify_stores', 0)}`\n"
                f"Stores Failed: "
                f"`{after.get('stores_failed', 0)}`\n"
                f"HTTP 429 Responses: "
                f"`{after.get('rate_limit_responses', 0)}`\n"
                f"Retries: "
                f"`{after.get('rate_limit_retries', 0)}`\n"
                f"Backoff Seconds: "
                f"`{after.get('rate_limit_backoff_seconds', 0)}`\n"
                f"Outcome: `{outcome}`\n\n"
                f"Last Error:\n`{str(last_error)[:900]}`"
            )

        await interaction.followup.send(
            message,
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

        diagnostics = (
            result.get("diagnostics")
            or {}
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
                f"Priority Collections: "
                f"`{diagnostics.get('priority_collections', 0)}`\n"
                f"Collection Products: "
                f"`{diagnostics.get('collection_products_seen', 0)}`\n"
                f"General Products: "
                f"`{diagnostics.get('general_products_seen', 0)}`\n"
                f"HTTP 429s: "
                f"`{diagnostics.get('rate_limit_responses', 0)}` | "
                f"Retries: "
                f"`{diagnostics.get('rate_limit_retries', 0)}`\n"
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
                    if result["initial_seed"]
                    else ""
                )
            )
        )

    await interaction.followup.send(
        ("\n\n".join(lines))[:1900],
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

    scan_in_progress = bool(
        data.get("scan_in_progress")
    )

    embed = discord.Embed(
        title="🛍️ Lotus Shopify Monitor",
        description=(
            f"**Worker:** "
            f"{'✅ Online' if worker_online else '❌ Offline'}\n"
            f"**Monitor Loop:** "
            f"{'✅ Running' if data.get('running') else '❌ Stopped'}\n"
            f"**Scan In Progress:** "
            f"{'🟡 Yes' if scan_in_progress else '⚪ No'}\n"
            f"**Active Shopify Stores:** "
            f"`{data.get('active_shopify_stores', 0)}`\n"
            f"**Last Outcome:** "
            f"`{data.get('last_scan_outcome', 'NOT_YET')}`\n"
            f"**Stores Scanned:** "
            f"`{data.get('stores_scanned', 0)}`\n"
            f"**Stores Failed:** "
            f"`{data.get('stores_failed', 0)}`\n"
            f"**TCG Products Seen:** "
            f"`{data.get('products_seen', 0)}`\n"
            f"**Events:** "
            f"`{data.get('events_created', 0)}`\n"
            f"**Flickers:** "
            f"`{data.get('flickers_detected', 0)}`\n\n"
            "**Rate Limit Protection:**\n"
            f"429s: `{data.get('rate_limit_responses', 0)}` | "
            f"Retries: `{data.get('rate_limit_retries', 0)}` | "
            f"Backoff: "
            f"`{data.get('rate_limit_backoff_seconds', 0)}s`\n"
            f"Overlap Skips: "
            f"`{data.get('scan_skipped_overlap', 0)}`\n\n"
            "**Priority Discovery:**\n"
            f"Collections: "
            f"`{data.get('priority_collections', 0)}` | "
            f"Collection Products: "
            f"`{data.get('collection_products_seen', 0)}`\n"
            f"General Products: "
            f"`{data.get('general_products_seen', 0)}` | "
            f"General Feed Skips: "
            f"`{data.get('general_feed_skipped', 0)}`\n"
            f"New Priority Memberships: "
            f"`{data.get('new_priority_collection_memberships', 0)}` | "
            f"Membership Alerts: "
            f"`{data.get('priority_membership_alerts', 0)}`"
        ),
    )

    embed.add_field(
        name="Current Scan Started",
        value=(
            data.get("scan_started_at")
            if scan_in_progress
            else "Not scanning"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Completed Scan",
        value=(
            data.get("last_scan")
            or "Not yet"
        ),
        inline=False,
    )

    duration = data.get(
        "scan_duration_seconds"
    )

    embed.add_field(
        name="Last Scan Duration",
        value=(
            f"{duration}s"
            if duration is not None
            else "Not yet"
        ),
        inline=False,
    )

    embed.add_field(
        name="Last Error",
        value=(
            str(data.get("last_error"))[:1000]
            if data.get("last_error")
            else "None ✅"
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
    description="View Pok\xe9mon Center queue status.",
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

        title="\u26a1 Pok\xe9mon Center Queue Intelligence",

        description=(

            f"**Worker:** "
            f"{'\u2705 Online' if worker_online else '\u274c Offline'}\n"

            f"**Running:** "
            f"{'\u2705' if data['running'] else '\u274c'}\n"

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
            or "None \u2705"
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
    description="Run a Pok\xe9mon Center queue scan now.",
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
                    "\u26a0\ufe0f Pok\xe9mon Center scan "
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
                    f"{'\U0001f6a8 ACTIVE' if result['queue_active'] else '\u2705 Clear'}"
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
                "\u274c Pok\xe9mon Center scan failed.\n"

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
    description="Add a Pok\xe9mon Center product to Lotus monitoring.",
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
                f"{'\u2705 Added' if created else '\u2705 Reactivated'} "
                "**Pok\xe9mon Center product**\n\n"

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
                "\u274c Product could not be added.\n\n"

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
    description="View known Pok\xe9mon Center products.",
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
            "No Pok\xe9mon Center products registered.",
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
                "\u2705",

            "BLOCKED":
                "\U0001f6ab",

            "PARSE_ERROR":
                "\U0001f9e9",

            "ERROR":
                "\u26a0\ufe0f",

        }.get(
            product.scan_status,
            "\u26aa",
        )

        lines.append(

            (
                f"**ID {product.id} \u2014 "
                f"{product.product_code or 'Unknown'}**\n"

                f"{'\U0001f7e2 Active' if product.active else '\u26ab Removed'}\n"

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
    description="Stop monitoring a Pok\xe9mon Center product.",
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
            "\u274c Product ID not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            "\u26ab Pok\xe9mon Center product removed "
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
    description="Restore a removed Pok\xe9mon Center product.",
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
            "\u274c Product ID not found.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(

        (
            "\u267b\ufe0f Pok\xe9mon Center product restored.\n"

            f"`{product.product_code or product.id}`"
        ),

        ephemeral=True,
    )


# =========================================================
# /DISCOVERPOKEMONPRODUCTS
# =========================================================

@bot.tree.command(
    name="discoverpokemonproducts",
    description="Run Pok\xe9mon Center indexed product discovery.",
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
                "\U0001f50e Pok\xe9mon Center discovery complete.\n\n"

                f"**New products added:** "
                f"`{count}`"
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.followup.send(

            (
                "\u274c Product discovery failed.\n"

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
    description="Scan known Pok\xe9mon Center products now.",
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
                "\u26a1 **Pok\xe9mon Center Product Scan**\n\n"

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
                "\u274c Product scan failed.\n"

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
    description="View Pok\xe9mon Center product intelligence.",
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
            "\u26a1 Pok\xe9mon Center Product Intelligence"
        ),

        description=(

            f"**Worker:** "
            f"{'\u2705 Online' if worker_online else '\u274c Offline'}\n"

            f"**Running:** "
            f"{'\u2705' if data['running'] else '\u274c'}\n"

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
            or "None \u2705"
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
    description="Temporarily enable fast Pok\xe9mon Center monitoring.",
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
                    "\u26a0\ufe0f Burst mode could not be enabled "
                    "because Redis is unavailable."
                ),

                ephemeral=True,
            )

            return

        await interaction.response.send_message(

            (
                "\u26a1 Pok\xe9mon Center burst monitoring "
                f"enabled for **{region.upper()}** "
                "for 5 minutes."
            ),

            ephemeral=True,
        )

    except Exception as error:

        await interaction.response.send_message(

            (
                "\u274c Burst mode failed.\n"

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

            "Pok\xe9mon Center Test"

            if queue_event

            else (
                f"{game.value} "
                f"{PRODUCT_FAMILY_LABELS.get(family_value, family_value)} "
                "Test Booster Box"
            )
        ),

        store_name=(
            "Pok\xe9mon Center"
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
            "\U0001f9ea Event submitted.\n\n"

            f"Event: "
            f"`{event.value}`\n"

            f"Game: "
            f"`{product_event.game}`\n"

            f"Category: "
            f"`{product_event.product_category}`\n"

            f"Family: "
            f"`{product_event.product_family}`\n"

            f"Database: "
            f"{'\u2705' if result['database_saved'] else '\u274c'}\n"

            f"Redis: "
            f"{'\u2705' if result['redis_saved'] else '\u274c'}"
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
                "\u274c Unknown alert type.\n\n"

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
            "\u274c Alert channel not found.",
            ephemeral=True,
        )

        return

    await channel.send(

        embed=discord.Embed(

            title="\U0001f9ea LOTUS TEST ALERT",

            description=(

                f"**{game.value} Test Product**\n"

                f"Route: "
                f"`{alert_type}`\n"

                "Version: `1.0.6`"
            ),
        )
    )

    await interaction.followup.send(

        (
            f"\u2705 Test alert sent "
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

    universal_monitor_online = (
        bot.universal_retailer_monitor_task
        is not None
        and
        not bot.universal_retailer_monitor_task.done()
        and
        bool(universal_status.get("running"))
    )

    major_pipeline_status = await get_major_pipeline_status()

    major_monitor_online = (
        bot.major_retailer_monitor_task
        is not None
        and
        not bot.major_retailer_monitor_task.done()
        and
        bool(major_pipeline_status.get("running"))
    )

    embed = discord.Embed(

        title="\U0001f7e2 Lotus Tracker Bot Status",

        description=(

            f"**PostgreSQL / Alembic:** "
            f"{'\u2705' if bot.database_ready else '\u274c'}\n"

            f"**Redis:** "
            f"{'\u2705' if bot.redis_ready else '\u274c'}\n"

            f"**Event Worker:** "
            f"{'\u2705' if event_worker_online else '\u274c'}\n"

            f"**Shopify Monitor:** "
            f"{'\u2705' if shopify_online else '\u274c'}\n"

            f"**Pok\xe9mon Queue Monitor:** "
            f"{'\u2705' if pokemon_queue_online else '\u274c'}\n"

            f"**Pok\xe9mon Product Monitor:** "
            f"{'\u2705' if pokemon_products_online else '\u274c'}\n"

            f"**Universal Retailer Monitor:** "
            f"{'\u2705 Automatic / Capability Safe' if universal_monitor_online else '\u274c Offline'}\n"
            f"**Universal Stores Current Cycle:** "
            f"`{universal_status.get('stores_scanned', 0)}/"
            f"{universal_status.get('current_cycle_total_stores', 0)}`"
            + (
                f" • `{universal_status.get('current_store_name')}`"
                if universal_status.get('current_cycle_in_progress')
                and universal_status.get('current_store_name')
                else ""
            )
            + "\n"
            f"**Universal Stores Last Completed Cycle:** "
            f"`{universal_status.get('last_completed_stores_scanned', 0)}`\n"
            f"**Universal Failures Last Cycle:** "
            f"`{universal_status.get('last_completed_stores_failed', 0)}`\n"
            f"**Universal Timeouts Last Cycle:** "
            f"`{universal_status.get('last_completed_store_timeouts', 0)}`\n"
            f"**Universal Stock Events Blocked Last Cycle:** "
            f"`{universal_status.get('last_completed_stock_events_blocked', 0)}`\n"
            f"**Major Retailer Monitor:** "
            f"{'✅ Promotion-Gated' if major_monitor_online else '❌ Offline'}\n"
            f"**Major Retailers in Production:** "
            f"`{major_pipeline_status.get('production_retailers', 0)}`\n"
            f"**Major Global Kill Switch:** "
            f"{'🛑 ON' if major_pipeline_status.get('global_kill_switch') else '✅ OFF'}\n\n"

            "**Strict TCG Classification:** \u2705\n"

            "**Category Preferences:** \u2705\n"

            "**Singles Filtering:** \u2705\n"

            "**Product Family Detection:** \u2705\n"

            "**English / JP / KR / CN Preferences:** \u2705\n"

            "**Game + Category + Family Audience:** \u2705\n"

            "**Currency-Independent Family Detection:** \u2705\n"

            "**Regional MSRP Isolation:** \u2705\n"

            "**Exact Product MSRP:** \u2705\n"

            "**Product Type MSRP:** \u2705\n"

            "**Game Default MSRP:** \u2705\n"

            "**Cross-Currency MSRP:** \u2705\n"

            "**30-Day Pricing History:** \u2705\n"

            "**Deal Score:** \u2705\n"

            "**Scalper Protection:** \u2705\n"

            "**Smart Quick Cart:** \u2705\n"

            "**Native Currency:** \u2705\n"

            "**USD Conversion:** \u2705\n"

            "**Early Page Routing:** \u2705\n"

            "**Product Images:** \u2705\n"

            "**Affiliate Pipeline:** \u2705\n"

            "**Store Self-Healing:** \u2705\n"

            "**Inventory Flicker:** \u2705\n"

            "**Universal Retailer Foundation:** \u2705\n"

            "**Auto Platform Fingerprinting:** \u2705\n"

            f"**Universal Adapters Loaded:** "
            f"{'\u2705' if universal_status.get('adapters_loaded') else '\u26aa'}\n\n"

            f"**Healthy Stores:** "
            f"{health['healthy']}\n"

            f"**Degraded Stores:** "
            f"{health['degraded']}\n"

            f"**Unhealthy Stores:** "
            f"{health['unhealthy']}\n"

            f"**Redis Queue:** "
            f"`{queue}`\n\n"

            "**Version:** `1.0.6`"
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
            "\u274c You do not have permission "
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

            "\u274c Command failed.\n\n"

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