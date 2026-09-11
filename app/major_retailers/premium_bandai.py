"""Premium Bandai US source assessment — Step 6K-3D1."""

from __future__ import annotations

import asyncio
import json
import os
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import aiohttp

from .base import (
    MajorRetailerAdapter,
    MajorRetailerCapabilityProfile,
    MajorRetailerProbe,
)
from .registry import major_retailer_adapter


STEP = "6K-3D1"
DEFAULT_URL = "https://p-bandai.com/us"


def safe_probe_url(value):
    try:
        parsed = urlparse(value)

        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {"p-bandai.com", "www.p-bandai.com"}
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not (
                parsed.path == "/us"
                or parsed.path.startswith("/us/")
            )
        ):
            return None

        return "https://" + parsed.hostname + parsed.path

    except (ValueError, TypeError):
        return None


class SourcePage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.script_count = 0
        self.json_ld_count = 0
        self.product_links = set()
        self.title_parts = []
        self.in_title = False
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "title":
            self.in_title = True

        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")

            if key in {
                "og:title",
                "og:type",
                "product:price:amount",
                "product:price:currency",
            }:
                self.meta[key] = str(
                    attrs.get("content", "")
                )[:180]

        if tag == "script":
            self.script_count += 1

            if (
                attrs.get("type", "").lower()
                == "application/ld+json"
            ):
                self.json_ld_count += 1

        if tag == "a":
            value = attrs.get("href")

            if isinstance(value, str):
                url = safe_probe_url(
                    urljoin(DEFAULT_URL, value)
                )

                if (
                    url
                    and urlparse(url).path.startswith("/us/item/")
                ):
                    self.product_links.add(url)

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data[:180])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False


def assess_html(body):
    challenge_markers = (
        "access denied",
        "verify you are human",
        "robot or human",
        "pardon our interruption",
    )

    if any(marker in body.lower() for marker in challenge_markers):
        return False, "PREMIUM_BANDAI_CHALLENGE_PAGE", {}

    if not body.strip():
        return False, "PREMIUM_BANDAI_EMPTY_RESPONSE", {}

    parser = SourcePage()
    parser.feed(body)

    diagnostics = {
        "script_tags": parser.script_count,
        "json_ld_blocks": parser.json_ld_count,
        "candidate_item_links": len(parser.product_links),
        "candidate_item_samples": sorted(parser.product_links)[:3],
        "page_title": " ".join(
            " ".join(parser.title_parts).split()
        )[:180],
        "page_metadata_candidates": parser.meta,
    }

    return (
        True,
        "PREMIUM_BANDAI_PAGE_REACHABLE_NOT_PRODUCT_VALIDATED",
        diagnostics,
    )


@major_retailer_adapter("premium_bandai")
class PremiumBandaiMajorRetailerAdapter(MajorRetailerAdapter):
    retailer_key = "premium_bandai"
    version = "1.0.6-6K3D1"

    @property
    def capabilities(self):
        return MajorRetailerCapabilityProfile()

    async def healthcheck(self):
        self.diagnostics = {
            "integration_state": "SOURCE_ASSESSMENT_ONLY",
            "step": STEP,
            "requests": 0,
            "product_parser_verified": False,
            "stock_verified": False,
            "last_error": None,
        }

        url = safe_probe_url(
            os.getenv(
                "PREMIUM_BANDAI_PROBE_URL",
                DEFAULT_URL,
            ).strip()
        )

        success = False
        status = None
        message = "PREMIUM_BANDAI_INVALID_PROBE_URL"

        if url:
            self.diagnostics["probe_url"] = url

            try:
                timeout = aiohttp.ClientTimeout(total=12)
                headers = {
                    "User-Agent": (
                        "LotusTracker/1.0.6 "
                        "PremiumBandaiSourceAssessment"
                    ),
                    "Accept": "text/html",
                }

                async with aiohttp.ClientSession(
                    timeout=timeout,
                    headers=headers,
                ) as session:
                    self.diagnostics["requests"] = 1

                    async with session.get(
                        url,
                        allow_redirects=False,
                    ) as response:
                        status = response.status

                        if status != 200:
                            message = f"PREMIUM_BANDAI_HTTP_{status}"

                            if status in {301, 302, 303, 307, 308}:
                                target = safe_probe_url(
                                    urljoin(
                                        url,
                                        response.headers.get(
                                            "Location", ""
                                        ),
                                    )
                                )
                                self.diagnostics[
                                    "us_redirect_target"
                                ] = target

                        elif "html" not in response.headers.get(
                            "Content-Type", ""
                        ).lower():
                            message = (
                                "PREMIUM_BANDAI_UNEXPECTED_CONTENT_TYPE"
                            )

                        else:
                            raw = bytearray()

                            async for chunk in (
                                response.content.iter_chunked(65536)
                            ):
                                raw.extend(chunk)

                                if len(raw) > 2 * 1024 * 1024:
                                    raise ValueError(
                                        "RESPONSE_TOO_LARGE"
                                    )

                            self.diagnostics["response_bytes"] = len(raw)

                            success, message, details = assess_html(
                                raw.decode("utf-8", errors="replace")
                            )

                            self.diagnostics.update(details)

            except asyncio.CancelledError:
                raise

            except Exception as error:
                message = (
                    "PREMIUM_BANDAI_PROBE_"
                    + type(error).__name__.upper()
                )

        if not success:
            self.diagnostics["last_error"] = message

        print(
            "PREMIUM BANDAI SOURCE DIAGNOSTICS | "
            + json.dumps(
                {
                    "probe_message": message,
                    "http_status": status,
                    **self.diagnostics,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )

        return MajorRetailerProbe(
            retailer_key=self.retailer_key,
            success=success,
            source_name="PremiumBandaiPublicUS",
            confidence="LOW",
            http_status=status,
            message=message,
            diagnostics=self.get_diagnostics(),
        )

    async def discover_products(self, *, limit=20):
        raise RuntimeError(
            "PREMIUM_BANDAI_PRODUCT_PARSER_NOT_VALIDATED_STEP_6K_3D"
        )
