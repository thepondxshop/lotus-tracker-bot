"""Temporary Railway diagnostic: 15-minute silence, ONE request, then idle.

Run instead of main.py, never alongside it. Restore the original start
command after saving the result. Does not import/start Lotus or use its data.
"""
import asyncio
import json
import time
from datetime import datetime, timezone

import aiohttp

URL = "https://thepondx.com/products.json?limit=1&page=1"
QUIET_SECONDS = 15 * 60
BODY_LIMIT = 65536
HEADER_NAMES = (
    "Retry-After", "Server", "Content-Type", "CF-Ray", "X-Request-ID",
    "CF-Mitigated", "X-Shopify-Stage", "X-Shopify-Shop-Api-Call-Limit",
)


def log(label, data):
    print(label + " | " + json.dumps(data, ensure_ascii=True), flush=True)


async def quiet_period(seconds):
    deadline = time.monotonic() + seconds
    while True:
        remaining = max(0, deadline - time.monotonic())
        if remaining <= 0:
            return
        log("SHOPIFY PROBE QUIET", {"seconds_left": int(remaining + 0.999),
                                    "http_requests_sent": 0})
        await asyncio.sleep(min(60, remaining))


async def one_request(session_factory=aiohttp.ClientSession):
    result = {"at_utc": datetime.now(timezone.utc).isoformat(),
              "target": URL, "method": "GET", "automatic_retries": 0}
    try:
        async with session_factory(
            timeout=aiohttp.ClientTimeout(total=25, connect=10),
            headers={"Accept": "application/json,text/plain,*/*",
                     "User-Agent": "PonDeX-Trackers/1.0.6-C1"},
        ) as session:
            # Do not change identity or follow alternate endpoints on rejection.
            async with session.get(URL, allow_redirects=False) as response:
                result["http_status"] = response.status
                result["headers"] = {
                    name: str(response.headers[name]).replace("\n", " ").replace("\r", " ")[:200]
                    for name in HEADER_NAMES if name in response.headers
                }
                body = bytearray()
                async for chunk in response.content.iter_chunked(4096):
                    body.extend(chunk[:BODY_LIMIT + 1 - len(body)])
                    if len(body) > BODY_LIMIT:
                        break
                result["body_truncated"] = len(body) > BODY_LIMIT
                result["bytes_inspected"] = min(len(body), BODY_LIMIT)
                # Report schema only: never print cookies, credentials or body.
                try:
                    payload = json.loads(bytes(body)) if not result["body_truncated"] else None
                    result["valid_products_response"] = (
                        response.status == 200 and isinstance(payload, dict)
                        and isinstance(payload.get("products"), list)
                    )
                    if result["valid_products_response"]:
                        result["products_returned"] = len(payload["products"])
                except (ValueError, UnicodeError):
                    result["valid_products_response"] = False
    except Exception as error:
        result["error_type"] = type(error).__name__
    return result


async def main():
    log("SHOPIFY PROBE START", {"mode": "ONE_REQUEST_ONLY", "quiet_seconds": QUIET_SECONDS,
                                "lotus_bot_running_in_this_process": False})
    await quiet_period(QUIET_SECONDS)
    log("SHOPIFY PROBE RESULT", await one_request())
    log("SHOPIFY PROBE FINISHED", {
        "next_step": "Save RESULT and restore the original Railway start command.",
        "further_requests": 0,
    })
    # Stay alive so a Railway restart policy does not repeatedly run the probe.
    # A deliberate external restart starts a NEW full quiet period.
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
