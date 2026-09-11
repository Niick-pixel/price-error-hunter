"""Additional deal feeds, so discounts are found independently of one site.

Both feeds here are public RSS and cost one request per poll. Amazon itself is
never scraped: CamelCamelCamel already tracks Amazon prices and publishes the
biggest drops, ASIN included, which is exactly the signal a price-error hunt
needs.
"""

import html
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from . import scraper

CAMEL_FEED = "https://camelcamelcamel.com/top_drops/feed"
SLICKDEALS_FEED = (
    "https://slickdeals.net/newsearch.php"
    "?mode=frontpage&searcharea=deals&searchin=first&rss=1"
)
SLICKDEALS_POPULAR = (
    "https://slickdeals.net/newsearch.php"
    "?mode=popdeals&searcharea=deals&searchin=first&rss=1"
)
SLICKDEALS_WOOT = (
    "https://slickdeals.net/newsearch.php"
    "?q=woot&searcharea=deals&searchin=first&rss=1"
)
SLICKDEALS_WALMART = (
    "https://slickdeals.net/newsearch.php"
    "?q=walmart&searcharea=deals&searchin=first&rss=1"
)
TECHBARGAINS_FEED = "https://www.techbargains.com/rss.xml"

# TechBargains puts the price at the end of the title: "... Jumper Cables $33.33"
TRAILING_PRICE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)\s*$")
LEADING_PRICE_TAG = re.compile(r"^\$\s?[\d,]+(?:\.\d{2})?\*?\s*\|\s*")
# "Amazon - Smlau XB2 Wireless Adapter ..." - en dash or hyphen, short prefix
# only, so a product name containing a dash is not mistaken for a store.
TITLE_RETAILER = re.compile(r"^([A-Za-z][A-Za-z0-9'&. ]{2,18}?)\s*[-–—]\s+")

# "Product Name - down 12.45% ($4.12) to $28.98 from $33.10"
CAMEL_TITLE = re.compile(
    r"^(?P<name>.+?)\s+-\s+down\s+(?P<pct>[\d.]+)%\s+"
    r"\(\$(?P<save>[\d,.]+)\)\s+to\s+\$(?P<now>[\d,.]+)\s+from\s+\$(?P<was>[\d,.]+)\s*$",
    re.I,
)
CAMEL_ASIN = re.compile(r"/product/([A-Za-z0-9]{10})")

CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"
IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
# Slickdeals spells out the product URL, which gives us the ASIN for free.
AMAZON_DP = re.compile(r"amazon\.com/(?:dp|gp/product)/([A-Z0-9]{10})", re.I)


def amazon_image(asin):
    """Amazon's legacy image-by-ASIN endpoint.

    Only worth using as a last resort: it serves a 43-byte placeholder for most
    modern ASINs and really only has artwork for books and other media. The UI
    drops anything that comes back tiny and shows a placeholder tile instead.
    """
    return f"https://m.media-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"

RETAILER_TAG = re.compile(r"\[([a-z0-9.-]+\.[a-z]{2,})\]", re.I)
PRICE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
PCT_OFF = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%\s*off", re.I)
WAS_PRICE = re.compile(
    r"(?:was|reg(?:ularly)?\.?|orig(?:inally)?\.?|list(?:\s+price)?|down\s+from)"
    r"\s*\$\s?([\d,]+(?:\.\d{2})?)",
    re.I,
)


