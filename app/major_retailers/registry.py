"""Major-retailer registry for Lotus Step 6K-1A2."""

from __future__ import annotations

from typing import Type

from .base import MajorRetailerAdapter, MajorRetailerDefinition

VERSION = "1.1.1"

_DEFINITIONS: dict[str, MajorRetailerDefinition] = {}
_ADAPTERS: dict[str, Type[MajorRetailerAdapter]] = {}


def normalize_retailer_key(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "target.com": "target",
        "walmart.com": "walmart",
        "bestbuy": "best_buy",
        "best buy": "best_buy",
        "best-buy": "best_buy",
        "bestbuy.com": "best_buy",
        "game stop": "gamestop",
        "game-stop": "gamestop",
        "gamestop.com": "gamestop",
        "premium bandai": "premium_bandai",
        "premium-bandai": "premium_bandai",
        "p bandai": "premium_bandai",
        "p-bandai": "premium_bandai",
        "p-bandai.com": "premium_bandai",
        "p-bandai.com/us": "premium_bandai",
        "www.p-bandai.com": "premium_bandai",
        "www.p-bandai.com/us": "premium_bandai",
        "box lunch": "boxlunch",
        "box-lunch": "boxlunch",
        "box_lunch": "boxlunch",
        "boxlunch.com": "boxlunch",
        "hot topic": "hot_topic",
        "hot-topic": "hot_topic",
        "hottopic": "hot_topic",
        "hottopic.com": "hot_topic",
        "costco.com": "costco",
        "sam's club": "sams_club",
        "sams club": "sams_club",
        "sam's": "sams_club",
        "sams": "sams_club",
        "samsclub.com": "sams_club",
        "amazon": "amazon_us",
        "amazon us": "amazon_us",
        "amazon.com": "amazon_us",
        "amazon japan": "amazon_jp",
        "amazon jp": "amazon_jp",
        "amazon.co.jp": "amazon_jp",
    }
    return aliases.get(raw, raw.replace("-", "_").replace(" ", "_"))


def register_major_retailer_definition(definition: MajorRetailerDefinition) -> MajorRetailerDefinition:
    if not isinstance(definition, MajorRetailerDefinition):
        raise TypeError("definition must be MajorRetailerDefinition")
    key = normalize_retailer_key(definition.key)
    if not key:
        raise ValueError("Retailer definition key is required")
    _DEFINITIONS[key] = MajorRetailerDefinition(
        key=key,
        display_name=definition.display_name,
        domain=definition.domain,
        region=definition.region,
        enabled=bool(definition.enabled),
        affiliate_provider=definition.affiliate_provider,
        notes=definition.notes,
    )
    return _DEFINITIONS[key]


def get_major_retailer_definition(key: str) -> MajorRetailerDefinition | None:
    return _DEFINITIONS.get(normalize_retailer_key(key))


def list_major_retailer_definitions() -> list[MajorRetailerDefinition]:
    return sorted(_DEFINITIONS.values(), key=lambda item: item.display_name.lower())


def register_major_retailer_adapter(key: str, adapter_class: Type[MajorRetailerAdapter]):
    normalized = normalize_retailer_key(key)
    if not isinstance(adapter_class, type) or not issubclass(adapter_class, MajorRetailerAdapter):
        raise TypeError("adapter_class must inherit MajorRetailerAdapter")
    if normalized not in _DEFINITIONS:
        raise ValueError(f"Unknown major retailer definition: {normalized}")
    _ADAPTERS[normalized] = adapter_class
    return adapter_class


def major_retailer_adapter(key: str):
    def decorator(adapter_class: Type[MajorRetailerAdapter]):
        return register_major_retailer_adapter(key, adapter_class)
    return decorator


def get_major_retailer_adapter_class(key: str):
    return _ADAPTERS.get(normalize_retailer_key(key))


def list_registered_major_retailer_adapters() -> list[str]:
    return sorted(_ADAPTERS.keys())


def build_major_retailer_adapter(key: str) -> MajorRetailerAdapter:
    normalized = normalize_retailer_key(key)
    definition = get_major_retailer_definition(normalized)
    if definition is None:
        raise ValueError(f"Unknown major retailer '{normalized}'.")
    adapter_class = get_major_retailer_adapter_class(normalized)
    if adapter_class is None:
        raise ValueError(f"No major retailer adapter registered for '{normalized}'.")
    return adapter_class(definition)
