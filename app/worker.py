async def build_event_embed(
    event,
):
    # =====================================================
    # EVENT BASICS
    # =====================================================

    event_type = (
        event.get(
            "event_type",
            "UNKNOWN",
        )
    )

    product_name = (
        event.get(
            "product_name"
        )
        or "Unknown Product"
    )

    store_name = (
        event.get(
            "store_name"
        )
        or "Unknown Store"
    )

    product_url = (
        event.get(
            "product_url"
        )
        or ""
    )

    final_url, affiliate_used = (
        build_affiliate_url(
            product_url,
            store_name,
        )
    )

    # =====================================================
    # PRODUCT INFORMATION
    # =====================================================

    game = (
        event.get(
            "game"
        )
        or ""
    )

    product_category = (
        event.get(
            "product_category"
        )
        or "UNKNOWN"
    )

    product_type = (
        event.get(
            "product_type"
        )
        or ""
    )

    region = (
        event.get(
            "region"
        )
        or ""
    )

    source_type = (
        event.get(
            "source_type"
        )
        or "unknown"
    )

    price = (
        event.get(
            "price"
        )
    )

    old_price = (
        event.get(
            "old_price"
        )
    )

    currency = (
        event.get(
            "currency"
        )
        or "USD"
    ).upper()

    purchase_limit = (
        event.get(
            "purchase_limit"
        )
    )

    # =====================================================
    # SOURCE LABELS
    # =====================================================

    source_labels = {
        "shopify":
            "Shopify • TCG Store",

        "major_retailer":
            "Major Retailer",

        "pokemon_center":
            "Pokémon Center",

        "queue":
            "Queue Intelligence",

        "simulation":
            "Simulation",
    }

    source_label = (
        source_labels.get(
            source_type,
            source_type.replace(
                "_",
                " ",
            ).title(),
        )
    )

    # =====================================================
    # CREATE EMBED
    # =====================================================

    embed = discord.Embed(

        title=(
            EVENT_TITLES.get(
                event_type,
                "📡 LOTUS PRODUCT EVENT",
            )
        ),

        description=(
            f"**{product_name}**"
        ),

        url=(
            final_url
            or None
        ),
    )

    # =====================================================
    # PRODUCT IMAGE
    # =====================================================

    image_url = (
        event.get(
            "image_url"
        )
    )

    if image_url:

        embed.set_thumbnail(
            url=image_url
        )

    # =====================================================
    # PRICE
    #
    # PRICE CHANGE:
    #
    # C$34.99 → C$39.33
    # 📈 +C$4.34 • +12.4%
    # ≈ US$28.37
    #
    # NORMAL:
    #
    # C$39.33
    # ≈ US$28.37
    # =====================================================

    if price is not None:

        native_text = (
            format_currency(
                price,
                currency,
            )
        )

        price_lines = []

        is_price_change = (
            event_type
            in {
                "PRICE_DROP",
                "PRICE_INCREASE",
                "PRICE_ERROR",
            }
        )

        # =================================================
        # OLD → NEW PRICE
        # =================================================

        if (
            is_price_change
            and old_price is not None
        ):

            try:

                old_value = float(
                    old_price
                )

                new_value = float(
                    price
                )

                old_text = (
                    format_currency(
                        old_value,
                        currency,
                    )
                )

                difference = (
                    new_value
                    - old_value
                )

                if old_value != 0:

                    percentage = (
                        difference
                        / old_value
                    ) * 100

                else:

                    percentage = 0.0

                difference_text = (
                    format_currency(
                        abs(
                            difference
                        ),
                        currency,
                    )
                )

                # -----------------------------------------
                # PRICE DROP
                # -----------------------------------------

                if difference < 0:

                    price_lines.append(
                        (
                            f"**{old_text} → "
                            f"{native_text}**"
                        )
                    )

                    price_lines.append(
                        (
                            f"🔥 Save "
                            f"**{difference_text}** "
                            f"• "
                            f"**{abs(percentage):.1f}%**"
                        )
                    )

                # -----------------------------------------
                # PRICE INCREASE
                # -----------------------------------------

                elif difference > 0:

                    price_lines.append(
                        (
                            f"**{old_text} → "
                            f"{native_text}**"
                        )
                    )

                    price_lines.append(
                        (
                            f"📈 +**{difference_text}** "
                            f"• "
                            f"**+{percentage:.1f}%**"
                        )
                    )

                # -----------------------------------------
                # NO NUMERICAL CHANGE
                # -----------------------------------------

                else:

                    price_lines.append(
                        f"**{native_text}**"
                    )

            except (
                TypeError,
                ValueError,
            ):

                price_lines.append(
                    f"**{native_text}**"
                )

        else:

            price_lines.append(
                f"**{native_text}**"
            )

        # =================================================
        # USD CONVERSION
        # =================================================

        if currency != "USD":

            converted_usd = (
                await convert_currency(
                    price,
                    currency,
                    "USD",
                )
            )

            if (
                converted_usd
                is not None
            ):

                usd_text = (
                    format_currency(
                        converted_usd,
                        "USD",
                    )
                )

                price_lines.append(
                    f"≈ **{usd_text}**"
                )

        embed.add_field(

            name="💰 Price",

            value=(
                "\n".join(
                    price_lines
                )
            ),

            inline=False,
        )

    # =====================================================
    # STORE + REGION
    #
    # 🏪 Hobbiesville • 🇨🇦 CA
    # =====================================================

    store_parts = [
        f"🏪 **{store_name}**"
    ]

    if region:

        region_flags = {
            "US": "🇺🇸",
            "USA": "🇺🇸",

            "CA": "🇨🇦",
            "CAN": "🇨🇦",

            "UK": "🇬🇧",
            "GB": "🇬🇧",

            "JP": "🇯🇵",
            "JAPAN": "🇯🇵",

            "EU": "🇪🇺",

            "AU": "🇦🇺",
            "AUS": "🇦🇺",
        }

        region_upper = (
            str(
                region
            ).upper()
        )

        region_flag = (
            region_flags.get(
                region_upper,
                "🌎",
            )
        )

        store_parts.append(
            (
                f"{region_flag} "
                f"**{region_upper}**"
            )
        )

    embed.add_field(

        name="\u200b",

        value=(
            " • ".join(
                store_parts
            )
        ),

        inline=False,
    )

    # =====================================================
    # GAME + CATEGORY / TYPE
    #
    # 🏴‍☠️ One Piece • 🃏 Single
    # =====================================================

    product_parts = []

    game_icons = {
        "One Piece":
            "🏴‍☠️",

        "Pokemon":
            "⚡",

        "Pokémon":
            "⚡",

        "Magic: The Gathering":
            "🧙",

        "MTG":
            "🧙",

        "Riftbound":
            "⚔️",

        "LEGO":
            "🧱",

        "Video Games":
            "🎮",

        "Board Games":
            "🎲",
    }

    if game:

        game_icon = (
            game_icons.get(
                game,
                "🎴",
            )
        )

        product_parts.append(
            (
                f"{game_icon} "
                f"**{game}**"
            )
        )

    category_display = None

    if (
        product_category
        and product_category
        != "UNKNOWN"
    ):

        category_display = (
            str(
                product_category
            )
            .replace(
                "_",
                " ",
            )
            .title()
        )

    type_display = None

    if product_type:

        type_display = (
            str(
                product_type
            )
            .replace(
                "_",
                " ",
            )
        )

    # Avoid displaying things like:
    #
    # Single • Single
    #
    # when category and type are the same.

    if category_display:

        product_parts.append(
            f"🃏 {category_display}"
        )

    if (
        type_display
        and (
            not category_display
            or (
                type_display.lower()
                != category_display.lower()
            )
        )
    ):

        product_parts.append(
            type_display
        )

    if product_parts:

        embed.add_field(

            name="\u200b",

            value=(
                " • ".join(
                    product_parts
                )
            ),

            inline=False,
        )

    # =====================================================
    # STOCK / AVAILABILITY
    # =====================================================

    if event_type in {

        "STOCK_AVAILABLE",
        "RESTOCK",
        "SOLD_OUT",
        "INVENTORY_FLICKER",

    }:

        in_stock = bool(
            event.get(
                "in_stock"
            )
        )

        if in_stock:

            stock_text = (
                "🟢 **IN STOCK**"
            )

        else:

            stock_text = (
                "🔴 **OUT OF STOCK**"
            )

        # Flicker gets special context because the product
        # may disappear again very quickly.

        if (
            event_type
            == "INVENTORY_FLICKER"
        ):

            if in_stock:

                stock_text += (
                    "\n⚡ Brief inventory activity "
                    "detected — checkout quickly."
                )

            else:

                stock_text += (
                    "\n⚡ Rapid inventory movement "
                    "detected."
                )

        embed.add_field(

            name="📦 Status",

            value=stock_text,

            inline=False,
        )

    # =====================================================
    # SMART CART
    # =====================================================

    if purchase_limit:

        try:

            limit_number = int(
                purchase_limit
            )

            smart_cart_text = (
                f"Detected retailer limit: "
                f"**{limit_number}**"
            )

        except (
            TypeError,
            ValueError,
        ):

            smart_cart_text = (
                f"Detected retailer limit: "
                f"**{purchase_limit}**"
            )

    else:

        smart_cart_text = (
            "Limit not detected • "
            "retailer may adjust quantity"
        )

    embed.add_field(

        name="🛒 Smart Cart",

        value=smart_cart_text,

        inline=False,
    )

    # =====================================================
    # QUICK PRODUCT LINK
    # =====================================================

    if final_url:

        embed.add_field(

            name="🔗 Quick Link",

            value=(
                f"[**Open Product**]"
                f"({final_url})"
            ),

            inline=False,
        )

    # =====================================================
    # AFFILIATE DISCLOSURE
    # =====================================================

    if affiliate_used:

        embed.add_field(

            name="Affiliate Disclosure",

            value=(
                AFFILIATE_DISCLOSURE
            ),

            inline=False,
        )

    # =====================================================
    # COMPACT FOOTER
    # =====================================================

    footer_parts = [
        "Lotus Tracker Bot",
        source_label,
    ]

    if (
        currency != "USD"
        and price is not None
    ):

        footer_parts.append(
            "USD conversion approximate"
        )

    embed.set_footer(

        text=(
            " • ".join(
                footer_parts
            )
        )
    )

    return (
        embed,
        affiliate_used,
    )