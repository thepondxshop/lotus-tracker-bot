"""Bounded public HTTPS reads with DNS, redirect, cookie and size isolation."""

import asyncio
import ipaddress
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp

from .extraction import canonical_url, same_site
from .service import CatalogError


MAX_BODY = 2_000_000


class FetchError(CatalogError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PublicResolver(aiohttp.resolver.DefaultResolver):
    async def resolve(self, host, port=0, family=0):
        values = await super().resolve(host, port, family)

        if not values or any(
            not ipaddress.ip_address(value["host"]).is_global
            or ipaddress.ip_address(value["host"]).is_multicast
            for value in values
        ):
            raise OSError("Non-public address rejected")

        return values


@dataclass
class Page:
    url: str
    text: str
    content_type: str


class PublicHTTP:
    def __init__(self, pace=1.5):
        self.session = None
        self.pace = pace
        self.last = 0.0

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(
                resolver=PublicResolver(),
                limit=2,
                use_dns_cache=False,
            ),
            timeout=aiohttp.ClientTimeout(
                total=20,
                connect=8,
            ),
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
            headers={
                "User-Agent": (
                    "LotusReleaseCatalog/1.1 public release metadata"
                ),
                "Accept": (
                    "text/html,application/json,application/xml,text/xml"
                ),
            },
        )
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def get(self, url, origin):
        current = canonical_url(url)

        for _ in range(5):
            if not same_site(current, origin):
                raise FetchError("CROSS_SITE_REDIRECT")

            try:
                address = ipaddress.ip_address(
                    urlsplit(current).hostname
                )
            except ValueError:
                address = None

            if address is not None and (
                not address.is_global or address.is_multicast
            ):
                raise FetchError("NON_PUBLIC_ADDRESS")

            await asyncio.sleep(
                max(
                    0,
                    self.pace - (time.monotonic() - self.last),
                )
            )
            self.last = time.monotonic()

            try:
                async with self.session.get(
                    current,
                    allow_redirects=False,
                ) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        if not response.headers.get("Location"):
                            raise FetchError("INVALID_REDIRECT")

                        current = canonical_url(
                            urljoin(
                                current,
                                response.headers["Location"],
                            )
                        )
                        continue

                    if response.status == 429:
                        raise FetchError("RATE_LIMITED")

                    if response.status in (401, 403):
                        raise FetchError("ACCESS_DENIED")

                    if response.status != 200:
                        raise FetchError(
                            f"HTTP_{response.status}"
                        )

                    content_type = response.headers.get(
                        "Content-Type", ""
                    ).lower()

                    if content_type and not any(
                        value in content_type
                        for value in (
                            "html",
                            "json",
                            "xml",
                            "text/plain",
                        )
                    ):
                        raise FetchError("UNSUPPORTED_CONTENT_TYPE")

                    if (
                        response.content_length is not None
                        and response.content_length > MAX_BODY
                    ):
                        raise FetchError("BODY_TOO_LARGE")

                    chunks = []
                    size = 0

                    async for chunk in response.content.iter_chunked(
                        65536
                    ):
                        size += len(chunk)

                        if size > MAX_BODY:
                            raise FetchError("BODY_TOO_LARGE")

                        chunks.append(chunk)

                    try:
                        text = b"".join(chunks).decode(
                            response.charset or "utf-8-sig",
                            errors="replace",
                        )
                    except LookupError:
                        text = b"".join(chunks).decode(
                            "utf-8-sig",
                            errors="replace",
                        )

                    return Page(
                        current,
                        text,
                        content_type,
                    )

            except FetchError:
                raise
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                OSError,
            ):
                raise FetchError("NETWORK_ERROR") from None

        raise FetchError("TOO_MANY_REDIRECTS")
