"""add pricing references

Revision ID: 20260827_02
Revises: 20260827_01
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.

revision = "20260827_02"

down_revision = "20260827_01"

branch_labels = None

depends_on = None


def upgrade():

    op.create_table(

        "pricing_references",

        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),

        sa.Column(
            "game",
            sa.String(
                length=100
            ),
            nullable=False,
        ),

        sa.Column(
            "product_name",
            sa.String(
                length=500
            ),
            nullable=False,
        ),

        sa.Column(
            "normalized_name",
            sa.String(
                length=500
            ),
            nullable=False,
        ),

        sa.Column(
            "amount",
            sa.Float(),
            nullable=False,
        ),

        sa.Column(
            "currency",
            sa.String(
                length=10
            ),
            nullable=False,
        ),

        sa.Column(
            "source",
            sa.String(
                length=500
            ),
            nullable=False,
        ),

        sa.Column(
            "confidence",
            sa.String(
                length=20
            ),
            nullable=False,
        ),

        sa.Column(
            "kind",
            sa.String(
                length=50
            ),
            nullable=False,
        ),

        sa.Column(
            "region",
            sa.String(
                length=50
            ),
            nullable=False,
        ),

        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.PrimaryKeyConstraint(
            "id"
        ),

        sa.UniqueConstraint(
            "game",
            "normalized_name",
            "region",
            "kind",
            name=(
                "uq_pricing_reference_"
                "product_region_kind"
            ),
        ),
    )


    op.create_index(
        op.f(
            "ix_pricing_references_game"
        ),
        "pricing_references",
        [
            "game"
        ],
        unique=False,
    )


    op.create_index(
        op.f(
            "ix_pricing_references_normalized_name"
        ),
        "pricing_references",
        [
            "normalized_name"
        ],
        unique=False,
    )


    op.create_index(
        op.f(
            "ix_pricing_references_region"
        ),
        "pricing_references",
        [
            "region"
        ],
        unique=False,
    )


    op.create_index(
        op.f(
            "ix_pricing_references_active"
        ),
        "pricing_references",
        [
            "active"
        ],
        unique=False,
    )


def downgrade():

    op.drop_index(
        op.f(
            "ix_pricing_references_active"
        ),
        table_name="pricing_references",
    )

    op.drop_index(
        op.f(
            "ix_pricing_references_region"
        ),
        table_name="pricing_references",
    )

    op.drop_index(
        op.f(
            "ix_pricing_references_normalized_name"
        ),
        table_name="pricing_references",
    )

    op.drop_index(
        op.f(
            "ix_pricing_references_game"
        ),
        table_name="pricing_references",
    )

    op.drop_table(
        "pricing_references"
    )