from alembic import op
import sqlalchemy as sa


revision = "20260826_04"
down_revision = "20260826_03"

branch_labels = None
depends_on = None


def upgrade():

    bind = op.get_bind()

    inspector = sa.inspect(
        bind
    )

    if (
        "pokemon_center_products"
        not in inspector.get_table_names()
    ):

        return

    existing_columns = {
        column["name"]
        for column
        in inspector.get_columns(
            "pokemon_center_products"
        )
    }

    if "scan_status" not in existing_columns:

        op.add_column(
            "pokemon_center_products",
            sa.Column(
                "scan_status",
                sa.String(
                    length=50
                ),
                nullable=False,
                server_default="NOT_SCANNED",
            ),
        )

    if "last_http_status" not in existing_columns:

        op.add_column(
            "pokemon_center_products",
            sa.Column(
                "last_http_status",
                sa.Integer(),
                nullable=True,
            ),
        )

    if "blocked_until" not in existing_columns:

        op.add_column(
            "pokemon_center_products",
            sa.Column(
                "blocked_until",
                sa.DateTime(),
                nullable=True,
            ),
        )

    if "block_count" not in existing_columns:

        op.add_column(
            "pokemon_center_products",
            sa.Column(
                "block_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "last_scan_attempt_at" not in existing_columns:

        op.add_column(
            "pokemon_center_products",
            sa.Column(
                "last_scan_attempt_at",
                sa.DateTime(),
                nullable=True,
            ),
        )


def downgrade():

    bind = op.get_bind()

    inspector = sa.inspect(
        bind
    )

    if (
        "pokemon_center_products"
        not in inspector.get_table_names()
    ):

        return

    columns = {
        column["name"]
        for column
        in inspector.get_columns(
            "pokemon_center_products"
        )
    }

    for column in [
        "last_scan_attempt_at",
        "block_count",
        "blocked_until",
        "last_http_status",
        "scan_status",
    ]:

        if column in columns:

            op.drop_column(
                "pokemon_center_products",
                column,
            )