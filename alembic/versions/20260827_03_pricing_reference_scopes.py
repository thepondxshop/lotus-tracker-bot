"""add pricing reference scopes

Revision ID: 20260827_03
Revises: 20260827_02
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


# =========================================================
# ALEMBIC REVISION
# =========================================================

revision = "20260827_03"

down_revision = "20260827_02"

branch_labels = None

depends_on = None


# =========================================================
# UPGRADE
# =========================================================

def upgrade():

    op.add_column(

        "pricing_references",

        sa.Column(
            "scope_type",
            sa.String(
                length=50
            ),
            nullable=False,
            server_default="EXACT_PRODUCT",
        ),
    )

    op.add_column(

        "pricing_references",

        sa.Column(
            "match_value",
            sa.String(
                length=500
            ),
            nullable=True,
        ),
    )

    op.create_index(

        op.f(
            "ix_pricing_references_scope_type"
        ),

        "pricing_references",

        [
            "scope_type"
        ],

        unique=False,
    )

    op.create_index(

        op.f(
            "ix_pricing_references_match_value"
        ),

        "pricing_references",

        [
            "match_value"
        ],

        unique=False,
    )


# =========================================================
# DOWNGRADE
# =========================================================

def downgrade():

    op.drop_index(

        op.f(
            "ix_pricing_references_match_value"
        ),

        table_name=(
            "pricing_references"
        ),
    )

    op.drop_index(

        op.f(
            "ix_pricing_references_scope_type"
        ),

        table_name=(
            "pricing_references"
        ),
    )

    op.drop_column(
        "pricing_references",
        "match_value",
    )

    op.drop_column(
        "pricing_references",
        "scope_type",
    )