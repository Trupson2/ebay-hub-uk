"""
eBay Hub UK - Amazon Product Scraper & Specification Parser
Scrapes product data from Amazon UK (priority), then .com, then .de.
Parses pasted joblot specification text to extract product info.
"""

import re
import time
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
    """Extract main product image URL from Amazon page."""
    # Try the main image element
    img = soup.select_one('#landingImage')
    if img:
        # data-old-hires has the high-res version
        src = img.get('data-old-hires') or img.get('src')
        if src and 'placeholder' not in src.lower():
            return src

    # Try alternative image container
    img = soup.select_one('#imgBlkFront')
    if img:
        src = img.get('src')
        if src:
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


def scrape_amazon_product(asin):
    """
    Scrape product data from Amazon for a given ASIN.
    Tries amazon.co.uk first, then .com, then .de.

    Returns dict: {title, image_url, price, bullet_points, category}
    or None on failure.
    """
    if not asin or not ASIN_RE.match(asin):
        logger.warning(f"Invalid ASIN: {asin}")
        return None

    session = _create_session()

    for domain, currency in AMAZON_DOMAINS:
        url = f"https://www.{domain}/dp/{asin}"
        try:
            # Random delay to avoid rate limiting
            time.sleep(random.uniform(1.5, 3.5))

            # Visit domain homepage first for cookies
            try:
                session.get(f"https://www.{domain}/ref=cs_503_link", timeout=8, allow_redirects=True)
            except:
                pass

            resp = session.get(url, timeout=15, allow_redirects=True)

            if resp.status_code == 503 or 'captcha' in resp.text.lower() or 'robot check' in resp.text.lower():
                print(f"[SCRAPE] CAPTCHA on {domain} for {asin}, trying next...")
                time.sleep(2)
                continue

            if resp.status_code != 200:
                print(f"[SCRAPE] HTTP {resp.status_code} from {domain} for {asin}")
                time.sleep(1)
                continue

            soup = BeautifulSoup(resp.text, 'html.parser')

            title = _extract_title(soup)
            if not title:
                logger.warning(f"No title found on {domain} for {asin}, trying next")
                time.sleep(0.5)
                continue

            image_url = _extract_image(soup) or get_amazon_image_url(asin)
            price = _extract_price(soup)
            bullet_points = _extract_bullet_points(soup)
            category = _extract_category(soup)

            logger.info(f"Scraped {asin} from {domain}: {title[:50]}...")
            return {
                'title': title,
                'image_url': image_url,
                'price': price,
                'bullet_points': bullet_points,
                'category': category,
            }

        except requests.RequestException as e:
            logger.warning(f"Request failed for {domain}/{asin}: {e}")
            time.sleep(0.5)
            continue

    logger.error(f"All Amazon domains failed for ASIN: {asin}")
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
    # Try multiple Amazon image URL formats
    return f"https://m.media-amazon.com/images/I/{asin}._AC_SL1500_.jpg"


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
