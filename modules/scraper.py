"""
eBay Hub UK - Amazon Product Scraper & Specification Parser
Scrapes product data from Amazon. Auto-detects the locale where the ASIN
lives by cascading through AMAZON_DOMAINS; a pallet can override with an
explicit domain when the auto-detection picks the wrong variant. Non-
English locales are fetched via /-/en/ so titles/specs come back in
English regardless. Parses pasted joblot specs to extract product info.
"""

import re
import time
import json
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AMAZON_DOMAINS = [
    ("amazon.co.uk", "GBP"),
    ("amazon.com", "USD"),
    ("amazon.de", "EUR"),
    ("amazon.pl", "PLN"),
    ("amazon.fr", "EUR"),
    ("amazon.it", "EUR"),
    ("amazon.es", "EUR"),
    ("amazon.nl", "EUR"),
    ("amazon.se", "SEK"),
]

import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

USER_AGENT = USER_AGENTS[0]

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ASIN pattern: starts with B0 followed by 8 alphanumeric chars
ASIN_RE = re.compile(r'\b(B0[A-Z0-9]{8})\b')


def _looks_non_english(text):
    """Detect titles that contain accented letters from Polish, German,
    French, Italian, Swedish, etc. Those products came from a non-English
    locale where Amazon's /-/en/ prefix didn't have a translation. We then
    re-scrape the title from amazon.co.uk/amazon.com so the uncle's eBay
    listings go out in English without him having to edit every title.
    Pure ASCII titles with just weird punctuation (®, ™, ", etc.) do NOT
    count as non-English — those are fine for English listings."""
    if not text:
        return False
    # Any alphabetic character with a codepoint above 127 means non-ASCII
    # script: ą/ä/é/ü/ö/ß/ñ/å etc.
    return any(c.isalpha() and ord(c) > 127 for c in text)

# EAN pattern: 13-digit number (also catches UPC-A 12-digit if needed)
EAN_RE = re.compile(r'\b(\d{13})\b')

# Quantity patterns: "x2", "2x", "qty: 3", "qty 3", "quantity: 3", etc.
QTY_RE = re.compile(
    r'(?:^|\s)(\d{1,4})\s*[xX]\b'       # "2x" or "2 x"
    r'|[xX]\s*(\d{1,4})\b'               # "x2" or "x 2"
    r'|(?:qty|quantity)\s*[:\-]?\s*(\d{1,4})'  # "qty: 3", "quantity 3"
    , re.IGNORECASE
)

# Amazon price patterns on page
PRICE_RE = re.compile(r'[\u00a3$\u20ac]\s*([\d,]+\.?\d*)')


# ---------------------------------------------------------------------------
# Amazon Scraper
# ---------------------------------------------------------------------------

def _create_session():
    """Create a requests session with randomized headers to avoid blocks."""
    session = requests.Session()
    headers = HEADERS.copy()
    headers['User-Agent'] = random.choice(USER_AGENTS)
    session.headers.update(headers)
    # Visit homepage first to get cookies (anti-CAPTCHA)
    try:
        session.get('https://www.amazon.co.uk/', timeout=8, allow_redirects=True)
    except:
        pass
    return session


def _extract_price(soup):
    """Extract price from Amazon product page."""
    # Try multiple price selectors
    price_selectors = [
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '.a-price .a-offscreen',
        '#corePrice_feature_div .a-offscreen',
        '#tp_price_block_total_price_ww .a-offscreen',
        '.priceToPay .a-offscreen',
        '#price_inside_buybox',
        '#newBuyBoxPrice',
        'span.a-color-price',
    ]

    for selector in price_selectors:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            match = PRICE_RE.search(text)
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except (ValueError, IndexError):
                    continue
    return None


def _extract_title(soup):
    """Extract product title from Amazon page."""
    el = soup.select_one('#productTitle')
    if el:
        return el.get_text(strip=True)
    return None


