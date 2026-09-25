"""Per-store adaptive pacing. Cooldown deadlines remain owned by the adapter."""
import time
from dataclasses import dataclass

BASE_INTERVAL = 0.75
MAX_INTERVAL = 12.0
STABLE_SECONDS = 300.0
STABLE_RESPONSES = 20


@dataclass
class Pace:
    interval: float = BASE_INTERVAL
    recovering: bool = False
    clean_since: float | None = None
    clean_responses: int = 0


_STATES = {}


def throttled(domain):
    state = _STATES.setdefault(domain, Pace())
    state.interval = min(MAX_INTERVAL, max(1.5, state.interval * 2))
    state.recovering = True
    state.clean_since = None
    state.clean_responses = 0


def succeeded(domain):
    state = _STATES.get(domain)
    if state is None:
        return
    now = time.monotonic()
    if state.clean_since is None:
        state.clean_since = now
    state.clean_responses += 1
    if state.clean_responses >= STABLE_RESPONSES and now-state.clean_since >= STABLE_SECONDS:
        state.recovering = False
        state.interval = max(BASE_INTERVAL, state.interval * 0.75)
        state.clean_since = now
        state.clean_responses = 0


def request_interval(domain):
    state = _STATES.get(domain)
    return state.interval if state else BASE_INTERVAL


def recovering(domain):
    state = _STATES.get(domain)
    return bool(state and state.recovering)


def poll_interval(domain, normal=5.0):
    return max(normal, request_interval(domain) * 2)
