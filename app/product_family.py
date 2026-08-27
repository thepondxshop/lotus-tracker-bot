import re


# =========================================================
# LOTUS PRODUCT FAMILY CLASSIFIER
# PonDeX Trackers
# Version 1.0.2
#
# Product families:
#
# GLOBAL_STANDARD
# JP
# KR
# CN
# UNKNOWN
#
# IMPORTANT:
#
# Product family describes the actual PRODUCT configuration,
# not the currency or physical location of the retailer.
#
# Example:
#
# Japanese One Piece booster box sold by a US store in USD
# remains:
#
# JP
#
# It must NOT inherit GLOBAL_STANDARD MSRP.
# =========================================================


VALID_PRODUCT_FAMILIES = {

    "GLOBAL_STANDARD",
    "JP",
    "KR",
    "CN",
    "UNKNOWN",
}


# =========================================================
# NORMALIZE FAMILY
# =========================================================

def normalize_product_family(
    value,
):

    if value is None:

        return None

    value = (
        str(
            value
        )
        .strip()
        .upper()
        .replace(
            "-",
            "_",
        )
        .replace(
            " ",
            "_",
        )
    )


    aliases = {

        # -------------------------------------------------
        # Global / International
        # -------------------------------------------------

        "GLOBAL":
            "GLOBAL_STANDARD",

        "INTERNATIONAL":
            "GLOBAL_STANDARD",

        "INTERNATIONAL_ENGLISH":
            "GLOBAL_STANDARD",

        "ENGLISH":
            "GLOBAL_STANDARD",

        "ENG":
            "GLOBAL_STANDARD",

        "US":
            "GLOBAL_STANDARD",

        "USA":
            "GLOBAL_STANDARD",

        "NA":
            "GLOBAL_STANDARD",


        # -------------------------------------------------
        # Japan
        # -------------------------------------------------

        "JAPAN":
            "JP",

        "JAPANESE":
            "JP",

        "JPN":
            "JP",


        # -------------------------------------------------
        # Korea
        # -------------------------------------------------

        "KOREA":
            "KR",

        "KOREAN":
            "KR",

        "KOR":
            "KR",


        # -------------------------------------------------
        # Mainland China / Simplified Chinese
        # -------------------------------------------------

        "CHINA":
            "CN",

        "CHINESE":
            "CN",

        "SIMPLIFIED_CHINESE":
            "CN",

        "S_CHINESE":
            "CN",

        "MAINLAND_CHINA":
            "CN",
    }


    value = (
        aliases.get(
            value,
            value,
        )
    )


    if value not in VALID_PRODUCT_FAMILIES:

        return None


    return value


# =========================================================
# BUILD SEARCH TEXT
# =========================================================

def _build_product_text(
    item,
):

    values = []


    for key in (

        "title",
        "product_name",
        "product_type",
        "vendor",
        "tags",
        "description",
        "handle",
        "sku",

    ):

        value = (
            item.get(
                key
            )
        )


        if value is None:

            continue


        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):

            values.extend(

                str(
                    part
                )

                for part in value
            )


        else:

            values.append(
                str(
                    value
                )
            )


    text = (
        " ".join(
            values
        )
        .lower()
    )


    text = re.sub(
        r"\s+",
        " ",
        text,
    )


    return text.strip()


# =========================================================
# TOKEN / PHRASE MATCH
# =========================================================

def _contains_any(
    text,
    phrases,
):

    for phrase in phrases:

        if phrase in text:

            return True


    return False


# =========================================================
# JAPANESE MARKERS
# =========================================================

JP_MARKERS = [

    "japanese version",
    "japanese edition",
    "japanese booster",
    "japanese box",
    "japanese tcg",
    "japan version",
    "japan edition",
    "japan import",
    "jp version",
    "jp edition",
    "jp booster",
    "jp box",
    "jpn version",
    "jpn edition",
    "jpn booster",
    "jpn box",
    "language japanese",
    "japanese language",

    # Common Unicode markers
    "日本語",
    "日本版",
    "日版",
]


