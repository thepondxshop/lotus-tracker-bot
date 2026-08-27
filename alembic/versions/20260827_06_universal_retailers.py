"""add universal retailer product metadata

Revision ID: 20260827_06
Revises: 20260827_05
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_06"

down_revision = "20260827_05"

branch_labels = None

depends_on = None


# =========================================================
# UPGRADE
# =========================================================

def upgrade():

    # =====================================================
    # UNIVERSAL RETAILER PRODUCT IDENTIFIERS
    #
    # external_product_id:
    #     Retailer's own product/catalog identifier.
    #
    # offer_id:
    #     Purchasable offer / SKU / variation identifier.
    #
    # platform_data:
    #     Optional serialized adapter metadata.
    #
    # Shopify variant_id remains untouched and continues
    # to be used for Shopify Smart Cart.
    # =====================================================

    op.add_column(

        "store_products",

        sa.Column(
            "external_product_id",
            sa.String(
                length=255
            ),
            nullable=True,
        ),
    )

    op.add_column(

        "store_products",

        sa.Column(
            "offer_id",
            sa.String(
                length=255
            ),
            nullable=True,
        ),
    )

    op.add_column(

        "store_products",

        sa.Column(
            "platform_data",
            sa.Text(),
            nullable=True,
        ),
    )


    # =====================================================
    # INDEXES
    # =====================================================

    op.create_index(

        "ix_store_products_external_product_id",

        "store_products",

        [
            "external_product_id",
        ],

        unique=False,
    )

    op.create_index(

        "ix_store_products_offer_id",

        "store_products",

        [
            "offer_id",
        ],

        unique=False,
    )


    # =====================================================
    # PRICING REFERENCE UNIQUE CONSTRAINT
    #
    # Old:
    #
    # game
    # normalized_name
    # region
    # kind
    #
    # New:
    #
    # game
    # normalized_name
    # region
    # kind
    # scope_type
    # product_family
    #
    # This permits separate MSRP rules such as:
    #
    # One Piece Booster Box GLOBAL_STANDARD
    # One Piece Booster Box JP
    # One Piece Booster Box KR
    # One Piece Booster Box CN
    # =====================================================

    op.drop_constraint(

        "uq_pricing_reference_product_region_kind",

        "pricing_references",

        type_="unique",
    )

    op.create_unique_constraint(

        "uq_pricing_reference_scope_family",

        "pricing_references",

        [
            "game",
            "normalized_name",
            "region",
            "kind",
            "scope_type",
            "product_family",
        ],
    )


# =========================================================
# DOWNGRADE
# =========================================================

def downgrade():

    # =====================================================
    # RESTORE OLD PRICING CONSTRAINT
    # =====================================================

    op.drop_constraint(

        "uq_pricing_reference_scope_family",

        "pricing_references",

        type_="unique",
    )

    op.create_unique_constraint(

        "uq_pricing_reference_product_region_kind",

        "pricing_references",

        [
            "game",
            "normalized_name",
            "region",
            "kind",
        ],
    )


    # =====================================================
    # REMOVE UNIVERSAL RETAILER INDEXES
    # =====================================================

    op.drop_index(

        "ix_store_products_offer_id",

        table_name="store_products",
    )

    op.drop_index(

        "ix_store_products_external_product_id",

        table_name="store_products",
    )


    # =====================================================
    # REMOVE UNIVERSAL RETAILER COLUMNS
    # =====================================================

    op.drop_column(

        "store_products",

        "platform_data",
    )

    op.drop_column(

        "store_products",

        "offer_id",
    )

    op.drop_column(

        "store_products",

        "external_product_id",
    )