def _num(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _age_text(pub_date):
    """RSS gives an absolute date; the UI wants '12 min ago'."""
    if not pub_date:
        return ""
    try:
        stamp = parsedate_to_datetime(pub_date).timestamp()
    except (TypeError, ValueError):
        return ""
    minutes = max(0, int((time.time() - stamp) / 60))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 1440:
        return f"{minutes // 60} hr ago"
    return f"{minutes // 1440} days ago"


def _items(xml):
    """Parse an RSS document.

    These are XML, so they are parsed with ElementTree rather than an HTML
    parser - the HTML path mangles CDATA descriptions and drops <link> text.
    """
    try:
        root = ElementTree.fromstring(xml.encode("utf-8"))
    except ElementTree.ParseError:
        return

    for node in root.iter("item"):
        def text(tag):
            found = node.find(tag)
            return (found.text or "").strip() if found is not None else ""

        raw_description = text("description")
        # Thumbnails live in the namespaced <content:encoded> block, not in
        # <description>, so both are searched for an <img>.
        content = text(CONTENT_ENCODED)
        image = ""
        for blob in (content, raw_description):
            found = IMG_SRC.search(blob or "")
            if found:
                image = found.group(1)
                break

        description = raw_description
        if "<" in description:
            # Descriptions carry escaped HTML; flatten it to plain text.
            description = " ".join(
                BeautifulSoup(description, "html.parser").get_text(" ").split()
            )
        yield {
            # Some feeds double-escape entities, leaving &#039; in the text.
            "title": html.unescape(text("title")),
            "link": text("link"),
            "description": description,
            "image": image,
            "pub_date": text("pubDate"),
        }


class CamelTopDrops:
    """Biggest recent Amazon price drops, straight from CamelCamelCamel."""

    name = "camelcamelcamel"
    label = "Camel top drops"

    def fetch(self, session, timeout):
        resp = session.get(CAMEL_FEED, timeout=timeout)
        resp.raise_for_status()
        out = []
        for entry in _items(resp.text):
            match = CAMEL_TITLE.match(entry["title"])
            asin_match = CAMEL_ASIN.search(entry["link"])
            if not match or not asin_match:
                continue
            price = _num(match.group("now"))
            was = _num(match.group("was"))
            if price is None or was is None:
                continue
            asin = asin_match.group(1)
            out.append({
                "id": scraper.deal_id(entry["link"]),
                "url": entry["link"],
                "title": match.group("name").strip(),
                "retailer": "Amazon",
                "price": price,
                "list_price": was,
                "discount_pct": _num(match.group("pct")) or 0.0,
                "savings": _num(match.group("save")) or round(was - price, 2),
                "image": entry["image"] or amazon_image(asin),
                "age_text": _age_text(entry["pub_date"]),
                "asin": asin,
                "direct_url": f"https://www.amazon.com/dp/{asin}",
                # ASIN and prices are already known, so no detail page is needed.
                "detail_state": 1,
            })
        return out


class Slickdeals:
    """Community-vetted front page deals across many retailers."""

    name = "slickdeals"
    label = "Slickdeals"
    feed = SLICKDEALS_FEED

    def fetch(self, session, timeout):
        resp = session.get(self.feed, timeout=timeout)
        resp.raise_for_status()
        out = []
        for entry in _items(resp.text):
            title, desc = entry["title"], entry["description"]
            if not title or not entry["link"]:
                continue

            price = _num(PRICE.search(title).group(1)) if PRICE.search(title) else None
            if price is None and PRICE.search(desc):
                price = _num(PRICE.search(desc).group(1))
            if price is None:
                continue

            blob = f"{title} {desc}"
            list_price = None
            was = WAS_PRICE.search(blob)
            if was:
                list_price = _num(was.group(1))

            discount = None
            pct = PCT_OFF.search(blob)
            if pct:
                discount = _num(pct.group(1))

            # Slickdeals often quotes "on sale for $49.99 - 50% off"; the higher
            # of the two prices in the description is the pre-discount figure.
            if list_price is None and discount:
                candidates = [_num(m) for m in PRICE.findall(desc)]
                highest = max([c for c in candidates if c] or [0])
                if highest > price:
                    list_price = highest
            if list_price and price and discount is None:
                discount = round((1 - price / list_price) * 100, 1)

            retailer = "Unknown"
            tag = RETAILER_TAG.search(desc)
            if tag:
                retailer = tag.group(1).split(".")[0].replace("-", " ").title()
            else:
                # The popular feed often omits the [store.com] tag and instead
                # names the retailer in the title as "Amazon - product name".
                lead = TITLE_RETAILER.match(title)
                if lead:
                    retailer = lead.group(1).strip().title()

            # Posts usually spell out the product URL, so Amazon items can join
            # the Amazon tab with a chart and a direct link like any other.
            asin = ""
            found = AMAZON_DP.search(blob)
            if found:
                asin = found.group(1).upper()
                retailer = "Amazon"

            out.append({
                "id": scraper.deal_id(entry["link"]),
                "url": entry["link"],
                # The popular feed prefixes titles with "$79* | "; drop it.
                "title": LEADING_PRICE_TAG.sub("", title).strip(),
                "retailer": retailer,
                "price": price,
                "list_price": list_price,
                "discount_pct": discount or 0.0,
                "savings": round(list_price - price, 2) if list_price else 0.0,
                "image": entry["image"] or (amazon_image(asin) if asin else ""),
                # Kept so promo codes can be detected; Slickdeals puts
                # "w/ code XXXX" in the description, not the title.
                "description": desc,
                "age_text": _age_text(entry["pub_date"]),
                "asin": asin,
                "direct_url": f"https://www.amazon.com/dp/{asin}" if asin else "",
                "detail_state": 1,
            })
        return out


class SlickdealsPopular(Slickdeals):
    """The popular list runs deeper than the front page and overlaps only partly."""

    name = "slickdeals_popular"
    label = "Slickdeals popular"
    feed = SLICKDEALS_POPULAR


class SlickdealsWoot(Slickdeals):
    """Woot deals via Slickdeals' search feed.

    Woot retired its own RSS - every documented endpoint now 404s - so this is
    the remaining way to watch it without scraping. The search returns some
    neighbouring sites, so anything that does not resolve to woot.com is
    dropped rather than mislabelled.
    """

    name = "woot"
    label = "Woot"
    feed = SLICKDEALS_WOOT
    retailer = "Woot"
    term = "woot"

    def fetch(self, session, timeout):
        out = []
        for item in Slickdeals.fetch(self, session, timeout):
            blob = (item["url"] + " " + item["title"] + " " +
                    item["retailer"]).lower()
            if self.term not in blob:
                continue
            item["retailer"] = self.retailer
            out.append(item)
        return out


class SlickdealsWalmart(SlickdealsWoot):
    """Walmart deals via the same search-feed trick used for Woot."""

    name = "walmart"
    label = "Walmart"
    feed = SLICKDEALS_WALMART
    retailer = "Walmart"
    term = "walmart"


class TechBargains:
    """Amazon-heavy feed whose links are already product URLs, so ASINs are free."""

    name = "techbargains"
    label = "TechBargains"
    MAX_ITEMS = 60

    def fetch(self, session, timeout):
        resp = session.get(TECHBARGAINS_FEED, timeout=timeout)
        resp.raise_for_status()
        out = []
        for entry in _items(resp.text):
            title, link = entry["title"], entry["link"]
            if not title or not link:
                continue
            price_match = TRAILING_PRICE.search(title)
            if not price_match:
                continue
            price = _num(price_match.group(1))
            if price is None:
                continue

            asin = ""
            found = AMAZON_DP.search(link)
            if found:
                asin = found.group(1).upper()

            clean = TRAILING_PRICE.sub("", title).strip(" -–—")
            out.append({
                "id": scraper.deal_id(link),
                "url": link,
                "title": clean or title,
                "retailer": "Amazon" if asin else _host_label(link),
                "price": price,
                "list_price": None,
                "discount_pct": 0.0,
                "savings": 0.0,
                # The feed carries a real thumbnail on its own CDN; prefer it,
                # because Amazon's by-ASIN path only has art for books.
                "image": entry["image"] or (amazon_image(asin) if asin else ""),
                # Kept so promo codes can be detected later.
                "description": entry["description"],
                "age_text": _age_text(entry["pub_date"]),
                "asin": asin,
                "direct_url": f"https://www.amazon.com/dp/{asin}" if asin else link,
                "detail_state": 1,
            })
            if len(out) >= self.MAX_ITEMS:
                break
        return out


def _host_label(url):
    host = urlparse(url).netloc.lower().replace("www.", "")
    return host.split(".")[0].replace("-", " ").title() if host else "Unknown"


ALL = (CamelTopDrops(), Slickdeals(), SlickdealsPopular(), SlickdealsWoot(),
       SlickdealsWalmart(), TechBargains())
