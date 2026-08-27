"""add product family alert preferences

Revision ID: 20260827_05
Revises: 20260827_04
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_05"

down_revision = "20260827_04"

branch_labels = None

depends_on = None


# =========================================================
# UPGRADE
# =========================================================

def upgrade():

    op.create_table(

        "user_product_family_preferences",

        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),

        sa.Column(
            "discord_user_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "game",
            sa.String(
                length=150
            ),
            nullable=False,
        ),

        sa.Column(
            "product_family",
            sa.String(
                length=50
            ),
            nullable=False,
        ),

        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
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
            "discord_user_id",
            "game",
            "product_family",
            name=(
                "uq_user_product_family_preference"
            ),
        ),
    )


    op.create_index(

        op.f(
            "ix_user_product_family_preferences_discord_user_id"
        ),

        "user_product_family_preferences",

        [
            "discord_user_id"
        ],

        unique=False,
    )


    op.create_index(

        op.f(
            "ix_user_product_family_preferences_game"
        ),

        "user_product_family_preferences",

        [
            "game"
        ],

        unique=False,
    )


    op.create_index(

        op.f(
            "ix_user_product_family_preferences_product_family"
        ),

        "user_product_family_preferences",

        [
            "product_family"
        ],

        unique=False,
    )


# =========================================================
# DOWNGRADE
# =========================================================

def downgrade():

    op.drop_index(

        op.f(
            "ix_user_product_family_preferences_product_family"
        ),

        table_name=(
            "user_product_family_preferences"
        ),
    )


    op.drop_index(

        op.f(
            "ix_user_product_family_preferences_game"
        ),

        table_name=(
            "user_product_family_preferences"
        ),
    )


    op.drop_index(

        op.f(
            "ix_user_product_family_preferences_discord_user_id"
        ),

        table_name=(
            "user_product_family_preferences"
        ),
    )


    op.drop_table(
        "user_product_family_preferences"
    )