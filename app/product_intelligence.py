from datetime import datetime


# =========================================================
# LOTUS PRODUCT INTELLIGENCE
# PonDeX Trackers
# Version 0.6.2
# =========================================================


PREORDER_KEYWORDS = [
    "preorder",
    "pre-order",
    "pre order",
    "reserve now",
    "reservation",
]


COMING_SOON_KEYWORDS = [
    "coming soon",
    "coming-soon",
    "releases",
    "release date",
    "available soon",
    "launching",
]


def build_search_text(
    product: dict,
) -> str:

    parts = [
        product.get("title", ""),
        product.get("vendor", ""),
        product.get("product_type", ""),
        str(product.get("tags", "")),
        product.get("body_html", ""),
    ]

    return " ".join(
        str(part)
        for part in parts
        if part
    ).lower()


def detect_preorder(
    product: dict,
) -> bool:

    searchable = build_search_text(
        product
    )

    return any(
        keyword in searchable
        for keyword in PREORDER_KEYWORDS
    )


def detect_coming_soon(
    product: dict,
) -> bool:

    searchable = build_search_text(
        product
    )

    return any(
        keyword in searchable
        for keyword in COMING_SOON_KEYWORDS
    )


def classify_product_state(
    product: dict,
    available: bool,
):

    preorder = detect_preorder(
        product
    )

    coming_soon = detect_coming_soon(
        product
    )

    if preorder and available:

        return "PREORDER_LIVE"

    if preorder and not available:

        return "PREORDER_PAGE"

    if coming_soon and not available:

        return "COMING_SOON"

    if available:

        return "STOCK_AVAILABLE"

    return "PAGE_LIVE"