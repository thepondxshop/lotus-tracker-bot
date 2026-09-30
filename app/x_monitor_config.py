"""Disabled-by-default inbound X monitoring settings. No publishing code."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import os
import re

VERSION = "1.0.0-XM1"
DEFAULT_HANDLES = (
    "AzukiTCG", "PalworldOCG_EN", "BN_pokemon", "Laurier_News",
    "OPMerchandise", "CeladonCA", "Lovery_lono", "DisTrackers",
    "AndyCollectz", "Sneaky_Steals", "OPTCGAlert", "iamapokeMOM",
)
PAGE_SIZE = 10
# Conservative estimates in thousandths of a US dollar. Verify console rates
# before enabling. Expanded users are included; no billing dedup is assumed.
POST_MILLS = 5
USER_MILLS = 10


def parse_handles(value):
    result = []
    for item in re.split(r"[\s,]+", value.strip()):
        if not item:
            continue
        item = re.sub(r"^https://(?:www\.)?(?:x|twitter)\.com/", "", item)
        item = item.strip("/@")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", item):
            raise ValueError("X_MONITOR_HANDLES contains an invalid handle.")
        if item.lower() not in {x.lower() for x in result}:
            result.append(item)
    if not result or len(result) > 20:
        raise ValueError("X_MONITOR_HANDLES must contain 1 to 20 handles.")
    return tuple(result)


def make_query(handles):
    query = "(" + " OR ".join("from:" + h for h in handles) + ") -is:retweet -is:reply"
    if len(query) > 512:
        raise ValueError("X monitoring query exceeds 512 characters.")
    return query


def number(env, name, default, minimum, maximum):
    try:
        value = int(env.get(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be between {minimum} and {maximum}.") from None


def money(env, name):
    try:
        value = Decimal(env.get(name, "0"))
        if not value.is_finite() or not 0 <= value <= 10000:
            raise ValueError
        return int(value * 1000)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} must be a nonnegative dollar amount up to 10000.") from None


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    bearer: str = field(default="", repr=False)
    channel_id: int = 0
    role_id: int = 0
    handles: tuple = DEFAULT_HANDLES
    interval: int = 120
    daily_mills: int = 0
    monthly_mills: int = 0
    daily_requests: int = 1000

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        handles = parse_handles(env.get("X_MONITOR_HANDLES", ",".join(DEFAULT_HANDLES)))
        make_query(handles)
        return cls(
            enabled=env.get("X_MONITOR_ENABLED", "false").strip().lower() == "true",
            bearer=env.get("X_BEARER_TOKEN", "").strip(),
            channel_id=number(env, "CHANNEL_X_MONITOR_ADMIN", 0, 0, 2**64 - 1),
            role_id=number(env, "ROLE_X_MONITOR_ADMIN", 0, 0, 2**64 - 1),
            handles=handles,
            interval=number(env, "X_MONITOR_POLL_SECONDS", 120, 60, 3600),
            daily_mills=money(env, "X_MONITOR_DAILY_BUDGET_USD"),
            monthly_mills=money(env, "X_MONITOR_MONTHLY_BUDGET_USD"),
            daily_requests=number(env, "X_MONITOR_MAX_REQUESTS_PER_DAY", 1000, 1, 10000),
        )

    @property
    def fingerprint(self):
        return hashlib.sha256(make_query(self.handles).lower().encode()).hexdigest()[:16]

    @property
    def request_reserve(self):
        return PAGE_SIZE * POST_MILLS + min(PAGE_SIZE, len(self.handles)) * USER_MILLS

    def blocker(self):
        if not self.enabled:
            return "DISABLED — X_MONITOR_ENABLED=false"
        if not self.bearer:
            return "BLOCKED — X_BEARER_TOKEN is missing"
        if not self.channel_id:
            return "BLOCKED — CHANNEL_X_MONITOR_ADMIN is missing"
        if min(self.daily_mills, self.monthly_mills) < self.request_reserve:
            return "BLOCKED — set daily and monthly budgets (each at least one request reserve)"
        return ""