def _extract_image(soup):
    """Extract main product image URL from Amazon page.
    Tries a cascade of selectors — Amazon swaps layouts between regular
    listings, 'Currently unavailable' pages, ebooks, and mobile-style
    pages. We were previously missing all 'Currently unavailable' pages
    because they don't always use #landingImage."""

    def _best_from_dynamic(img_tag):
        """data-a-dynamic-image is a JSON blob of URL -> [width, height].
        Pick the biggest. This is the most reliable source on modern
        Amazon pages because it's the same thing the gallery JS reads."""
        if not img_tag:
            return None
        dyn = img_tag.get('data-a-dynamic-image')
        if dyn:
            try:
                data = json.loads(dyn)
                if isinstance(data, dict) and data:
                    # Pick URL with the largest width
                    best = max(data.items(), key=lambda kv: (kv[1][0] if isinstance(kv[1], list) and kv[1] else 0))
                    return best[0]
            except Exception:
                pass
        return None

    def _src_of(img_tag):
        if not img_tag:
            return None
        src = (
            _best_from_dynamic(img_tag)
            or img_tag.get('data-old-hires')
            or img_tag.get('data-a-hires')
            or img_tag.get('src')
        )
        if src and 'placeholder' not in src.lower() and 'transparent' not in src.lower():
            return src
        return None

    # Try the well-known selectors in priority order. "Currently unavailable"
    # pages usually still render #landingImage, but sometimes fall back to
    # #imgTagWrapperId img or the dynamic-image container.
    for sel in (
        '#landingImage',
        '#imgBlkFront',
        '#imgTagWrapperId img',
        '#main-image-container img',
        '.imgTagWrapper img',
        '#ebooksImgBlkFront',
        'img.a-dynamic-image',
        'img[data-a-dynamic-image]',
    ):
        img = soup.select_one(sel)
        src = _src_of(img)
        if src:
            return src

    # Last resort: Open Graph meta tag — Amazon always sets this even
    # for unavailable products.
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get('content'):
        src = og['content']
        if 'placeholder' not in src.lower():
            return src

    return None


def _extract_bullet_points(soup):
    """Extract feature bullet points from Amazon page."""
    bullets = []
    feature_div = soup.select_one('#feature-bullets')
    if feature_div:
        for li in feature_div.select('li span.a-list-item'):
            text = li.get_text(strip=True)
            if text and len(text) > 5:
                bullets.append(text)

    if not bullets:
        # Alternative: productDescription
        desc = soup.select_one('#productDescription')
        if desc:
            text = desc.get_text(strip=True)
            if text:
                bullets = [text[:500]]

    return bullets


