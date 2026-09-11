"""Lotus 6K-3D3: Premium Bandai US product-data validation probe.

Extracts observed product fields for diagnostics only; no production alerts.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import aiohttp
from .base import MajorRetailerAdapter, MajorRetailerCapabilityProfile, MajorRetailerProbe
from .registry import major_retailer_adapter

STEP = "6K-3D3"
DEFAULT_URL = "https://p-bandai.com/us"


def safe_probe_url(value):
    try:
        p = urlparse(value)
        if (p.scheme != "https" or p.hostname not in {"p-bandai.com", "www.p-bandai.com"}
                or p.username or p.password or p.port not in (None, 443)
                or not (p.path == "/us" or p.path.startswith("/us/"))):
            return None
        # Queries/fragments are unnecessary for source assessment.
        return "https://" + p.hostname + p.path
    except (ValueError, TypeError):
        return None


def sanitize_text(value, limit=400):
    value = " ".join(str(value).split())
    value = re.sub(r"https?://\S+", "[URL]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
    value = re.sub(r"(?i)\b(token|api_?key|session|authorization|password|nonce)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", value)
    value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", value)
    value = re.sub(r"[A-Za-z0-9_+=/-]{32,}", "[LONG_VALUE]", value)
    return value[:limit]


def script_reference(src, page_url):
    try:
        parsed = urlparse(urljoin(page_url, src))
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return "[NON_HTTP_SCRIPT]"
        # No credentials, query strings or fragments. Mask opaque path segments.
        path = re.sub(r"[A-Za-z0-9_+=-]{24,}", "[OPAQUE]", parsed.path)
        return (parsed.hostname + path)[:200]
    except (ValueError, TypeError):
        return "[INVALID_SCRIPT_URL]"


class SourcePage(HTMLParser):
    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.tags = Counter()
        self.scripts = []
        self.current_script = None
        self.hidden = Counter()
        self.visible = []
        self.visible_chars = 0
        self.title_parts = []
        self.in_title = False
        self.meta = {}
        self.json_ld_count = 0
        self.product_links = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags[tag] += 1
        if tag in {"script", "style", "noscript", "template", "form", "textarea"}:
            self.hidden[tag] += 1
        if tag == "title":
            self.in_title = True
        if tag == "script":
            info = {"type": sanitize_text(attrs.get("type", "classic"), 80),
                    "inline_characters": 0,
                    "source": script_reference(attrs["src"], self.page_url) if attrs.get("src") else None}
            self.current_script = info
            if len(self.scripts) < 8:
                self.scripts.append(info)
            if attrs.get("type", "").lower() == "application/ld+json":
                self.json_ld_count += 1
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key in {"og:title", "og:type", "product:price:amount", "product:price:currency"}:
                self.meta[key] = sanitize_text(attrs.get("content", ""), 180)
        if tag == "a" and isinstance(attrs.get("href"), str):
            url = safe_probe_url(urljoin(self.page_url, attrs["href"]))
            if url and urlparse(url).path.startswith("/us/item/"):
                self.product_links.add(url)

    def handle_data(self, data):
        if self.current_script is not None:
            self.current_script["inline_characters"] += len(data)
        if self.in_title:
            self.title_parts.append(data[:180])
        if not any(self.hidden.values()) and self.visible_chars < 2000:
            sample = data[:2000-self.visible_chars]
            self.visible.append(sample)
            self.visible_chars += len(sample)

    def handle_endtag(self, tag):
        if self.hidden[tag]:
            self.hidden[tag] -= 1
        if tag == "script":
            self.current_script = None
        if tag == "title":
            self.in_title = False


def assess_html(body, page_url=DEFAULT_URL):
    if not body.strip():
        return False, "PREMIUM_BANDAI_EMPTY_RESPONSE", {}
    parser = SourcePage(page_url)
    parser.feed(body)
    parser.close()
    lowered = body.lower()
    markers = [name for name, text in (
        ("ACCESS_DENIED_TEXT", "access denied"),
        ("HUMAN_VERIFICATION_TEXT", "verify you are human"),
        ("ROBOT_OR_HUMAN_TEXT", "robot or human"),
        ("INTERRUPTION_TEXT", "pardon our interruption"),
        ("AKAMAI_REFERENCE", "akamai"),
        ("DATADOME_REFERENCE", "datadome"),
        ("PERIMETERX_REFERENCE", "perimeterx"),
        ("CAPTCHA_REFERENCE", "captcha"),
        ("NEXT_DATA_REFERENCE", "__next_data__"),
        ("NUXT_REFERENCE", "__nuxt"),
    ) if text in lowered]
    challenge = any(name.endswith("_TEXT") for name in markers)
    details = {
        "script_tags": parser.tags["script"],
        "script_references": parser.scripts,
        "json_ld_blocks": parser.json_ld_count,
        "candidate_item_links": len(parser.product_links),
        "candidate_item_samples": sorted(parser.product_links)[:3],
        "page_title": sanitize_text(" ".join(parser.title_parts), 180),
        "page_metadata_candidates": parser.meta,
        "structure_counts": {tag: parser.tags[tag] for tag in
            ("html", "head", "body", "title", "h1", "a", "form", "iframe", "script", "noscript")},
        "visible_text_sample": sanitize_text(" ".join(parser.visible)),
        "recognized_markers": markers,
        "marker_note": "References alone do not prove a block or usable product data.",
    }
    # A fetched page is evidence for inspection, not a passed product validation.
    message = ("PREMIUM_BANDAI_CHALLENGE_PAGE" if challenge else
               "PREMIUM_BANDAI_STRUCTURE_CAPTURED_NOT_PRODUCT_VALIDATED")
    if not challenge:
        parsed = parse_preload_product(body, page_url)
        details.update(parsed)
        if parsed.get("product_data_parsed"):
            message = "PREMIUM_BANDAI_PRODUCT_PARSED_LIVE_VALIDATION_PENDING"
        else:
            message = "PREMIUM_BANDAI_" + parsed["preload_error"]
    return False, message, details


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
    data = candidates[0]
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


@major_retailer_adapter("premium_bandai")
class PremiumBandaiMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "premium_bandai"
    version = "1.0.6-6K3D3"
    @property
    def capabilities(self):
        # No product capability is claimed from a source-access probe.
        return MajorRetailerCapabilityProfile()
    async def healthcheck(self):
        self.diagnostics={"integration_state":"VALIDATION_ONLY", "product_data_parsed":False, "step":STEP,
                          "requests":0, "product_parser_verified":False,
                          "stock_verified":False, "last_error":None}
        url=safe_probe_url(os.getenv("PREMIUM_BANDAI_PROBE_URL",DEFAULT_URL).strip())
        success=False;status=None;message="PREMIUM_BANDAI_INVALID_PROBE_URL"
        if url:
            self.diagnostics["probe_url"]=url
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                    headers={"User-Agent":"LotusTracker/1.0.6 PremiumBandaiSourceAssessment", "Accept":"text/html"}) as session:
                    self.diagnostics["requests"]=1
                    async with session.get(url,allow_redirects=False) as response:
                        status=response.status
                        if status!=200:
                            message=f"PREMIUM_BANDAI_HTTP_{status}"
                            if status in {301,302,303,307,308}:
                                target=safe_probe_url(urljoin(url,response.headers.get("Location","")))
                                self.diagnostics["us_redirect_target"]=target
                        elif "html" not in response.headers.get("Content-Type", "").lower():
                            message="PREMIUM_BANDAI_UNEXPECTED_CONTENT_TYPE"
                        else:
                            raw=bytearray()
                            async for chunk in response.content.iter_chunked(65536):
                                raw.extend(chunk)
                                if len(raw)>2*1024*1024:
                                    raise ValueError("RESPONSE_TOO_LARGE")
                            self.diagnostics["response_bytes"]=len(raw)
                            success,message,details=assess_html(raw.decode("utf-8",errors="replace"), url)
                            self.diagnostics.update(details)
            except asyncio.CancelledError:raise
            except Exception as error:
                message="PREMIUM_BANDAI_PROBE_"+type(error).__name__.upper()
        if not success:self.diagnostics["last_error"]=message
        print("PREMIUM BANDAI SOURCE DIAGNOSTICS | " + json.dumps(
            {"probe_message": message, "http_status": status, **self.diagnostics},
            ensure_ascii=True, sort_keys=True), flush=True)
        return MajorRetailerProbe(self.retailer_key,success,"PremiumBandaiPublicUS", "LOW",
                                  status,message,self.get_diagnostics())
    async def discover_products(self, *, limit=20):
        raise RuntimeError("PREMIUM_BANDAI_PRODUCT_PARSER_NOT_VALIDATED_STEP_6K_3D")
