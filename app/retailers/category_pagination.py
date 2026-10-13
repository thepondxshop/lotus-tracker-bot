"""ASIA2: retain only an explicit same-category next page, never filters/search URLs."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode, urlunsplit


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('a', 'link') and 'next' in attrs.get('rel', '').lower().split():
            self.links.append(attrs.get('href', ''))


def next_category_page(html, url):
    current = urlsplit(url)
    if current.scheme != 'https' or current.username or current.password or current.port not in (None, 443):
        return None
    query = parse_qs(current.query)
    if set(query) - {'page', 'p'} or len(query) > 1:
        return None
    raw = next(iter(query.values()), ['1'])
    if len(raw) != 1 or not raw[0].isdigit():
        return None
    page = int(raw[0])
    found = set()
    for link in Links(html).links:
        candidate = urlsplit(urljoin(url, link))
        q = parse_qs(candidate.query)
        if (candidate.scheme != 'https' or candidate.netloc != current.netloc
                or candidate.path != current.path or candidate.fragment
                or len(q) != 1 or set(q) - {'page', 'p'}):
            continue
        key, values = next(iter(q.items()))
        if len(values) != 1 or not values[0].isdigit():
            continue
        if int(values[0]) != page + 1 or int(values[0]) > 20:
            continue
        found.add(urlunsplit((candidate.scheme, candidate.netloc, candidate.path,
                              urlencode({key: int(values[0])}), '')))
    return next(iter(found)) if len(found) == 1 else None


_CURSORS = {}


def rotating_selection(domain, ranked, limit):
    """Bounded Meccha selection: advance through discovered URLs across cycles."""
    if domain.lower().removeprefix('www.') != 'meccha-japan.com' or len(ranked) <= limit:
        return ranked[:limit]
    previous = _CURSORS.get(domain)
    start = ranked.index(previous) + 1 if previous in ranked else 0
    if start >= len(ranked): start = 0
    selected = (ranked[start:] + ranked[:start])[:limit]
    if selected: _CURSORS[domain] = selected[-1]
    return selected