def _extract_all_images(soup, page_text='', asin=''):
    """Extract all product images (up to 8) from Amazon page.
    Uses same proven logic as Akces Hub scraper."""
    images = []

    # Method 1: colorImages JSON (best method — gets unique images)
    color_match = re.search(r"'colorImages'\s*:\s*\{[^}]*'initial'\s*:\s*(\[[^\]]+\])", page_text)
    if not color_match:
        color_match = re.search(r'"colorImages"\s*:\s*\{[^}]*"initial"\s*:\s*(\[[^\]]+\])', page_text)

    if color_match:
        try:
            gallery_str = color_match.group(1).replace("'", '"')
            gallery_data = json.loads(gallery_str)
            for item in gallery_data:
                if isinstance(item, dict):
                    img_url = item.get('hiRes') or item.get('large') or (item.get('main', {}) or {}).get('url')
                    if img_url and '/I/' in img_url:
                        clean_url = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', img_url)
                        if clean_url not in images:
                            images.append(clean_url)
        except:
            pass

    # Method 2: imageGalleryData
    if len(images) < 4:
        gallery_match = re.search(r'"imageGalleryData"\s*:\s*(\[[^\]]+\])', page_text)
        if gallery_match:
            try:
                urls = re.findall(r'"mainUrl"\s*:\s*"([^"]+)"', gallery_match.group(1))
                for url in urls:
                    if '/I/' in url:
                        clean_url = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', url)
                        if clean_url not in images:
                            images.append(clean_url)
            except:
                pass

    # Method 3: All hiRes/large URLs from entire page
    if len(images) < 4:
        all_hires = re.findall(r'"hiRes"\s*:\s*"(https://[^"]+)"', page_text)
        all_large = re.findall(r'"large"\s*:\s*"(https://[^"]+)"', page_text)
        for img_list in [all_hires, all_large]:
            for img in img_list:
                if '/I/' in img and not any(x in img.lower() for x in ['icon', 'button', 'sprite', 'transparent']):
                    clean_url = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', img)
                    if clean_url not in images:
                        images.append(clean_url)
                if len(images) >= 8:
                    break

    # Method 4: data-old-hires attributes
    if len(images) < 4:
        hires_attrs = re.findall(r'data-old-hires="([^"]+)"', page_text)
        for img in hires_attrs:
            if '/I/' in img:
                clean_url = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', img)
                if clean_url not in images:
                    images.append(clean_url)

    # Method 5: landingImageUrl
    if len(images) < 4:
        landing = re.search(r'"landingImageUrl"\s*:\s*"([^"]+)"', page_text)
        if landing:
            clean_url = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', landing.group(1))
            if clean_url not in images:
                images.append(clean_url)

    # NO asin-based fallback here. The old code used to return
    # [f"https://m.media-amazon.com/images/I/{asin}._AC_SL1500_.jpg"]
    # when nothing else was found, but Amazon's image-ID namespace is
    # completely separate from the ASIN namespace — the URL looks
    # plausible but almost always 404s. Worse, it was being written
    # straight into the DB and then passing every "has image" check,
    # causing the same product to be re-scraped forever with no
    # improvement. Now: return [] here and let the caller decide how
    # to handle the "no image available" case (manual upload).
    return images[:8]


def _extract_item_specifics(soup):
    """Extract item specifics (brand, model, material, etc.) from Amazon product page."""
    specs = {}

    # Method 1: Product details table (techSpec)
    for table_id in ['productDetails_techSpec_section_1', 'productDetails_techSpec_section_2',
                     'productDetails_detailBullets_sections1']:
        table = soup.select_one(f'#{table_id}')
        if table:
            for row in table.select('tr'):
                th = row.select_one('th')
                td = row.select_one('td')
                if th and td:
                    key = th.get_text(strip=True).rstrip(':').strip()
                    val = td.get_text(strip=True)
                    if key and val and val.lower() not in ('', '-', 'n/a'):
                        specs[key] = val

    # Method 2: Detail Bullets feature div
    detail_bullets = soup.select_one('#detailBullets_feature_div')
    if detail_bullets:
        for li in detail_bullets.select('li'):
            spans = li.select('span.a-text-bold')
            for bold_span in spans:
                key = bold_span.get_text(strip=True).rstrip(':').strip()
                # The value is in the next sibling span
                sibling = bold_span.find_next_sibling('span')
                if sibling:
                    val = sibling.get_text(strip=True)
                    if key and val and key not in ('Customer Reviews', 'Best Sellers Rank',
                                                    'ASIN', 'Date First Available'):
                        specs[key] = val

    # Method 3: Product information tables (below-the-fold)
    for table in soup.select('#productDetails_db_sections table, .prodDetTable'):
        for row in table.select('tr'):
            th = row.select_one('th')
            td = row.select_one('td')
            if th and td:
                key = th.get_text(strip=True).rstrip(':').strip()
                val = td.get_text(strip=True)
                if key and val and val.lower() not in ('', '-', 'n/a'):
                    if key not in ('Customer Reviews', 'Best Sellers Rank',
                                   'ASIN', 'Date First Available'):
                        specs[key] = val

    # Clean up: only keep useful specifics for eBay
    useful_keys = {
        'Brand', 'Manufacturer', 'Model', 'Model Number', 'Model Name',
        'Colour', 'Color', 'Material', 'Material Type', 'Weight',
        'Item Weight', 'Product Dimensions', 'Package Dimensions',
        'Power Source', 'Voltage', 'Wattage', 'Batteries',
        'Connectivity Technology', 'Wireless Type', 'Compatible Devices',
        'Special Feature', 'Special Features', 'Pattern',
        'Size', 'Item Dimensions LxWxH', 'Capacity', 'Style',
    }
    filtered = {}
    for k, v in specs.items():
        for ukey in useful_keys:
            if ukey.lower() == k.lower() or ukey.lower() in k.lower():
                filtered[k] = v
                break
    return filtered


