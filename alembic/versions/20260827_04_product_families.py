"""add product family pricing isolation

Revision ID: 20260827_04
Revises: 20260827_03
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_04"

down_revision = "20260827_03"

branch_labels = None

depends_on = None


def upgrade():

    # =====================================================
    # PRODUCTS
    # =====================================================

    op.add_column(

        "products",

        sa.Column(
            "product_family",
            sa.String(
                length=50
            ),
            nullable=False,
            server_default="GLOBAL_STANDARD",
        ),
    )


    op.create_index(

        op.f(
            "ix_products_product_family"
        ),

        "products",

        [
            "product_family"
        ],

        unique=False,
    )


    # =====================================================
    # PRICING REFERENCES
    # =====================================================

    op.add_column(

        "pricing_references",

        sa.Column(
            "product_family",
            sa.String(
                length=50
            ),
            nullable=False,
            server_default="GLOBAL_STANDARD",
        ),
    )


    op.create_index(

        op.f(
            "ix_pricing_references_product_family"
        ),

        "pricing_references",

        [
            "product_family"
        ],

        unique=False,
    )


    # =====================================================
    # MIGRATE EXISTING MSRP RULE KEYS
    #
    # Existing v1.0.1 rules are standard/global rules.
    #
    # Prefix their normalized key so the new resolver can
    # continue finding them without deleting any records.
    # =====================================================

    op.execute(
        """
        UPDATE pricing_references
        SET normalized_name =
            'family global_standard ' || normalized_name
        WHERE normalized_name NOT LIKE 'family %'
        """
    )


def downgrade():

    # =====================================================
    # REMOVE FAMILY PREFIX FROM EXISTING KEYS
    # =====================================================

    op.execute(
        """
        UPDATE pricing_references
        SET normalized_name =
            regexp_replace(
                normalized_name,
                '^family global_standard ',
                ''
            )
        WHERE normalized_name LIKE
            'family global_standard %'
        """
    )


    # =====================================================
    # PRICING REFERENCES
    # =====================================================

    op.drop_index(

        op.f(
            "ix_pricing_references_product_family"
        ),

        table_name=(
            "pricing_references"
        ),
    )


    op.drop_column(
        "pricing_references",
        "product_family",
    )


    # =====================================================
    # PRODUCTS
    # =====================================================

    op.drop_index(

        op.f(
            "ix_products_product_family"
        ),

        table_name=(
            "products"
        ),
    )


    op.drop_column(
        "products",
        "product_family",
    )