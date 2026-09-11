"""Lotus 6K-3D: Premium Bandai US source-access assessment only.

No product extraction, persistence, stock inference, or customer alerts.
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

STEP = "6K-3D2"
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
    return False, message, details


@major_retailer_adapter("premium_bandai")
class PremiumBandaiMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "premium_bandai"
    version = "1.0.6-6K3D2"
    @property
    def capabilities(self):
        # No product capability is claimed from a source-access probe.
        return MajorRetailerCapabilityProfile()
    async def healthcheck(self):
        self.diagnostics={"integration_state":"SOURCE_ASSESSMENT_ONLY", "step":STEP,
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
