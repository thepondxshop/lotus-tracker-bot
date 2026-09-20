"""Public product facts only. Never execute page scripts or infer stock from prices."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from .service import CatalogError, digest, public_source_url
from .distributors import product_url, public_data, phd_sku_fragment


GAMES = (
    ("One Piece", r"\bone\s*piece\b|\b(?:PEB|PRB|OP)[ -]?\d+\b"),
    ("Pokemon", r"\bpokemon\b"),
    ("Gundam", r"\bgundam\b"),
    ("Dragon Ball Fusion World", r"\bfusion world\b"),
    ("Riftbound", r"\briftbound\b"),
    ("Palworld", r"\bpalworld\b"),
    ("Naruto", r"\bnaruto\b"),
    ("Cyberpunk TCG", r"\bcyberpunk\b"),
    ("Azuki TCG", r"\bazuki\b"),
    ("Hellbreak TCG", r"\bhellbreak\b"),
)

CODE = re.compile(
    r"(?<![A-Z0-9])(?:PEB|PRB|OP|EB|ST|GD|FB|FS|EX)[ -]?\d{1,3}(?![A-Z0-9])",
    re.I,
)


def norm(value):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", str(value or ""))
            if not unicodedata.combining(c)
        ).casefold().split()
    )


def scope(value):
    value = norm(value)
    aliases = {
        "en": "english",
        "eng": "english",
        "ja": "japanese",
        "jpn": "japanese",
        "usa": "us",
        "united states": "us",
        "es": "spanish",
        "fr": "french",
        "de": "german",
    }
    unknown_values = (
        "", "unknown", "tbd", "tba", "?", "n/a", "none", "unspecified",
    )
    return "unknown" if value in unknown_values else aliases.get(value, value)


def code(value):
    value = str(value or "").strip()
    if not CODE.fullmatch(value):
        return None
    prefix, number = re.fullmatch(r"([A-Za-z]+)[ -]?(\d+)", value).groups()
    return f"{prefix.upper()}{int(number):02d}"


def canonical_url(value):
    parsed = urlsplit(public_source_url(value, required=True))
    hostname = parsed.hostname.lower().rstrip(".")
    if ":" in hostname:
        hostname = f"[{hostname}]"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in ("gclid", "fbclid")
    ]
    result = urlunsplit((
        "https",
        hostname,
        parsed.path or "/",
        urlencode(sorted(query)),
        phd_sku_fragment(value),
    ))
    if len(result) > 1500:
        raise CatalogError("Source URL is too long.")
    return result


def host(value):
    return (
        (urlsplit(value).hostname or "")
        .lower()
        .removeprefix("www.")
        .rstrip(".")
    )


def same_site(first, second):
    return host(first) == host(second)


def url_key(value):
    parsed = urlsplit(canonical_url(value))
    fragment = phd_sku_fragment(value)
    if fragment:
        return digest(host(value), parsed.path, parsed.query, fragment)
    return digest(host(value), parsed.path, parsed.query)


def is_product(value):
    path = urlsplit(value).path.lower()
    return product_url(value) or bool(
        re.search(r"/(?:products?/[^/]+|pc_product_detail\.asp)", path)
        or (
            host(value) == "gtsdistribution.com"
            and path.startswith("/card-games/")
            and path.endswith(".asp")
        )
    )


def product_format(title, body=""):
    title = norm(title).replace("_", " ")
    if re.search(r"\bcase\b", title):
        return "CASE"
    if (
        re.search(r"\b(box|display|elite trainer)\b", title)
        or re.search(r"sold as (?:a )?display", body, re.I)
    ):
        return "BOX"
    if re.search(r"\b(deck|starter)\b", title):
        return "DECK"
    if re.search(r"\bpack\b", title):
        return "PACK"
    return "UNKNOWN"


def languages(title):
    return {
        match[0].title()
        for match in re.finditer(
            r"\b(?:English|Japanese|French|Spanish|German|Korean|"
            r"(?:Traditional |Simplified )?Chinese)\b",
            title,
            re.I,
        )
    }


class HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.schemas = []
        self.skip = 0
        self.script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip += 1
            if tag == "script":
                self.script = (
                    []
                    if attrs.get("type", "").lower() == "application/ld+json"
                    else None
                )
        if tag in ("p", "div", "br", "li", "tr", "td", "h1", "h2"):
            self.parts.append("\n")
        if tag == "a" and attrs.get("href") and len(self.links) < 2000:
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            if tag == "script" and self.script is not None:
                self.schemas.append("".join(self.script))
                self.script = None
            self.skip = max(0, self.skip - 1)
        if tag in ("p", "div", "li", "tr", "td"):
            self.parts.append("\n")

    def handle_data(self, value):
        if self.script is not None:
            self.script.append(value)
        if not self.skip:
            self.parts.append(value)

    @property
    def text(self):
        return "\n".join(
            " ".join(part.split())
            for part in "".join(self.parts).splitlines()
            if part.strip()
        )


def visible(value):
    page = HTML()
    page.feed(unescape(str(value or "")))
    return page.text


def label(body, name):
    match = re.search(
        rf"(?im)^\s*{name}(?=\s*:|\s*$)\s*:?\s*\n?\s*([^\n]+)",
        body,
    )
    return match[1].strip(" :*") if match else None


def parse_date(value, gts=False):
    if not value:
        return None, False
    formats = ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"]
    if gts:
        formats.append("%m/%d/%Y")
    for fmt in formats:
        try:
            text = str(value).strip()
            if fmt == "%Y-%m-%d" and not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", text
            ):
                continue
            return datetime.strptime(text, fmt).date().isoformat(), False
        except ValueError:
            pass
    return None, True


@dataclass
class Candidate:
    url: str
    title: str
    game: str
    sku: str | None = None
    set_code: str | None = None
    product_format: str = "UNKNOWN"
    region: str = "UNKNOWN"
    language: str = "UNKNOWN"
    release_date: str | None = None
    order_due_date: str | None = None
    manufacturer: str | None = None
    cards_per_pack: int | None = None
    packs_per_box: int | None = None
    boxes_per_case: int | None = None
    all_foil: bool | None = None
    reported_rarity_total: str | None = None
    computed_rarity_total: str | None = None
    issues: list = field(default_factory=list)
    evidence: str = ""
    extractor: str = ""

    def payload(self):
        return asdict(self)

    def fingerprint(self):
        data = self.payload()
        data.pop("evidence")
        return digest(data)


@dataclass
class Document:
    products: list = field(default_factory=list)
    product_links: list = field(default_factory=list)
    listing_links: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    supported: bool = False
    diagnostics: list = field(default_factory=list)


def candidate(data, url, settings, extractor):
    title = " ".join(str(data.get("name") or "").split())
    body = (
        visible(data.get("description"))
        + "\n"
        + str(data.get("configuration") or "")
    )
    text = norm(title + " " + str(data.get("game") or ""))

    if not title or re.search(
        r"\b(funko|lego|nanoblock|model kit|plastic model|"
        r"puzzle|plush|statue|figure)\b",
        text,
    ):
        return None

    if "dragon ball" in text and "fusion world" not in text:
        return None

    games = [
        game
        for game, pattern in GAMES
        if re.search(pattern, text)
    ]
    game = (
        games[0]
        if len(games) == 1
        else settings.get("game") if not games else None
    )

    if not game or (
        settings.get("game")
        and norm(game) != norm(settings["game"])
    ):
        return None

    if not re.search(
        r"\b(tcg|ccg|card game|trading cards?|booster|elite trainer|"
        r"starter deck|battle deck)\b",
        norm(title + " " + body[:5000]),
    ) and not CODE.search(title):
        return None

    row = Candidate(
        canonical_url(url),
        title[:180],
        game,
        evidence=body[:3000],
        extractor=extractor,
    )

    if len(title) > 180:
        row.issues.append("TITLE_TRUNCATED")

    codes = {code(match[0]) for match in CODE.finditer(title)}
    if code(data.get("set_code")):
        codes.add(code(data["set_code"]))
    if len(codes) == 1:
        row.set_code = next(iter(codes))
    elif len(codes) > 1:
        row.issues.append("MULTIPLE_SET_CODES")

    raw_sku = str(data.get("sku") or label(body, "SKU") or "").strip()
    row.sku = raw_sku.upper() if scope(raw_sku) != "unknown" else None

    maker = data.get("manufacturer") or label(body, "Manufacturer")
    row.manufacturer = (
        str(
            maker.get("name", "")
            if isinstance(maker, dict)
            else maker or ""
        )[:180]
        or None
    )

    fmt = str(data.get("product_format") or "").upper()
    row.product_format = (
        fmt
        if fmt in ("PACK", "BOX", "CASE", "DECK", "SET", "ACCESSORY")
        else product_format(title, body)
    )

    langs = languages(title)
    if len(langs) > 1:
        row.issues.append("MULTIPLE_LANGUAGES")

    for name in ("region", "language"):
        explicit = data.get(name) or label(
            body,
            "(?:Product )?Language"
            if name == "language"
            else "(?:Sales )?Region",
        )

        if name == "language" and len(langs) == 1:
            from_title = next(iter(langs))
            if scope(explicit) not in ("unknown", scope(from_title)):
                row.issues.append("SOURCE_SCOPE_CONFLICT")
            explicit = from_title

        configured = settings.get(name, "UNKNOWN")
        if scope(explicit) != "unknown":
            setattr(row, name, str(explicit)[:40])
            if scope(configured) not in ("unknown", scope(explicit)):
                row.issues.append("SOURCE_SCOPE_CONFLICT")
        elif scope(configured) != "unknown":
            setattr(row, name, configured)

    date_fields = (
        ("release_date", "releaseDate", "Release Date"),
        ("order_due_date", "order_due_date", "Order Due Date"),
    )
    for name, key, heading in date_fields:
        date_value, bad = parse_date(
            data.get(key) or data.get(name) or label(body, heading),
            host(url) in ("gtsdistribution.com", "southernhobby.com"),
        )
        setattr(row, name, date_value)
        if bad:
            row.issues.append("INVALID_" + name.upper())

    config = re.search(
        r"(\d+)\s*cards?\s*/\s*(\d+)\s*packs?\s*/\s*(\d+)\s*displays?",
        body,
        re.I,
    )
    patterns = [
        r"booster\s+pack\s*:\s*(\d+)\s*cards?",
        r"(?:display\s+box|booster\s+box)\s*:\s*(\d+)\s*packs?",
        r"case\s*:\s*(\d+)\s*(?:display\s+boxes|displays?|boxes)",
    ]

    for index, name in enumerate((
        "cards_per_pack", "packs_per_box", "boxes_per_case",
    )):
        values = {
            int(match[1])
            for match in re.finditer(patterns[index], body, re.I)
        }
        if config:
            values.add(int(config[index + 1]))
        value = data.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            values.add(value)
        if len(values) == 1 and 1 <= next(iter(values)) <= 10000:
            setattr(row, name, next(iter(values)))
        elif values:
            row.issues.append("PACKAGING_CONFLICT")

    positive_foil = bool(re.search(
        r"all[ -]foil|all (?:the )?cards are foiled",
        body,
        re.I,
    ))
    negative_foil = bool(re.search(
        r"not all (?:the )?cards are foiled|not all[ -]foil",
        body,
        re.I,
    ))
    explicit_foil = data.get("all_foil")

    if isinstance(explicit_foil, bool):
        row.all_foil = explicit_foil
        if (
            (explicit_foil and negative_foil)
            or (
                not explicit_foil
                and positive_foil
                and not negative_foil
            )
        ):
            row.issues.append("FOIL_CLAIM_CONFLICT")
    elif negative_foil:
        row.all_foil = False
    elif positive_foil:
        row.all_foil = True

    counts = []
    for rarity in (
        "Leader", "Common", "Rare", "Super Rare",
        "Secret Rare", "Special Card", "DON!! Card",
    ):
        match = re.search(
            rf"(?im)^\s*[•♦*\-]*\s*{re.escape(rarity)}"
            rf"\s*[*]*\s*[x×]\s*(\d+)\b",
            body,
        )
        counts.append(int(match[1]) if match else None)

    total = re.search(
        r"(\d+)\s*\+\s*(\d+)\s*card types",
        body,
        re.I,
    )
    if total:
        row.reported_rarity_total = f"{total[1]}+{total[2]}"
    if all(number is not None for number in counts):
        row.computed_rarity_total = f"{sum(counts[:-1])}+{counts[-1]}"
        if total and row.computed_rarity_total != row.reported_rarity_total:
            row.issues.append("RARITY_COUNT_MISMATCH")

    row.issues = sorted(set(row.issues))
    return row


def nodes(data):
    stack = [data]
    count = 0

    while stack and count < 5000:
        item = stack.pop()
        count += 1

        if isinstance(item, list):
            stack.extend(item[:500])
        elif isinstance(item, dict):
            types = item.get("@type", [])
            if (
                types == "Product"
                or (isinstance(types, list) and "Product" in types)
                or (item.get("name") and item.get("sku"))
            ):
                yield item

            for key in (
                "@graph", "products", "items",
                "itemListElement", "item", "data",
            ):
                if key in item:
                    stack.append(item[key])


def extract(url, body, settings=None, content_type="text/html"):
    settings = settings or {}
    doc = Document()
    page = HTML()
    data = []

    if "xml" in content_type or body.lstrip().startswith("<?xml"):
        if re.search(r"<!DOCTYPE|<!ENTITY", body, re.I):
            doc.issues = ["UNSUPPORTED_XML_DTD"]
            return doc

        try:
            root = ET.fromstring(body)
            index = root.tag.rsplit("}", 1)[-1] == "sitemapindex"
            doc.supported = True

            for node in root.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                link = node.get("href") or node.text
                if tag not in ("loc", "link") or not link:
                    continue
                try:
                    link = canonical_url(urljoin(url, link.strip()))
                except CatalogError:
                    continue
                if same_site(url, link):
                    target = (
                        doc.listing_links if index else doc.product_links
                    )
                    target.append(link)
        except ET.ParseError:
            doc.issues = ["INVALID_XML"]

        doc.product_links = doc.product_links[:2000]
        doc.listing_links = doc.listing_links[:200]
        return doc

    if "json" in content_type or body.lstrip().startswith(("{", "[")):
        try:
            data = list(nodes(json.loads(body)))
        except (ValueError, RecursionError):
            doc.issues = ["INVALID_JSON"]
            return doc
    else:
        page.feed(body)

        for raw in page.schemas[:30]:
            try:
                data.extend(nodes(json.loads(raw)))
            except (ValueError, RecursionError):
                doc.issues.append("INVALID_JSON_LD")

        for href in page.links:
            try:
                link = canonical_url(urljoin(url, href))
            except CatalogError:
                continue
            if same_site(url, link):
                target = (
                    doc.product_links
                    if is_product(link)
                    else doc.listing_links
                )
                target.append(link)

    gts = []
    total = 0

    if host(url) == "gtsdistribution.com":
        for match in re.finditer(
            r"\bvar\s+(?:product|products|productResults)\s*=\s*",
            body,
        ):
            try:
                value = json.JSONDecoder().raw_decode(
                    body[match.end():]
                )[0]
            except (ValueError, RecursionError):
                continue

            if isinstance(value, dict) and isinstance(
                value.get("products"), list
            ):
                total = value.get("count", 0)
                value = value["products"]

            for product in (
                value if isinstance(value, list) else [value]
            ):
                if (
                    not isinstance(product, dict)
                    or not product.get("key")
                    or not product.get("name")
                ):
                    continue

                fields = {
                    str(item.get("label", "")).strip(" :").casefold():
                        item.get("value")
                    for item in (
                        product.get("searchfields") or {}
                    ).values()
                    if isinstance(item, dict)
                }

                gts.append(dict(
                    name=product["name"],
                    sku=product.get("sku"),
                    description=product.get("description", ""),
                    manufacturer=fields.get("manufacturer"),
                    configuration=fields.get("configurations"),
                    region=fields.get("region"),
                    language=fields.get("language"),
                    release_date=(
                        product.get("release_date_display")
                        or product.get("release_date")
                    ),
                    order_due_date=product.get("preorder_date_display"),
                    url=urljoin(
                        url,
                        "/pc_product_detail.asp?"
                        + urlencode({"key": product["key"]}),
                    ),
                ))

        if gts:
            data = gts
            doc.product_links = []

            current = re.search(
                r"oConfig\.searchConfig\.page\s*=\s*(\d+)",
                body,
            )
            size = re.search(
                r"oConfig\.searchConfig\.rpp\s*=\s*(\d+)",
                body,
            )

            if (
                current
                and size
                and isinstance(total, int)
                and 0 < int(size[1]) <= 200
                and int(current[1]) * int(size[1]) < total
            ):
                parsed = urlsplit(url)
                params = dict(parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                ))
                params["page"] = str(int(current[1]) + 1)

                doc.listing_links.insert(
                    0,
                    canonical_url(urlunsplit((
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        urlencode(params),
                        "",
                    ))),
                )

    distributor = public_data(url, body, doc.diagnostics) if 'html' in content_type else None
    if distributor is not None:
        data, doc.product_links, doc.listing_links, extra_issues = distributor
        doc.issues.extend(extra_issues)
    doc.supported = bool(data or doc.product_links or doc.listing_links)

    for product in data[:200]:
        raw = product.get("url") or (
            url if len(data) == 1 else None
        )
        if not isinstance(raw, str):
            continue

        try:
            link = canonical_url(urljoin(url, raw))
        except CatalogError:
            continue
        if not same_site(url, link):
            continue

        row = candidate(
            product,
            link,
            settings,
            product.get('_extractor') or ("GTS_PUBLIC_PRODUCT_JSON" if gts else "PRODUCT_DATA"),
        )
        if row:
            row.issues = sorted(set(row.issues + product.get('_issues', [])))
            doc.products.append(row)
            if row.extractor != 'GROSNOR_PUBLIC_LISTING':
                doc.product_links.append(link)

    unique = {}
    for row in doc.products:
        key = url_key(row.url)
        if (
            key in unique
            and row.fingerprint() != unique[key].fingerprint()
        ):
            unique[key].issues.append("MULTIPLE_PRODUCTS_SAME_URL")
        else:
            unique[key] = row

    doc.products = list(unique.values())
    doc.product_links = list(dict.fromkeys(doc.product_links))[:2000]
    doc.listing_links = list(dict.fromkeys(doc.listing_links))[:200]

    return doc
