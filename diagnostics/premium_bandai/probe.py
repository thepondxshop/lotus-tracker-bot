"""Lotus 6K-3D6: one-shot browser diagnostics; no Discord or production integration."""
import asyncio
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

def sanitize_text(value, limit=400):
    value = " ".join(str(value).split())
    value = re.sub(r"https?://\S+", "[URL]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
    value = re.sub(r"(?i)\b(token|api_?key|session|authorization|password|nonce)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", value)
    value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", value)
    value = re.sub(r"[A-Za-z0-9_+=/-]{32,}", "[LONG_VALUE]", value)
    return value[:limit]

def parse_preload_product(body, page_url):
    """Extract observed product fields without executing JavaScript or enabling alerts."""
    path = urlparse(page_url).path
    match = re.fullmatch(r"/us/item/([A-Za-z0-9_-]+)/?", path)
    if not match:
        return {"preload_error": "ITEM_URL_REQUIRED"}

    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.active = False
            self.parts = []
        def handle_starttag(self, tag, attrs):
            if tag == "script":
                attrs = dict(attrs)
                self.active = not attrs.get("src") and attrs.get("type", "").lower() in {
                    "", "text/javascript", "application/javascript"}
        def handle_endtag(self, tag):
            if tag == "script":
                self.active = False
        def handle_data(self, data):
            if self.active:
                self.parts.append(data)

    scripts = Scripts()
    scripts.feed(body)
    candidates = []
    for script in scripts.parts:
        for assignment in re.finditer(
                r"(?m)^\s*(?:(?:var|let|const)\s+|window\.)?PRELOAD_DATA\s*=\s*", script):
            try:
                data, end = json.JSONDecoder().raw_decode(script[assignment.end():])
                tail = script[assignment.end()+end:].lstrip(" \t")
                if not tail or tail.startswith((";", "\n", "\r")):
                    candidates.append(data)
            except (ValueError, RecursionError):
                return {"preload_error": "PRELOAD_JSON_INVALID"}
    if len(candidates) != 1:
        return {"preload_error": "PRELOAD_NOT_FOUND" if not candidates else "PRELOAD_AMBIGUOUS"}
    return parse_product_data(candidates[0], page_url)


def parse_product_data(data, page_url):
    match = re.fullmatch(r"/us/item/([A-Za-z0-9_-]+)/?", urlparse(page_url).path)
    if not match:
        return {"preload_error": "ITEM_URL_REQUIRED"}
    product = data.get("product") if isinstance(data, dict) else None
    if not isinstance(product, dict):
        return {"preload_error": "PRODUCT_MISSING"}
    if product.get("productCode") != match[1] or product.get("areaCode") != "US":
        return {"preload_error": "PRODUCT_IDENTITY_MISMATCH"}

    def obj(value):
        return value if isinstance(value, dict) else {}
    def boolean(value):
        return value if type(value) is bool else None
    info = obj(product.get("infoSection"))
    title = obj(info.get("productName")).get("en")
    price = obj(obj(info.get("price")).get("fixedListPrice"))
    amount = price.get("amount")
    if (not isinstance(title, str) or not title.strip()
            or type(amount) not in (int, float) or not 0 < amount < 10000000
            or price.get("currency") != "USD"):
        return {"preload_error": "PRODUCT_FIELDS_INVALID"}
    general = obj(info.get("generalProdInfo"))
    order = obj(info.get("orderInfo"))
    flags = product.get("flags")
    flags = [sanitize_text(f, 80) for f in flags[:20] if isinstance(f, str)] if isinstance(flags, list) else []
    purchase = boolean(product.get("purchaseAvailable"))
    out = boolean(general.get("outOfStock"))
    # Only the closed-preorder combination has been observed in a real sample.
    closed = (purchase is False and out is True and "PRE_ORDER_CLOSED" in flags
              and order.get("preOrderStatus") == "End"
              and general.get("availabilityStatus") == "End")
    limits = obj(obj(product.get("productDescriptionSection")).get("productLimitedQuantityInfo"))
    def limit(key):
        value = limits.get(key)
        return value if type(value) is int and value > 0 else None
    images = obj(product.get("mediaSection")).get("images")
    image_url = None
    if isinstance(images, list) and images:
        source = obj(images[0]).get("fileUrl")
        if isinstance(source, str):
            candidate = urljoin("https://p-bandai.com/", source)
            parsed = urlparse(candidate)
            if (parsed.scheme == "https" and parsed.hostname == "p-bandai.com"
                    and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment):
                image_url = candidate
    return {
        "preload_error": None, "product_data_parsed": True,
        "observed_product": {
            "product_code": match[1], "title": sanitize_text(title, 240),
            "price": amount, "currency": "USD", "image_url": image_url,
            "flags": flags, "purchase_available": purchase, "out_of_stock": out,
            "preorder_status": sanitize_text(order.get("preOrderStatus"), 80),
            "availability_status": sanitize_text(general.get("availabilityStatus"), 80),
            "discontinued": boolean(product.get("discontinued")),
            "order_start": sanitize_text(order.get("orderStartDate"), 80),
            "order_end": sanitize_text(order.get("orderEndDate"), 80),
            "estimated_shipping_month": sanitize_text(order.get("estimatedShippingDate"), 80),
            "limit_per_order": limit("maxByPerOrder"),
            "limit_per_user": limit("maxByPerUser"),
            "observed_state": "PREORDER_CLOSED" if closed else "UNKNOWN_REQUIRES_VALIDATION",
        },
        "stock_verified": False,
        "validation_note": "Closed-preorder sample supported; live transitions and purchasable states unverified.",
    }

SNAPSHOT_JS = r"""() => {
    const out = {
        title: String(document.title || "").slice(0, 500),
        text: String(document.body?.innerText || "").slice(0, 10000),
        preload_present: false, product_present: false, read_error: false
    };
    try {
        const data = typeof PRELOAD_DATA !== "undefined"
            ? PRELOAD_DATA : window.PRELOAD_DATA;
        out.preload_present = data != null;
        const p = data?.product;
        out.product_present = p != null && typeof p === "object";
        if (out.product_present) {
            const scalar = v => typeof v === "string" ? v.slice(0, 500)
                : (typeof v === "boolean" || (typeof v === "number" && Number.isFinite(v))) ? v : null;
            const info = p.infoSection || {};
            const price = info.price?.fixedListPrice || {};
            const order = info.orderInfo || {};
            const general = info.generalProdInfo || {};
            const limits = p.productDescriptionSection?.productLimitedQuantityInfo || {};
            out.product = {
                productCode: scalar(p.productCode), areaCode: scalar(p.areaCode),
                purchaseAvailable: scalar(p.purchaseAvailable), discontinued: scalar(p.discontinued),
                flags: Array.isArray(p.flags) ? p.flags.slice(0, 20).map(scalar) : [],
                infoSection: {
                    productName: {en: scalar(info.productName?.en)},
                    price: {fixedListPrice: {amount: scalar(price.amount), currency: scalar(price.currency)}},
                    orderInfo: {
                        preOrderStatus: scalar(order.preOrderStatus),
                        orderStartDate: scalar(order.orderStartDate), orderEndDate: scalar(order.orderEndDate),
                        estimatedShippingDate: scalar(order.estimatedShippingDate)
                    },
                    generalProdInfo: {outOfStock: scalar(general.outOfStock), availabilityStatus: scalar(general.availabilityStatus)}
                },
                productDescriptionSection: {productLimitedQuantityInfo: {
                    maxByPerOrder: scalar(limits.maxByPerOrder), maxByPerUser: scalar(limits.maxByPerUser)
                }},
                mediaSection: {images: [{fileUrl: scalar(p.mediaSection?.images?.[0]?.fileUrl)}]}
            };
        }
    } catch (_) { out.read_error = true; }
    return out;
}"""

URLS = ["https://p-bandai.com/us/item/N2890904002",
        "https://p-bandai.com/us/item/N2890904001"]
PREFIX = "PREMIUM BANDAI BROWSER DIAGNOSTICS | "


def emit(data):
    print(PREFIX + json.dumps({"step": "6K-3D6", "browser_mode": "VIRTUAL_DISPLAY", "integration_state": "VALIDATION_ONLY",
                              "stock_verified": False, **data}, sort_keys=True), flush=True)


async def inspect_page(browser, url, result):
    context = await browser.new_context(accept_downloads=False)
    try:
        page = await context.new_page()
        page.set_default_timeout(5000)
        counts = {"requests": 0, "failed_requests": 0}
        def requested(request):
            counts["requests"] += 1
        def failed(request):
            counts["failed_requests"] += 1
        page.on("request", requested)
        page.on("requestfailed", failed)
        # Keep top-level navigation on the selected public US item page.
        async def guard(route):
            request = route.request
            if request.is_navigation_request() and request.frame == page.main_frame:
                parsed = urlparse(request.url)
                expected = urlparse(url)
                if (parsed.scheme != "https" or parsed.hostname != "p-bandai.com"
                        or parsed.path.rstrip('/') != expected.path.rstrip('/')):
                    result["navigation_restricted"] = True
                    await route.abort()
                    return
            await route.continue_()
        await page.route("**/*", guard)
        started = time.monotonic()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        result["http_status"] = response.status if response else None
        result["dom_ready_seconds"] = round(time.monotonic()-started, 3)
        if response and response.status in (401, 403, 429):
            result["outcome"] = "HTTP_ACCESS_RESTRICTED"
            return
        deadline = time.monotonic() + 12
        while True:
            body = await page.content()
            if len(body) > 2*1024*1024:
                result["outcome"] = "PAGE_TOO_LARGE"
                return
            result["rendered_characters"] = len(body)
            snapshot = await page.evaluate(SNAPSHOT_JS)
            result["page_title"] = sanitize_text(snapshot.get("title", ""), 180)
            result["visible_text_sample"] = sanitize_text(snapshot.get("text", ""), 500)
            result["runtime_preload_present"] = snapshot.get("preload_present", False)
            result["runtime_product_present"] = snapshot.get("product_present", False)
            result["runtime_read_error"] = snapshot.get("read_error", False)
            result.update(counts)
            visible = snapshot.get("text", "").lower()
            if any(marker in visible for marker in (
                    "verify you are human", "pardon our interruption", "access denied",
                    "robot or human", "complete the captcha")):
                result["outcome"] = "INTERACTIVE_CHALLENGE_OR_ACCESS_DENIED"
                return
            parsed = parse_preload_product(body, url)
            result["html_preload_error"] = parsed.get("preload_error")
            result["data_source"] = "HTML" if parsed.get("product_data_parsed") else None
            if snapshot.get("product_present"):
                runtime = parse_product_data({"product": snapshot.get("product")}, url)
                result["runtime_preload_error"] = runtime.get("preload_error")
                if runtime.get("product_data_parsed"):
                    parsed = runtime
                    result["data_source"] = "BROWSER_MEMORY"
            result.update(parsed)
            result.update(counts)
            if parsed.get("product_data_parsed"):
                result["outcome"] = "PRODUCT_PARSED_LIVE_VALIDATION_PENDING"
                result["data_ready_seconds"] = round(time.monotonic()-started, 3)
                return
            if time.monotonic() >= deadline:
                result["outcome"] = parsed.get("preload_error", "PRODUCT_NOT_FOUND")
                return
            await asyncio.sleep(1)
    finally:
        await context.close()


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        emit({"outcome": "PLAYWRIGHT_NOT_INSTALLED"})
        return
    async with async_playwright() as playwright:
        start = time.monotonic()
        try:
            browser = await playwright.chromium.launch(headless=False, timeout=20000,
                                                       args=["--disable-dev-shm-usage"])
        except Exception as error:
            emit({"outcome": "BROWSER_LAUNCH_FAILED", "error_type": type(error).__name__})
            return
        emit({"outcome": "BROWSER_STARTED", "startup_seconds": round(time.monotonic()-start, 3)})
        try:
            for url in URLS:
                result = {"probe_url": url, "product_data_parsed": False}
                start = time.monotonic()
                try:
                    await asyncio.wait_for(inspect_page(browser, url, result), timeout=45)
                except asyncio.TimeoutError:
                    result["outcome"] = "BROWSER_PROBE_TIMEOUT"
                except Exception as error:
                    result["outcome"] = "BROWSER_PROBE_FAILED"
                    result["error_type"] = type(error).__name__
                result["total_seconds"] = round(time.monotonic()-start, 3)
                emit(result)
        finally:
            await browser.close()
    emit({"outcome": "PROBE_COMPLETE"})


if __name__ == "__main__":
    asyncio.run(main())
