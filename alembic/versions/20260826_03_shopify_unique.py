from alembic import op

import sqlalchemy as sa


# =========================================================
# LOTUS SHOPIFY DUPLICATE REPAIR
# Version 0.7.4a
#
# Repairs duplicate store_products rows.
#
# Then guarantees:
#
#     one store + one product URL = one StoreProduct
# =========================================================


revision = "20260826_03"

down_revision = "20260826_02"

branch_labels = None

depends_on = None


# =========================================================
# UPGRADE
# =========================================================

def upgrade():

    bind = op.get_bind()

    inspector = sa.inspect(
        bind
    )

    tables = set(
        inspector.get_table_names()
    )

    if "store_products" not in tables:

        return

    # =====================================================
    # STEP 1
    # Find duplicate StoreProduct rows.
    #
    # keeper_id = oldest row for each store/url combination
    # =====================================================

    duplicate_groups = bind.execute(

        sa.text(
            """
            SELECT
                store_id,
                url,
                MIN(id) AS keeper_id
            FROM store_products
            GROUP BY
                store_id,
                url
            HAVING COUNT(*) > 1
            """
        )
    ).mappings().all()

    print(
        (
            "SHOPIFY DUPLICATE MIGRATION | "
            f"Groups={len(duplicate_groups)}"
        )
    )

    # =====================================================
    # STEP 2
    # For every duplicate group:
    #
    # - preserve one row
    # - move PriceHistory onto the keeper
    # - remove duplicate StoreProduct rows
    # =====================================================

    for group in duplicate_groups:

        store_id = (
            group[
                "store_id"
            ]
        )

        url = (
            group[
                "url"
            ]
        )

        keeper_id = (
            group[
                "keeper_id"
            ]
        )

        duplicate_ids = bind.execute(

            sa.text(
                """
                SELECT id
                FROM store_products
                WHERE
                    store_id = :store_id
                    AND url = :url
                    AND id <> :keeper_id
                ORDER BY id
                """
            ),

            {
                "store_id":
                    store_id,

                "url":
                    url,

                "keeper_id":
                    keeper_id,
            },
        ).scalars().all()

        if not duplicate_ids:

            continue

        # -------------------------------------------------
        # Price history points at store_product_id.
        #
        # Move those records before deleting duplicates.
        # -------------------------------------------------

        if "price_history" in tables:

            for duplicate_id in duplicate_ids:

                bind.execute(

                    sa.text(
                        """
                        UPDATE price_history
                        SET store_product_id = :keeper_id
                        WHERE store_product_id = :duplicate_id
                        """
                    ),

                    {
                        "keeper_id":
                            keeper_id,

                        "duplicate_id":
                            duplicate_id,
                    },
                )

        # -------------------------------------------------
        # Prefer the newest useful state from duplicates.
        #
        # This prevents cleanup from unnecessarily losing
        # stock/price information.
        # -------------------------------------------------

        newest = bind.execute(

            sa.text(
                """
                SELECT
                    price,
                    currency,
                    in_stock,
                    status,
                    sku,
                    last_seen_at
                FROM store_products
                WHERE
                    store_id = :store_id
                    AND url = :url
                ORDER BY
                    last_seen_at DESC NULLS LAST,
                    id DESC
                LIMIT 1
                """
            ),

            {
                "store_id":
                    store_id,

                "url":
                    url,
            },
        ).mappings().first()

        if newest:

            bind.execute(

                sa.text(
                    """
                    UPDATE store_products
                    SET
                        price = :price,
                        currency = :currency,
                        in_stock = :in_stock,
                        status = :status,
                        sku = COALESCE(:sku, sku),
                        last_seen_at = COALESCE(
                            :last_seen_at,
                            last_seen_at
                        )
                    WHERE id = :keeper_id
                    """
                ),

                {
                    "price":
                        newest[
                            "price"
                        ],

                    "currency":
                        newest[
                            "currency"
                        ],

                    "in_stock":
                        newest[
                            "in_stock"
                        ],

                    "status":
                        newest[
                            "status"
                        ],

                    "sku":
                        newest[
                            "sku"
                        ],

                    "last_seen_at":
                        newest[
                            "last_seen_at"
                        ],

                    "keeper_id":
                        keeper_id,
                },
            )

        # -------------------------------------------------
        # Delete duplicate rows.
        # -------------------------------------------------

        for duplicate_id in duplicate_ids:

            bind.execute(

                sa.text(
                    """
                    DELETE FROM store_products
                    WHERE id = :duplicate_id
                    """
                ),

                {
                    "duplicate_id":
                        duplicate_id,
                },
            )

        print(
            (
                "SHOPIFY DUPLICATES REPAIRED | "
                f"StoreID={store_id} | "
                f"Keeper={keeper_id} | "
                f"Removed={len(duplicate_ids)}"
            )
        )

    # =====================================================
    # STEP 3
    # Add permanent uniqueness protection.
    # =====================================================

    inspector = sa.inspect(
        bind
    )

    constraints = {
        constraint[
            "name"
        ]
        for constraint
        in inspector.get_unique_constraints(
            "store_products"
        )
        if constraint.get(
            "name"
        )
    }

    indexes = {
        index[
            "name"
        ]
        for index
        in inspector.get_indexes(
            "store_products"
        )
        if index.get(
            "name"
        )
    }

    constraint_name = (
        "uq_store_products_store_url"
    )

    if (
        constraint_name
        not in constraints
        and constraint_name
        not in indexes
    ):

        op.create_unique_constraint(
            constraint_name,
            "store_products",
            [
                "store_id",
                "url",
            ],
        )


# =========================================================
# DOWNGRADE
# =========================================================

def downgrade():

    bind = op.get_bind()

    inspector = sa.inspect(
        bind
    )

    if (
        "store_products"
        not in inspector.get_table_names()
    ):

        return

    constraints = {
        constraint[
            "name"
        ]
        for constraint
        in inspector.get_unique_constraints(
            "store_products"
        )
        if constraint.get(
            "name"
        )
    }

    if (
        "uq_store_products_store_url"
        in constraints
    ):

        op.drop_constraint(
            "uq_store_products_store_url",
            "store_products",
            type_="unique",
        )