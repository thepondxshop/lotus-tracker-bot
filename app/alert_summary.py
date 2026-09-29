"""A1 notification text. Uses the queued event only; no lookups or FX calls."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata

VERSION = "1.0.6-A1"
SUMMARY_LIMIT = 360
CONTENT_LIMIT = 2000

LABELS = {
    "DISCOVERED": "📡 NEW LISTING", "PAGE_LIVE": "🔵 PAGE LIVE",
    "COMING_SOON": "🟡 COMING SOON", "PREORDER_LIVE": "🟣 PREORDER LIVE",
    "STOCK_AVAILABLE": "🟢 IN STOCK", "RESTOCK": "🚨 RESTOCK",
    "SOLD_OUT": "🔴 SOLD OUT", "PRICE_DROP": "🔥 PRICE DROP",
    "PRICE_INCREASE": "📈 PRICE INCREASE", "PRICE_ERROR": "⚠️ POSSIBLE PRICE ERROR",
    "INVENTORY_FLICKER": "⚡ INVENTORY FLICKER",
    "RELEASE_DATE_CHANGED": "📅 RELEASE DATE CHANGED",
    "QUEUE_DETECTED": "🚨 QUEUE DETECTED", "QUEUE_ACTIVE": "🚨 QUEUE LIVE",
    "QUEUE_CLEARED": "✅ QUEUE CLEARED",
}


def _clean(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    # Catalog strings are not mention instructions. Remove raw Discord
    # syntax and formatting before placing them ahead of eligible mentions.
    text = re.sub(r"<[^>]*>", " ", text)
    text = text.replace("@", "＠")
    text = re.sub(r"[*_`|~<>]", "", text)
    text = "".join(c for c in text if not unicodedata.category(c).startswith("C") or c.isspace())
    return " ".join(text.split())


def _short(value, limit):
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def _content_size(value):
    # Conservative for clients which count emoji as UTF-16 surrogate pairs.
    return len(value.encode("utf-16-le")) // 2


def _price(event):
    try:
        price = Decimal(str(event.get("price")))
        if not price.is_finite() or price < 0 or price > Decimal("999999999999"):
            return "Price unavailable"
    except (InvalidOperation, TypeError, ValueError):
        return "Price unavailable"
    currency = _clean(event.get("currency") or "USD").upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return "Price unavailable"
    symbol = {"USD": "$", "CAD": "C$", "AUD": "A$", "GBP": "£", "EUR": "€", "JPY": "¥"}.get(currency, "")
    return f"{symbol}{price:,.2f} {currency}"


def build_notification_summary(event):
    label = LABELS.get(str(event.get("event_type") or "").upper(), "📡 PRODUCT UPDATE")
    title = _short(_clean(event.get("product_name")) or "Unknown product", 190)
    store = _short(_clean(event.get("store_name")) or "Unknown store", 65)
    price = "" if str(event.get("event_type") or "").startswith("QUEUE_") else f" — {_price(event)}"
    return _short(f"{label} • {title}{price} • {store}", SUMMARY_LIMIT)


def build_notification_chunks(event, members):
    """Every recipient chunk includes context; the worker embeds only once.

Returns content and explicit recipient IDs (at most 100 per message).
Unknown catalog strings can never add recipients to allowed_mentions.
"""
    summary = build_notification_summary(event)
    chunks, ids, mentions, seen = [], [], [], set()
    for member in members:
        member_id = int(member.id)
        if member_id <= 0 or member_id in seen:
            continue
        seen.add(member_id)
        mention = f"<@{member_id}>"
        candidate = summary + "\n" + " ".join(mentions + [mention])
        if mentions and (_content_size(candidate) > CONTENT_LIMIT or len(ids) >= 100):
            chunks.append((summary + "\n" + " ".join(mentions), ids))
            mentions, ids = [], []
        mentions.append(mention)
        ids.append(member_id)
    if mentions:
        chunks.append((summary + "\n" + " ".join(mentions), ids))
    return chunks or [(summary, [])]
