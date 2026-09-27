"""Bounded priority selection from the existing Redis list; one dispatcher.

Existing queue keys/payloads stay compatible with older producers and rollback.
This changes selection order across products, never creates or drops events.
"""
import os
import time
from redis.exceptions import ResponseError

VERSION = "1.0.0"
PRIORITY_ENABLED = os.getenv("LOTUS_EVENT_PRIORITY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
LOOKAHEAD = 512
MAX_PRIORITY_BURST = 8
_priority_streak = 0
_script_unavailable = False

# Only the queue key is used: no extra queue, migration or cluster hash slot.
# All read/selection work precedes the single removal command. Scripts execute
# atomically, so concurrent pushes cannot invalidate the selected list entry.
SELECT_EVENT_LUA = r'''
local rows = redis.call('LRANGE', KEYS[1], 0, tonumber(ARGV[1]) - 1)
local depth = redis.call('LLEN', KEYS[1])
if #rows == 0 then return {} end
if ARGV[2] == '1' then
    return {redis.call('LPOP', KEYS[1]), 'FAIR_FIFO', depth}
end
local urgent = {
    RESTOCK=true, STOCK_AVAILABLE=true, PREORDER_LIVE=true,
    SOLD_OUT=true, INVENTORY_FLICKER=true,
    QUEUE_DETECTED=true, QUEUE_ACTIVE=true, QUEUE_CLEARED=true
}
local function string_field(v)
    if type(v) == 'string' then return v end
    if type(v) == 'number' then return tostring(v) end
    return ''
end
local function identity(event)
    if type(event) ~= 'table' then return nil end
    local store = string.lower(string_field(event.store_name))
    local source = string.lower(string_field(event.source_type))
    if store == '' or source == '' then return nil end
    local external = string_field(event.external_product_id)
    local url = string_field(event.product_url)
    local host, path = string.match(url, '^https?://([^/]+)(.*)$')
    if host then
        host = string.gsub(string.lower(host), '^www%.', '')
        path = string.gsub(path, '[?#].*$', '')
        path = string.gsub(path, '/+$', '')
        -- Shopify collection product URLs refer to the same product page.
        if source == 'shopify' then
            path = string.gsub(path, '^/collections/[^/]+/products/', '/products/')
        end
        url = host .. path
    else
        url = ''
    end
    if external == '' and url == '' then return nil end
    return {store=store, source=source, external=external, url=url}
end
local function same_product(a, b)
    return a.store == b.store and a.source == b.source and (
        (a.external ~= '' and a.external == b.external) or
        (a.url ~= '' and a.url == b.url)
    )
end
local seen = {}
local chosen = 1
local reason = 'FIFO'
for i, raw in ipairs(rows) do
    local ok, event = pcall(cjson.decode, raw)
    local key = ok and identity(event) or nil
    -- An unidentifiable record is an ordering barrier. Consume the head and
    -- let the existing decoder handle it, rather than jump over unknown data.
    if not key then break end
    seen[i] = key
    if urgent[string_field(event.event_type)] then
        chosen = i
        reason = 'STOCK_PRIORITY'
        -- Preserve predecessors even when one event has only a URL and the
        -- next also has an external ID. Walk backward so aliases can chain.
        local related = {key}
        for j = i - 1, 1, -1 do
            for _, candidate in ipairs(related) do
                if same_product(seen[j], candidate) then
                    chosen = j
                    reason = 'PRODUCT_PREDECESSOR'
                    table.insert(related, seen[j])
                    break
                end
            end
        end
        break
    end
end
if chosen == 1 then return {redis.call('LPOP', KEYS[1]), reason, depth} end
-- The selected entry is the first identical payload: if an earlier identical
-- entry existed, the predecessor walk would already have selected it.
redis.call('LREM', KEYS[1], 1, rows[chosen])
return {rows[chosen], reason, depth}
'''


async def pop_priority_event(client, queue_key, timeout=5):
    """Return (raw JSON, selection reason, queue depth before removal)."""
    global _priority_streak, _script_unavailable
    if PRIORITY_ENABLED and not _script_unavailable:
        try:
            result = await client.eval(SELECT_EVENT_LUA, 1, queue_key,
                                       LOOKAHEAD, int(_priority_streak >= MAX_PRIORITY_BURST))
        except ResponseError as error:
            # Known permission/capability refusals happen before removal.
            # Do not catch network/timeouts and dequeue a second event when
            # the outcome of the first request may be unknown.
            detail = str(error).lower()
            if "noperm" not in detail and not ("unknown command" in detail and "eval" in detail):
                raise
            _script_unavailable = True
            print("LOTUS QUEUE MODE | Mode=FIFO_FALLBACK | Reason=REDIS_SCRIPT_UNAVAILABLE", flush=True)
            result = None
        if result:
            raw, reason, depth = result
            if isinstance(reason, bytes):
                reason = reason.decode("utf-8")
            _priority_streak = _priority_streak + 1 if reason in {"STOCK_PRIORITY", "PRODUCT_PREDECESSOR"} else 0
            return raw, reason, int(depth)
    # No priority request remains in flight. A newly arrived event may be
    # taken directly by BLPOP; the following iteration resumes priority scans.
    result = await client.blpop(queue_key, timeout=timeout)
    if not result:
        _priority_streak = 0
        return None
    _priority_streak = 0
    mode = "FIFO_FALLBACK" if _script_unavailable else "FIFO_DISABLED" if not PRIORITY_ENABLED else "EMPTY_WAIT"
    return result[1], mode, None


def event_age_seconds(event):
    value = event.get("_lotus_enqueued_at")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        age = time.time() - value
        if float('-inf') < age < float('inf'):
            return max(0.0, age)
    return None
