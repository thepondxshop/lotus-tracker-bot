"""Redis state, fenced writes, and conservative local X cost reservations."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import uuid

from app.redis_client import get_redis

WRITE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
for _, command in ipairs(cjson.decode(ARGV[2])) do
    redis.call(unpack(command))
end
return 1
"""
RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
RESERVE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return -1 end
if redis.call('GET', KEYS[5]) then return 1 end
local amount = tonumber(ARGV[2])
if tonumber(redis.call('GET', KEYS[2]) or '0') + amount > tonumber(ARGV[3]) then return 0 end
if tonumber(redis.call('GET', KEYS[3]) or '0') + amount > tonumber(ARGV[4]) then return 0 end
if tonumber(redis.call('GET', KEYS[4]) or '0') >= tonumber(ARGV[5]) then return 0 end
redis.call('INCRBY', KEYS[2], amount)
redis.call('INCRBY', KEYS[3], amount)
redis.call('INCR', KEYS[4])
redis.call('SET', KEYS[5], 'reserved', 'EX', 3456000)
redis.call('EXPIRE', KEYS[2], 3456000)
redis.call('EXPIRE', KEYS[3], 34560000)
redis.call('EXPIRE', KEYS[4], 3456000)
return 1
"""
SETTLE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
local receipt = redis.call('GET', KEYS[4])
if receipt == 'settled' then return 1 end
if receipt ~= 'reserved' then return 0 end
redis.call('INCRBY', KEYS[2], ARGV[2])
redis.call('INCRBY', KEYS[3], ARGV[2])
redis.call('SET', KEYS[4], 'settled', 'EX', 3456000)
return 1
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, guild_id, redis=None):
        self.prefix = f"lotus:xmonitor:v1:{guild_id}"
        self.redis_override = redis
        self.token = ""

    def key(self, name):
        return self.prefix + ":" + name

    async def call(self, method, *args, **kwargs):
        client = self.redis_override if self.redis_override is not None else get_redis()
        if client is None:
            raise RuntimeError("Redis unavailable")
        return await asyncio.wait_for(getattr(client, method)(*args, **kwargs), 5)

    @asynccontextmanager
    async def lease(self):
        token = uuid.uuid4().hex
        acquired = await self.call("set", self.key("lock"), token, nx=True, ex=120)
        if not acquired:
            yield False
            return
        self.token = token
        try:
            # Must bound the COMPLETE operation, including waits, below lease TTL.
            async with asyncio.timeout(90):
                yield True
        finally:
            self.token = ""
            try:
                await self.call("eval", RELEASE, 1, self.key("lock"), token)
            except Exception:
                pass

    async def write(self, commands):
        result = await self.call("eval", WRITE, 1, self.key("lock"), self.token, encode(commands))
        if result != 1:
            raise RuntimeError("X monitor lease lost")

    async def state(self):
        raw = await self.call("get", self.key("state"))
        return json.loads(raw) if raw else {}

    async def save(self, state, commands=()):
        await self.write([*commands, ["SET", self.key("state"), encode(state)]])

    def budget_keys(self, now):
        dt = datetime.fromtimestamp(now, timezone.utc)
        return [self.key("cost:day:" + dt.strftime("%Y-%m-%d")),
                self.key("cost:month:" + dt.strftime("%Y-%m")),
                self.key("calls:" + dt.strftime("%Y-%m-%d"))]

    async def reserve(self, cfg, now):
        keys = self.budget_keys(now)
        keys.append(self.key("reservation:" + uuid.uuid4().hex))
        result = await self.call("eval", RESERVE, 5, self.key("lock"), *keys,
                                 self.token, cfg.request_reserve, cfg.daily_mills,
                                 cfg.monthly_mills, cfg.daily_requests)
        if result == -1:
            raise RuntimeError("X monitor lease lost")
        return keys if result == 1 else None

    async def settle(self, keys, reserved, actual):
        # Unknown outcomes retain the entire reservation; only validated responses
        # release unused capacity. No assumption about X billing deduplication.
        # Idempotent even if the shared Redis client's automatic network retry
        # replays this script after the server already applied the refund.
        result = await self.call("eval", SETTLE, 4, self.key("lock"), keys[0], keys[1], keys[3],
                                 self.token, actual - reserved)
        if result != 1:
            raise RuntimeError("X budget settlement lease or reservation lost")

    async def enqueue_page(self, state, jobs, now):
        commands = [["ZREMRANGEBYSCORE", self.key("seen"), "-inf", now - 30 * 86400]]
        for job in jobs:
            if await self.call("zscore", self.key("seen"), job["id"]) is not None:
                continue
            commands.extend([
                ["ZADD", self.key("seen"), now, job["id"]],
                ["HSET", self.key("jobs"), job["id"], encode(job)],
                ["ZADD", self.key("due"), now, job["id"]],
            ])
        # Cursor and outbox commit together. Failed persistence means replaying
        # the page, never advancing past data that hasn't been durably queued.
        await self.save(state, commands)

    async def finish(self, job_id, outcome):
        await self.write([
            ["HDEL", self.key("jobs"), job_id],
            ["ZREM", self.key("due"), job_id],
            ["HINCRBY", self.key("totals"), outcome, 1],
        ])

    async def set_job(self, job, due=None):
        commands = [["HSET", self.key("jobs"), job["id"], encode(job)]]
        if due is not None:
            commands.append(["ZADD", self.key("due"), due, job["id"]])
        await self.write(commands)