def _extract_category(soup):
    """Extract product category from Amazon breadcrumbs."""
    breadcrumbs = soup.select('#wayfinding-breadcrumbs_feature_div li a')
    if breadcrumbs:
        cats = [a.get_text(strip=True) for a in breadcrumbs]
        return ' > '.join(cats) if cats else ''

    # Try alternative
    cat_el = soup.select_one('#nav-subnav .nav-a-content')
    if cat_el:
        return cat_el.get_text(strip=True)

    return ''


def _scrape_single_domain(asin, domain, session=None):
    """Single-domain scrape attempt. Returns dict on success, None on failure.
    Used internally by scrape_amazon_product for both explicit-domain and
    auto-cascade calls. Kept private so callers always go through the public
    function, which handles the cascade/override logic consistently."""
    if session is None:
        session = _create_session()

    # Amazon respects a /-/en/ path prefix on non-English locales — it forces
    # the product page to render in English even on .de/.fr/.it/etc. Without
    # this, scraping .de gives us German titles/bullets that are useless for
    # an English eBay UK listing.
    if domain in ('amazon.co.uk', 'amazon.com'):
        url = f"https://www.{domain}/dp/{asin}"
    else:
        url = f"https://www.{domain}/-/en/dp/{asin}"

    try:
        # Random delay to look less bot-like
        time.sleep(random.uniform(1.0, 2.5))

        # Visit domain homepage first so we have its cookies
        try:
            session.get(f"https://www.{domain}/ref=cs_503_link", timeout=8, allow_redirects=True)
        except:
            pass

        resp = session.get(url, timeout=15, allow_redirects=True)

        if resp.status_code == 503 or 'captcha' in resp.text.lower() or 'robot check' in resp.text.lower():
            logger.warning(f"[SCRAPE] CAPTCHA on {domain} for {asin}")
            return None

        if resp.status_code != 200:
            logger.info(f"[SCRAPE] HTTP {resp.status_code} from {domain} for {asin} (not listed here)")
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')

        title = _extract_title(soup)
        if not title:
            logger.info(f"[SCRAPE] No title on {domain} for {asin} — ASIN not listed on this locale")
            return None

        # Extract gallery first so we can use it as a fallback for the main
        # image. The legacy fallback (get_amazon_image_url(asin)) was broken —
        # it used the ASIN as the image path, but Amazon image IDs and ASINs
        # are different namespaces, so that URL is basically always a 404.
        all_images = _extract_all_images(soup, page_text=resp.text, asin=asin)
        price = _extract_price(soup)
        bullet_points = _extract_bullet_points(soup)
        category = _extract_category(soup)
        item_specifics = _extract_item_specifics(soup)

        # Main image: try the DOM extractor first, then fall back to the
        # first gallery image (which is often extracted from embedded JSON
        # even on "Currently unavailable" pages).
        image_url = _extract_image(soup)

        # Defensively reject anything that is actually the broken
        # constructed-from-ASIN URL. _extract_all_images no longer emits
        # that fallback, but raw page_text regex matches could still
        # surface one and we don't want to write it into the DB again.
        def _is_broken_asin_url(u):
            if not u:
                return False
            basename = u.rsplit('/', 1)[-1]
            return basename.startswith(f"{asin}.")

        if _is_broken_asin_url(image_url):
            image_url = None

        all_images = [u for u in all_images if not _is_broken_asin_url(u)]

        # If DOM scrape failed but the gallery has real images, promote
        # the first gallery image. Only non-broken URLs remain at this
        # point, so no further filtering needed.
        if not image_url and all_images:
            image_url = all_images[0]

        # Ensure main image is first in all_images (no duplicate)
        if image_url and image_url not in all_images:
            all_images.insert(0, image_url)
        all_images = all_images[:8]

        if not image_url:
            logger.info(
                f"[SCRAPE] {asin} on {domain}: page parsed but no usable image "
                f"(title='{(title or '')[:40]}...') — manual upload needed"
            )

        logger.info(
            f"[SCRAPE] {asin} from {domain}: {title[:50]}... "
            f"({len(all_images)} images, {len(item_specifics)} specs)"
        )
        return {
            'title': title,
            'image_url': image_url,
            'price': price,
            'bullet_points': bullet_points,
            'category': category,
            'all_images': all_images,
            'item_specifics': item_specifics,
            'source_domain': domain,
        }

    except requests.RequestException as e:
        logger.warning(f"Request failed for {domain}/{asin}: {e}")
        return None


