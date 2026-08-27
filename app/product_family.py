import re


# =========================================================
# LOTUS PRODUCT FAMILY CLASSIFIER
# PonDeX Trackers
# Version 1.0.2
#
# PRODUCT FAMILY != STORE CURRENCY
#
# A Japanese product sold for USD is still JP.
# A Korean product sold for CAD is still KR.
# A Chinese product sold for EUR is still CN.
#
# Families:
#
# GLOBAL_STANDARD
# JP
# KR
# CN
# UNKNOWN
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
        str(value)
        .strip()
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {

        # Global / international
        "GLOBAL":
            "GLOBAL_STANDARD",

        "STANDARD":
            "GLOBAL_STANDARD",

        "ENGLISH":
            "GLOBAL_STANDARD",

        "ENG":
            "GLOBAL_STANDARD",

        "INTERNATIONAL":
            "GLOBAL_STANDARD",

        "INTERNATIONAL_ENGLISH":
            "GLOBAL_STANDARD",

        "NA":
            "GLOBAL_STANDARD",

        "NORTH_AMERICA":
            "GLOBAL_STANDARD",

        "US":
            "GLOBAL_STANDARD",

        "USA":
            "GLOBAL_STANDARD",

        # Japan
        "JAPAN":
            "JP",

        "JAPANESE":
            "JP",

        "JPN":
            "JP",

        # Korea
        "KOREA":
            "KR",

        "KOREAN":
            "KR",

        "KOR":
            "KR",

        # Mainland China / Simplified Chinese
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

    value = aliases.get(
        value,
        value,
    )

    if value not in VALID_PRODUCT_FAMILIES:
        return None

    return value


# =========================================================
# TEXT HELPERS
# =========================================================

def _flatten_value(
    value,
):

    if value is None:
        return ""

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):

        return " ".join(
            str(item)
            for item in value
        )

    return str(value)


def build_product_family_text(
    item,
):

    if not item:
        return ""

    fields = (

        "title",
        "product_name",
        "product_type",
        "vendor",
        "tags",
        "description",
        "body_html",
        "handle",
        "sku",
    )

    parts = []

    for field in fields:

        value = item.get(
            field
        )

        if value is None:
            continue

        parts.append(
            _flatten_value(
                value
            )
        )

    text = " ".join(
        parts
    ).lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _contains_any(
    text,
    phrases,
):

    return any(
        phrase in text
        for phrase in phrases
    )


# =========================================================
# FAMILY MARKERS
# =========================================================

JP_MARKERS = [

    "japanese version",
    "japanese edition",
    "japanese booster",
    "japanese booster box",
    "japanese display",
    "japanese card game",
    "japanese tcg",
    "japanese language",

    "japan version",
    "japan edition",
    "japan import",
    "japan booster",
    "japan booster box",

    "jp version",
    "jp edition",
    "jp booster",
    "jp booster box",
    "jp display",

    "jpn version",
    "jpn edition",
    "jpn booster",
    "jpn booster box",

    "language: japanese",
    "language japanese",

    "日本語",
    "日本版",
    "日版",
]


KR_MARKERS = [

    "korean version",
    "korean edition",
    "korean booster",
    "korean booster box",
    "korean display",
    "korean card game",
    "korean tcg",
    "korean language",

    "korea version",
    "korea edition",
    "korea import",
    "korea booster",
    "korea booster box",

    "kr version",
    "kr edition",
    "kr booster",
    "kr booster box",

    "kor version",
    "kor edition",

    "language: korean",
    "language korean",

    "한국어",
    "한국판",
    "한글판",
]


CN_MARKERS = [

    "simplified chinese",
    "simplified-chinese",
    "simplified chinese version",
    "simplified chinese edition",
    "simplified chinese booster",
    "simplified chinese booster box",
    "simplified chinese display",
    "simplified chinese tcg",

    "mainland china",
    "mainland chinese",

    "china version",
    "china edition",
    "china import",
    "china booster",
    "china booster box",

    "cn version",
    "cn edition",
    "cn booster",
    "cn booster box",

    "s chinese",
    "s-chinese",

    "language: simplified chinese",
    "language simplified chinese",

    "简体中文",
    "简中",
    "中国大陆",
]


GLOBAL_MARKERS = [

    "english version",
    "english edition",
    "english language",

    "international version",
    "international edition",

    "north american version",
    "north america version",

    "na version",
    "us version",
    "usa version",

    "language: english",
    "language english",
]


# =========================================================
# AMBIGUOUS IMPORT MARKERS
#
# If Lotus knows something is imported but cannot safely
# determine which configuration it is, do NOT guess global.
# =========================================================

AMBIGUOUS_IMPORT_MARKERS = [

    "import edition",
    "import version",
    "import booster",
    "import booster box",

    "asian version",
    "asia version",
    "asia edition",

    "overseas edition",
    "overseas version",

    "foreign language",
]


# =========================================================
# DETECT PRODUCT FAMILY
# =========================================================

def detect_product_family(
    item,
    *,
    default=None,
):

    """
    Determine the actual product configuration.

    Currency is deliberately ignored.

    Priority:
      1. Explicit adapter value
      2. JP
      3. KR
      4. CN
      5. Explicit GLOBAL_STANDARD
      6. Ambiguous import -> UNKNOWN
      7. Optional trusted-store default
      8. UNKNOWN
    """

    if not item:

        return (
            normalize_product_family(
                default
            )
            or "UNKNOWN"
        )

    # -----------------------------------------------------
    # Explicit adapter metadata wins.
    # -----------------------------------------------------

    explicit = (
        normalize_product_family(
            item.get(
                "product_family"
            )
        )
    )

    if explicit:
        return explicit

    text = (
        build_product_family_text(
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

    # -----------------------------------------------------
    # Foreign configurations first.
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Explicit global-standard evidence.
    # -----------------------------------------------------

    if _contains_any(
        text,
        GLOBAL_MARKERS,
    ):
        return "GLOBAL_STANDARD"

    # -----------------------------------------------------
    # Known import, unknown configuration.
    # -----------------------------------------------------

    if _contains_any(
        text,
        AMBIGUOUS_IMPORT_MARKERS,
    ):
        return "UNKNOWN"

    # -----------------------------------------------------
    # Trusted store default.
    #
    # The monitor can pass GLOBAL_STANDARD for a normal
    # domestic/international English retailer.
    #
    # Otherwise we stay UNKNOWN.
    # -----------------------------------------------------

    normalized_default = (
        normalize_product_family(
            default
        )
    )

    if normalized_default:
        return normalized_default

    return "UNKNOWN"


# =========================================================
# GLOBAL MSRP FALLBACK POLICY
# =========================================================

def allows_global_msrp_fallback(
    product_family,
):

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


# =========================================================
# MSRP SAFETY
# =========================================================

def is_isolated_family(
    product_family,
):

    family = (
        normalize_product_family(
            product_family
        )
        or "UNKNOWN"
    )

    return family in {
        "JP",
        "KR",
        "CN",
        "UNKNOWN",
    }