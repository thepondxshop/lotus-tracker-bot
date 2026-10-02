"""Product artwork selection; generic social cards are not packaging evidence."""
import re
from urllib.parse import urljoin, urlsplit

HEROINES_PAGE = 'https://en.onepiece-cardgame.com/products/gift-collection.html'
# Product packaging verified on Bandai's page on 2026-10-02. Used to repair
# already stored generic art until the normal publisher refresh completes.
HEROINES_IMAGE = ('https://en.onepiece-cardgame.com/onepiececg/bccard/en/products/'
                  '2026/10/01/1G5QS6sl6UETbgKE/img_item01.webp')


def unsuitable(url):
    path = urlsplit(str(url or '')).path.lower()
    return bool(re.search(r'(?:^|/)(?:ogp|og-image|logo[^/]*)(?:\.|/)|'
                          r'img_thumbnail|no[-_ ]?(?:photo|image)|placeholder|\[temp\]', path))


def one_piece_image(page):
    """Require packaging alt text to match this page, excluding related goods."""
    from .one_piece_products import product_path, comparable
    if not product_path(page.get('url', '')): return page.get('image_url')
    expected = comparable(page.get('title', ''))
    matches = []
    for img in page.get('images', []):
        alt = str(img.get('alt') or '')
        prefix = 'Product packaging image of '
        if not alt.startswith(prefix) or comparable(alt[len(prefix):]) != expected: continue
        value = urljoin(page['url'], img.get('src') or '')
        p = urlsplit(value)
        if p.scheme == 'https' and p.hostname == 'en.onepiece-cardgame.com' and not unsuitable(value):
            if value not in matches: matches.append(value)
    if len(matches) == 1: return matches[0]
    # Ambiguous/no matching packaging: only retain a non-generic prior image.
    old = page.get('image_url')
    return old if old and not unsuitable(old) else None
