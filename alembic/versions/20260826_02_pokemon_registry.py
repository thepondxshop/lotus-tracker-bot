from alembic import op
import sqlalchemy as sa


revision = "20260826_02"
down_revision = "20260826_01"

branch_labels = None
depends_on = None


def upgrade():

    bind = op.get_bind()

    inspector = sa.inspect(
        bind
    )

    if (
        "pokemon_center_products"
        in inspector.get_table_names()
    ):

        return

    op.create_table(

        "pokemon_center_products",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "region",
            sa.String(
                length=20
            ),
            nullable=False,
            server_default="US",
        ),

        sa.Column(
            "url",
            sa.Text(),
            nullable=False,
            unique=True,
        ),

        sa.Column(
            "product_code",
            sa.String(
                length=100
            ),
            nullable=True,
        ),

        sa.Column(
            "title",
            sa.String(
                length=500
            ),
            nullable=True,
        ),

        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),

        sa.Column(
            "last_state",
            sa.String(
                length=100
            ),
            nullable=True,
        ),

        sa.Column(
            "last_price",
            sa.Float(),
            nullable=True,
        ),

        sa.Column(
            "last_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),

        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),

        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            nullable=True,
        ),

        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_pokemon_center_products_region",
        "pokemon_center_products",
        [
            "region"
        ],
    )

    op.create_index(
        "ix_pokemon_center_products_product_code",
        "pokemon_center_products",
        [
            "product_code"
        ],
    )


def downgrade():

    op.drop_table(
        "pokemon_center_products"
    )