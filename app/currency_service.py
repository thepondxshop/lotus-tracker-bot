import time

import aiohttp


# =========================================================
# LOTUS CURRENCY SERVICE
# PonDeX Trackers
# Version 0.7.7
#
# Native currency preservation
# Approximate USD conversion
# Cached exchange rates
# =========================================================


FRANKFURTER_BASE_URL = (
    "https://api.frankfurter.dev/v2/rate"
)


# =========================================================
# CACHE
#
# Exchange rates do not need to be fetched on every alert.
# Keep them for 30 minutes.
# =========================================================

CACHE_SECONDS = 1800

_rate_cache = {}


# =========================================================
# CURRENCY SYMBOLS
# =========================================================

CURRENCY_SYMBOLS = {

    "USD":
        "US$",

    "CAD":
        "C$",

    "GBP":
        "£",

    "EUR":
        "€",

    "JPY":
        "¥",

    "AUD":
        "A$",

    "NZD":
        "NZ$",

    "CHF":
        "CHF ",

    "HKD":
        "HK$",

    "SGD":
        "S$",
}


# =========================================================
# FORMAT PRICE
# =========================================================

def format_currency(
    amount,
    currency,
):

    if amount is None:

        return None

    currency = (
        currency
        or "USD"
    ).upper()

    symbol = (
        CURRENCY_SYMBOLS.get(
            currency,
            ""
        )
    )

    try:

        numeric = float(
            amount
        )

    except (
        TypeError,
        ValueError,
    ):

        return (
            f"{amount} {currency}"
        )

    # JPY generally does not use decimal cents.

    if currency == "JPY":

        return (
            f"{symbol}"
            f"{numeric:,.0f} "
            f"{currency}"
        )

    return (
        f"{symbol}"
        f"{numeric:,.2f} "
        f"{currency}"
    )


# =========================================================
# GET RATE
# =========================================================

async def get_exchange_rate(
    from_currency,
    to_currency="USD",
):

    from_currency = (
        from_currency
        or "USD"
    ).upper()

    to_currency = (
        to_currency
        or "USD"
    ).upper()

    if (
        from_currency
        == to_currency
    ):

        return 1.0

    cache_key = (
        from_currency,
        to_currency,
    )

    now = (
        time.monotonic()
    )

    cached = (
        _rate_cache.get(
            cache_key
        )
    )

    if cached:

        rate, stored_at = (
            cached
        )

        if (
            now
            - stored_at
            < CACHE_SECONDS
        ):

            return rate

    url = (
        f"{FRANKFURTER_BASE_URL}/"
        f"{from_currency}/"
        f"{to_currency}"
    )

    timeout = (
        aiohttp.ClientTimeout(
            total=10
        )
    )

    try:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url
            ) as response:

                if response.status != 200:

                    print(
                        (
                            "FX RATE ERROR | "
                            f"{from_currency}->"
                            f"{to_currency} | "
                            f"HTTP={response.status}"
                        )
                    )

                    return None

                data = (
                    await response.json(
                        content_type=None
                    )
                )

        # Frankfurter v2 /rate returns an object containing
        # the numeric rate.

        rate = (
            data.get(
                "rate"
            )
        )

        if rate is None:

            print(
                (
                    "FX RATE ERROR | "
                    f"{from_currency}->"
                    f"{to_currency} | "
                    "Missing rate field"
                )
            )

            return None

        rate = float(
            rate
        )

        _rate_cache[
            cache_key
        ] = (
            rate,
            now,
        )

        return rate

    except Exception as error:

        print(
            (
                "FX RATE ERROR | "
                f"{from_currency}->"
                f"{to_currency} | "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return None


# =========================================================
# CONVERT
# =========================================================

async def convert_currency(
    amount,
    from_currency,
    to_currency="USD",
):

    if amount is None:

        return None

    try:

        numeric_amount = float(
            amount
        )

    except (
        TypeError,
        ValueError,
    ):

        return None

    rate = (
        await get_exchange_rate(
            from_currency,
            to_currency,
        )
    )

    if rate is None:

        return None

    return (
        numeric_amount
        * rate
    )