def scrape_amazon_product(asin, domain=None, strict=False):
    """
    Scrape product data from Amazon for a given ASIN.

    `domain` is a SOFT HINT, not a hard lock:
    - If `domain` is given: try that locale first, and if the ASIN isn't
      there, cascade through the remaining locales. This mirrors the uncle's
      Akces Hub behaviour — pallets often contain ASINs sourced across
      multiple regions, so hard-locking to one locale silently drops the
      products that live elsewhere (the exact bug that produced the "no
      image for half the products" reports).
    - If `domain` is None: cascade through AMAZON_DOMAINS in priority order.
    - If `strict=True` AND `domain` is given: legacy strict mode, only that
      locale is tried. Reserved for cases where the caller knows the ASIN
      is truly locale-specific (different product per region).

    The caller can tell which locale actually served the page via the
    `source_domain` key in the return dict, and cache that on the pallet
    so subsequent scrapes put the correct locale first in the cascade.

    Non-English locales are fetched via the /-/en/ URL prefix, so titles/
    specs come back in English regardless of the domain.

    Returns dict: {title, image_url, price, bullet_points, category,
    all_images, item_specifics, source_domain} or None on failure.
    """
    if not asin or not ASIN_RE.match(asin):
        logger.warning(f"Invalid ASIN: {asin}")
        return None

    valid_domains = {d for d, _ in AMAZON_DOMAINS}
    session = _create_session()

    # Build the try-order: hint first, then the rest of AMAZON_DOMAINS.
    # Unknown hint is silently ignored (falls through to full cascade).
    if domain and domain in valid_domains:
        if strict:
            return _scrape_single_domain(asin, domain, session=session)
        try_order = [domain] + [d for d, _ in AMAZON_DOMAINS if d != domain]
    else:
        try_order = [d for d, _ in AMAZON_DOMAINS]

    for d in try_order:
        result = _scrape_single_domain(asin, d, session=session)
        if result:
            if domain and d == domain:
                logger.info(f"[SCRAPE] {asin} found on hinted locale {d}")
            elif domain:
                logger.info(f"[SCRAPE] {asin} not on hint {domain}, fell back to {d}")
            else:
                logger.info(f"[SCRAPE] Auto-detected {asin} on {d}")

            # Title upgrade: if the title came back in Polish/German/etc,
            # try amazon.co.uk or amazon.com for just the title so the
            # uncle's listings are English. We keep images/specs/price from
            # the original scrape because the ASIN might map to a different
            # variant per locale (see the Busybee Christmas Tree case).
            if _looks_non_english(result.get('title', '')) and d not in ('amazon.co.uk', 'amazon.com'):
                for eng_domain in ('amazon.co.uk', 'amazon.com'):
                    eng_result = _scrape_single_domain(asin, eng_domain, session=session)
                    if eng_result and eng_result.get('title') and not _looks_non_english(eng_result['title']):
                        logger.info(
                            f"[SCRAPE] Upgraded {asin} title from {d} ({result['title'][:40]}...) "
                            f"to {eng_domain} ({eng_result['title'][:40]}...)"
                        )
                        result['title'] = eng_result['title']
                        # Bullets are also often in the local language — upgrade
                        # those too if the English locale had them.
                        if eng_result.get('bullet_points'):
                            result['bullet_points'] = eng_result['bullet_points']
                        break
            return result

    logger.warning(f"[SCRAPE] {asin} not found on any Amazon locale")
    return None


