from alembic import op

import sqlalchemy as sa


# =========================================================
# STORE HEALTH MIGRATION
# PonDeX Trackers
# =========================================================


revision = (
    "20260826_01"
)

down_revision = None

branch_labels = None

depends_on = None


def upgrade():

    bind = op.get_bind()

    inspector = (
        sa.inspect(
            bind
        )
    )

    tables = (
        inspector.get_table_names()
    )

    if "stores" not in tables:

        return

    columns = {
        column[
            "name"
        ]
        for column
        in inspector.get_columns(
            "stores"
        )
    }

    if "health_status" not in columns:

        op.add_column(
            "stores",
            sa.Column(
                "health_status",
                sa.String(
                    length=50
                ),
                nullable=False,
                server_default="HEALTHY",
            ),
        )

    if "consecutive_failures" not in columns:

        op.add_column(
            "stores",
            sa.Column(
                "consecutive_failures",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "last_success_at" not in columns:

        op.add_column(
            "stores",
            sa.Column(
                "last_success_at",
                sa.DateTime(),
                nullable=True,
            ),
        )

    if "last_failure_at" not in columns:

        op.add_column(
            "stores",
            sa.Column(
                "last_failure_at",
                sa.DateTime(),
                nullable=True,
            ),
        )

    if "last_error" not in columns:

        op.add_column(
            "stores",
            sa.Column(
                "last_error",
                sa.Text(),
                nullable=True,
            ),
        )

    if "disabled_reason" not in columns:

        op.add_column(
            "stores",
            sa.Column(
                "disabled_reason",
                sa.String(
                    length=50
                ),
                nullable=True,
            ),
        )


def downgrade():

    bind = op.get_bind()

    inspector = (
        sa.inspect(
            bind
        )
    )

    tables = (
        inspector.get_table_names()
    )

    if "stores" not in tables:

        return

    columns = {
        column[
            "name"
        ]
        for column
        in inspector.get_columns(
            "stores"
        )
    }

    if "disabled_reason" in columns:

        op.drop_column(
            "stores",
            "disabled_reason",
        )

    if "last_error" in columns:

        op.drop_column(
            "stores",
            "last_error",
        )

    if "last_failure_at" in columns:

        op.drop_column(
            "stores",
            "last_failure_at",
        )

    if "last_success_at" in columns:

        op.drop_column(
            "stores",
            "last_success_at",
        )

    if "consecutive_failures" in columns:

        op.drop_column(
            "stores",
            "consecutive_failures",
        )

    if "health_status" in columns:

        op.drop_column(
            "stores",
            "health_status",
        )