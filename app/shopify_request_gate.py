"""Process-wide request-start pacing; domain cooldowns remain authoritative.

Run one Shopify worker replica. This gate does not coordinate separate processes.
"""
import asyncio
import time
from collections import OrderedDict


class RequestGate:
    def __init__(self, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.clock, self.sleep = clock, sleep
        self.lock = asyncio.Lock()
        self.next_start = 0.0
        self.blocked_until = 0.0
        self.interval = 0.35
        self.recent = OrderedDict()
        self.clean_since = None
        self.clean_count = 0

    async def acquire(self):
        started = self.clock()
        async with self.lock:
            # Recheck after sleeping: in-flight responses may extend the hold.
            while True:
                delay = max(self.next_start, self.blocked_until) - self.clock()
                if delay <= 0:
                    break
                await self.sleep(delay)
            self.next_start = self.clock() + self.interval
        return self.clock() - started

    def throttled(self, domain):
        now = self.clock()
        self.clean_since = None
        self.clean_count = 0
        for key, at in list(self.recent.items()):
            if now - at > 15:
                del self.recent[key]
        self.recent[domain] = now
        self.recent.move_to_end(domain)
        while len(self.recent) > 256:
            self.recent.popitem(last=False)
        if len(self.recent) >= 5:
            self.interval = min(2.0, max(1.0, self.interval * 1.5))
            self.blocked_until = max(self.blocked_until, now + 60)
            self.recent.clear()
            print('SHOPIFY SHARED PACING | Version=1.7.9 | State=THROTTLE_BURST | '
                  f'HoldSeconds=60 | RequestSpacing={self.interval:.2f}', flush=True)

    def products_succeeded(self):
        now = self.clock()
        if self.clean_since is None:
            self.clean_since = now
        self.clean_count += 1
        if self.clean_count >= 20 and now - self.clean_since >= 300:
            self.interval = max(0.35, self.interval * 0.75)
            self.clean_since = now
            self.clean_count = 0


_GATE = RequestGate()
async def acquire():
    return await _GATE.acquire()
def throttled(domain):
    _GATE.throttled(domain)
def products_succeeded():
    _GATE.products_succeeded()