# ---------------------------------------------------------------------------
# Amazon Image URL helper
# ---------------------------------------------------------------------------

def get_amazon_image_url(asin):
    """
    Return the standard Amazon product image URL for an ASIN.
    This uses Amazon's predictable image URL scheme (no scraping needed).
    """
    if not asin:
        return ''
    # Amazon image URL - works for most ASINs
    return f"https://m.media-amazon.com/images/I/{asin}._AC_SL1500_.jpg"


def get_amazon_image_urls(asin):
    """Return multiple possible image URLs for an ASIN (fallback chain)."""
    if not asin:
        return []
    return [
        f"https://m.media-amazon.com/images/I/{asin}._AC_SL1500_.jpg",
        f"https://images-na.ssl-images-amazon.com/images/I/{asin}._AC_SL1500_.jpg",
        f"https://m.media-amazon.com/images/I/{asin}._AC_UL600_.jpg",
        f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_SX500_.jpg",
    ]


# ---------------------------------------------------------------------------
# Specification Parser
# ---------------------------------------------------------------------------

def parse_specification(text):
    """
    Parse pasted joblot specification text and extract product info.

    Processes line by line, extracting:
    - ASIN (B0XXXXXXXXX pattern)
    - EAN (13-digit number)
    - Quantity (patterns like x2, 2x, qty: 3)
    - Product name (remaining text after removing identifiers)

    Returns list of dicts: [{name, asin, ean, quantity}, ...]
    """
    if not text or not text.strip():
        return []

    products = []
    lines = text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Skip obvious header/separator lines
        if line.startswith('---') or line.startswith('==='):
            continue
        if line.lower().startswith(('total', 'summary', 'subtotal', '#', 'item')):
            continue

        # Extract ASIN
        asin_match = ASIN_RE.search(line)
        asin = asin_match.group(1) if asin_match else ''

        # Extract EAN
        ean_match = EAN_RE.search(line)
        ean = ean_match.group(1) if ean_match else ''

        # Extract quantity
        quantity = 1
        qty_match = QTY_RE.search(line)
        if qty_match:
            qty_val = qty_match.group(1) or qty_match.group(2) or qty_match.group(3)
            if qty_val:
                try:
                    quantity = int(qty_val)
                    if quantity < 1:
                        quantity = 1
                    elif quantity > 9999:
                        quantity = 1
                except ValueError:
                    quantity = 1

        # Build product name: clean up the line
        name = line

        # Remove ASIN from name
        if asin:
            name = name.replace(asin, '')

        # Remove EAN from name
        if ean:
            name = name.replace(ean, '')

        # Remove quantity patterns from name
        name = QTY_RE.sub('', name)

        # Remove common delimiters, leading numbers, bullets
        name = re.sub(r'^[\d\.\)\-\*\u2022\|,;]+\s*', '', name)
        # Remove trailing/leading whitespace and extra spaces
        name = re.sub(r'\s+', ' ', name).strip()
        # Remove leading/trailing dashes and pipes
        name = name.strip('-|, ')

        if not name or len(name) < 2:
            if asin:
                name = f"Product {asin}"
            elif ean:
                name = f"Product EAN {ean}"
            else:
                continue

        products.append({
            'name': name,
            'asin': asin,
            'ean': ean,
            'quantity': quantity,
        })

    return products
