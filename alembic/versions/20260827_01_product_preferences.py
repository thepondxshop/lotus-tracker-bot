from alembic import op
import sqlalchemy as sa


revision = "20260827_01"
down_revision = "20260826_04"

branch_labels = None
depends_on = None


def upgrade():

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(
        inspector.get_table_names()
    )

    # =====================================================
    # USER PRODUCT PREFERENCES
    # =====================================================

    if (
        "user_product_preferences"
        not in tables
    ):

        op.create_table(
            "user_product_preferences",

            sa.Column(
                "id",
                sa.Integer(),
                primary_key=True,
                autoincrement=True,
            ),

            sa.Column(
                "discord_user_id",
                sa.BigInteger(),
                nullable=False,
            ),

            sa.Column(
                "game",
                sa.String(length=150),
                nullable=False,
            ),

            sa.Column(
                "product_category",
                sa.String(length=50),
                nullable=False,
            ),

            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),

            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),

            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),

            sa.UniqueConstraint(
                "discord_user_id",
                "game",
                "product_category",
                name="uq_user_product_preference",
            ),
        )

        op.create_index(
            "ix_user_product_preferences_discord_user_id",
            "user_product_preferences",
            ["discord_user_id"],
        )

        op.create_index(
            "ix_user_product_preferences_game",
            "user_product_preferences",
            ["game"],
        )

        op.create_index(
            "ix_user_product_preferences_product_category",
            "user_product_preferences",
            ["product_category"],
        )


    # =====================================================
    # PRODUCTS
    # =====================================================

    if "products" in tables:

        product_columns = {
            column["name"]
            for column
            in inspector.get_columns(
                "products"
            )
        }

        if (
            "product_category"
            not in product_columns
        ):

            op.add_column(
                "products",
                sa.Column(
                    "product_category",
                    sa.String(length=50),
                    nullable=False,
                    server_default="UNKNOWN",
                ),
            )

            op.create_index(
                "ix_products_product_category",
                "products",
                ["product_category"],
            )


    # =====================================================
    # STORE PRODUCTS
    # =====================================================

    if "store_products" in tables:

        store_product_columns = {
            column["name"]
            for column
            in inspector.get_columns(
                "store_products"
            )
        }

        if (
            "variant_id"
            not in store_product_columns
        ):

            op.add_column(
                "store_products",
                sa.Column(
                    "variant_id",
                    sa.String(length=255),
                    nullable=True,
                ),
            )

            op.create_index(
                "ix_store_products_variant_id",
                "store_products",
                ["variant_id"],
            )

        if (
            "purchase_limit"
            not in store_product_columns
        ):

            op.add_column(
                "store_products",
                sa.Column(
                    "purchase_limit",
                    sa.Integer(),
                    nullable=True,
                ),
            )


def downgrade():

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(
        inspector.get_table_names()
    )

    if (
        "store_products"
        in tables
    ):

        columns = {
            column["name"]
            for column
            in inspector.get_columns(
                "store_products"
            )
        }

        if (
            "purchase_limit"
            in columns
        ):

            op.drop_column(
                "store_products",
                "purchase_limit",
            )

        if (
            "variant_id"
            in columns
        ):

            try:
                op.drop_index(
                    "ix_store_products_variant_id",
                    table_name="store_products",
                )
            except Exception:
                pass

            op.drop_column(
                "store_products",
                "variant_id",
            )

    if (
        "products"
        in tables
    ):

        columns = {
            column["name"]
            for column
            in inspector.get_columns(
                "products"
            )
        }

        if (
            "product_category"
            in columns
        ):

            try:
                op.drop_index(
                    "ix_products_product_category",
                    table_name="products",
                )
            except Exception:
                pass

            op.drop_column(
                "products",
                "product_category",
            )

    if (
        "user_product_preferences"
        in tables
    ):

        op.drop_table(
            "user_product_preferences"
        )