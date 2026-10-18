"""Per-store adaptive pacing. Cooldown deadlines remain owned by the adapter."""
import time
from dataclasses import dataclass

BASE_INTERVAL = 0.75
MAX_INTERVAL = 12.0
STABLE_SECONDS = 300.0
STABLE_RESPONSES = 20
RECOVERY_POLL_SECONDS = 60.0


@dataclass
class Pace:
    interval: float = BASE_INTERVAL
    recovering: bool = False
    clean_since: float | None = None
    clean_responses: int = 0
    general_blocked: bool = False
    general_failures: int = 0
    general_retry_at: float = 0.0


_STATES = {}


def throttled(domain, purpose=None):
    state = _STATES.setdefault(domain, Pace())
    state.interval = min(MAX_INTERVAL, max(1.5, state.interval * 2))
    state.recovering = True
    if is_general(purpose):
        state.general_failures += 1
        state.general_blocked = True
        state.general_retry_at = time.monotonic() + general_delay(state)
    state.clean_since = None
    state.clean_responses = 0


def succeeded(domain, purpose=None):
    state = _STATES.get(domain)
    if state is None:
        return
    now = time.monotonic()
    if is_general(purpose):
        state.general_blocked = False
        state.general_failures = 0
        state.general_retry_at = 0.0
    if state.clean_since is None:
        state.clean_since = now
    state.clean_responses += 1
    if not state.general_blocked and state.clean_responses >= STABLE_RESPONSES and now-state.clean_since >= STABLE_SECONDS:
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
    minimum = RECOVERY_POLL_SECONDS if recovering(domain) else 0.0
    return max(normal, request_interval(domain) * 2, minimum)



def is_general(purpose):
    return purpose == 'GENERAL_HEAD' or str(purpose or '').startswith('GENERAL_PRODUCTS_PAGE_')


def general_delay(state):
    return min(3600.0, 900.0 * 2 ** min(max(state.general_failures-1,0),2))


def general_blocked(domain):
    state = _STATES.get(domain)
    return bool(state and state.general_blocked)


def general_due(domain):
    state = _STATES.get(domain)
    return not state or not state.general_blocked or time.monotonic() >= state.general_retry_at


def begin_general_attempt(domain):
    """Called under the adapter domain lock; failed probes also stay bounded."""
    if not general_due(domain):return False
    state = _STATES.get(domain)
    if state and state.general_blocked:
        state.general_retry_at = time.monotonic() + general_delay(state)
    return True