# =========================================================
# KOREAN MARKERS
# =========================================================

KR_MARKERS = [

    "korean version",
    "korean edition",
    "korean booster",
    "korean box",
    "korean tcg",
    "korea version",
    "korea edition",
    "korea import",
    "kr version",
    "kr edition",
    "kr booster",
    "kr box",
    "kor version",
    "kor edition",
    "language korean",
    "korean language",

    # Common Unicode markers
    "한국어",
    "한국판",
    "한글판",
]


# =========================================================
# SIMPLIFIED CHINESE MARKERS
# =========================================================

CN_MARKERS = [

    "simplified chinese",
    "simplified-chinese",
    "simplified chinese version",
    "simplified chinese edition",
    "simplified chinese booster",
    "simplified chinese box",
    "simplified chinese tcg",
    "mainland china",
    "china version",
    "china edition",
    "china import",
    "cn version",
    "cn edition",
    "cn booster",
    "cn box",
    "s chinese",
    "s-chinese",
    "language simplified chinese",

    # Common Chinese markers
    "简体中文",
    "简中",
    "中国大陆",
]


# =========================================================
# GLOBAL STANDARD MARKERS
#
# These are useful only when explicitly present.
# Lack of one does NOT automatically mean a product is
# foreign.
# =========================================================

GLOBAL_MARKERS = [

    "english version",
    "english edition",
    "english language",
    "international version",
    "international edition",
    "north america",
    "north american",
    "na version",
    "us version",
    "usa version",
]


# =========================================================
# DETECT PRODUCT FAMILY
# =========================================================

def detect_product_family(
    item,
    *,
    default="GLOBAL_STANDARD",
):

    """
    Detect the physical/product configuration family.

    Priority:

    1. Explicit product_family supplied by adapter
    2. Japanese markers
    3. Korean markers
    4. Simplified Chinese markers
    5. Explicit international/English markers
    6. Safe configured default

    Store currency is intentionally ignored.
    """


    if not item:

        return (
            normalize_product_family(
                default
            )
            or "UNKNOWN"
        )


    # =====================================================
    # EXPLICIT ADAPTER VALUE
    # =====================================================

    explicit = (
        normalize_product_family(

            item.get(
                "product_family"
            )
        )
    )


    if explicit:

        return explicit


    # =====================================================
    # SEARCH PRODUCT TEXT
    # =====================================================

    text = (
        _build_product_text(
            item
        )
    )


    if not text:

        return (
            normalize_product_family(
                default
            )
            or "UNKNOWN"
        )


    # =====================================================
    # FOREIGN CONFIGURATIONS FIRST
    # =====================================================

    if _contains_any(
        text,
        JP_MARKERS,
    ):

        return "JP"


    if _contains_any(
        text,
        KR_MARKERS,
    ):

        return "KR"


    if _contains_any(
        text,
        CN_MARKERS,
    ):

        return "CN"


    # =====================================================
    # EXPLICIT GLOBAL / ENGLISH CONFIGURATION
    # =====================================================

    if _contains_any(
        text,
        GLOBAL_MARKERS,
    ):

        return "GLOBAL_STANDARD"


    # =====================================================
    # DEFAULT
    #
    # For the stores currently monitored as standard
    # English/international TCG retailers, products without
    # foreign-language indicators remain GLOBAL_STANDARD.
    #
    # A future adapter can explicitly set UNKNOWN if it
    # cannot safely classify a product.
    # =====================================================

    return (
        normalize_product_family(
            default
        )
        or "UNKNOWN"
    )


# =========================================================
# GLOBAL FALLBACK POLICY
# =========================================================

def allows_global_msrp_fallback(
    product_family,
):

    """
    GLOBAL_STANDARD may use GLOBAL_STANDARD references.

    JP / KR / CN / UNKNOWN are isolated from global MSRP.
    """


    family = (
        normalize_product_family(
            product_family
        )
        or "UNKNOWN"
    )


    return (
        family
        == "GLOBAL_STANDARD"
    )