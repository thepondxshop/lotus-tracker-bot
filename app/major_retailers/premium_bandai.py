"""Lotus 6K-3D: Premium Bandai US source-access assessment only.

No product extraction, persistence, stock inference, or customer alerts.
"""
from __future__ import annotations
import asyncio
import os
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import aiohttp
from .base import MajorRetailerAdapter, MajorRetailerCapabilityProfile, MajorRetailerProbe
from .registry import major_retailer_adapter

STEP = "6K-3D"
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


class SourcePage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.script_count = 0
        self.json_ld_count = 0
        self.product_links = set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag == "script": self.script_count += 1
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.json_ld_count += 1
        if tag == "a":
            value=attrs.get("href")
            if isinstance(value,str):
                url=safe_probe_url(urljoin(DEFAULT_URL,value))
                if url and urlparse(url).path.startswith("/us/item/"):
                    self.product_links.add(url)


def assess_html(body):
    # A positive assessment is only page access, never product/stock validation.
    if any(s in body.lower() for s in ("access denied", "verify you are human", "robot or human", "pardon our interruption")):
        return False, "PREMIUM_BANDAI_CHALLENGE_PAGE", {}
    parser=SourcePage();parser.feed(body)
    if not body.strip():return False,"PREMIUM_BANDAI_EMPTY_RESPONSE",{}
    return True,"PREMIUM_BANDAI_PAGE_REACHABLE_NOT_PRODUCT_VALIDATED",{
        "script_tags":parser.script_count,"json_ld_blocks":parser.json_ld_count,
        "candidate_item_links":len(parser.product_links),
        "candidate_item_samples":sorted(parser.product_links)[:3],
    }


@major_retailer_adapter("premium_bandai")
class PremiumBandaiMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "premium_bandai"
    version = "1.0.6-6K3D"
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
                            success,message,details=assess_html(raw.decode("utf-8",errors="replace"))
                            self.diagnostics.update(details)
            except asyncio.CancelledError:raise
            except Exception as error:
                message="PREMIUM_BANDAI_PROBE_"+type(error).__name__.upper()
        if not success:self.diagnostics["last_error"]=message
        return MajorRetailerProbe(self.retailer_key,success,"PremiumBandaiPublicUS", "LOW",
                                  status,message,self.get_diagnostics())
    async def discover_products(self, *, limit=20):
        raise RuntimeError("PREMIUM_BANDAI_PRODUCT_PARSER_NOT_VALIDATED_STEP_6K_3D")
