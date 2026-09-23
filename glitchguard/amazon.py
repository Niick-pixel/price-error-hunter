"""Optional live price check against an Amazon product page.

This is deliberately conservative. Amazon's robots.txt does not disallow
/dp/<ASIN>, but their Conditions of Use prohibit bulk data gathering and their
bot detection is aggressive, so the checker is opt-in, hard-throttled to a
handful of requests per hour, and reports a block honestly instead of retrying
into a ban. It is only used as a fallback when Creators API credentials are
absent - see creators.py and the README.
"""

import re
import threading
import time

import requests
from bs4 import BeautifulSoup

MAX_BYTES = 1_500_000

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

PRICE_SELECTORS = (
    "#corePriceDisplay_desktop_feature_div span.priceToPay span.a-offscreen",
    "#corePrice_feature_div span.a-offscreen",
    "#corePrice_desktop span.a-offscreen",
    "span.priceToPay span.a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "#priceblock_saleprice",
    "span.a-price span.a-offscreen",
)

LIST_SELECTORS = (
    "#corePriceDisplay_desktop_feature_div span.basisPrice span.a-offscreen",
    "span.basisPrice span.a-offscreen",
    "#listPrice",
    "span.a-price.a-text-price span.a-offscreen",
)

BLOCK_MARKERS = (
    "api-services-support@amazon.com",
    "to discuss automated access",
    "enter the characters you see below",
    "type the characters you see in this image",
    "/errors/validatecaptcha",
    "robot check",
)

MONEY = re.compile(r"([\d,]+\.\d{2})")


class AmazonChecker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        })
        self._lock = threading.Lock()
        self._last = 0.0
        self._recent = []

    def budget(self, cfg):
        """Remaining checks in the trailing hour, and seconds until the next slot."""
        now = time.time()
        with self._lock:
            self._recent = [t for t in self._recent if now - t < 3600]
            used = len(self._recent)
            left = max(0, cfg["amazon_hourly_cap"] - used)
            wait = max(0.0, cfg["amazon_min_gap"] - (now - self._last))
        return {"used": used, "left": left, "wait": round(wait, 1)}

    def check(self, asin, cfg):
        """Fetch one product page. Returns a dict with status and prices."""
        budget = self.budget(cfg)
        if budget["left"] <= 0:
            return {"status": "capped", "note": "Hourly check limit reached"}

        # Reserve the next slot under the lock, then wait for it outside.
        # This used to sleep while holding the lock, and budget() - called on
        # every status poll - needs the same lock, so each spaced-out check
        # froze /api/status for up to 30 seconds. Alerts reach the page
        # through that endpoint, so they froze with it.
        with self._lock:
            now = time.time()
            slot = max(now, self._last + cfg["amazon_min_gap"])
            slot = min(slot, now + 30)
            self._last = slot
            self._recent.append(slot)
        wait = slot - time.time()
        if wait > 0:
            time.sleep(wait)

        url = f"https://www.amazon.com/dp/{asin}"
        try:
            resp = self.session.get(url, timeout=cfg["request_timeout"], stream=True)
            body = resp.raw.read(MAX_BYTES, decode_content=True) or b""
            resp.close()
        except Exception as exc:
            return {"status": "error", "note": f"{type(exc).__name__}"}

        if resp.status_code in (503, 429):
            return {"status": "blocked", "note": "Amazon returned a bot check"}
        if resp.status_code == 404:
            return {"status": "missing", "note": "Product page not found"}
        if resp.status_code != 200:
            return {"status": "error", "note": f"HTTP {resp.status_code}"}

        html = body.decode(resp.encoding or "utf-8", errors="replace")
        low = html.lower()
        if any(marker in low for marker in BLOCK_MARKERS):
            return {"status": "blocked", "note": "Amazon served a CAPTCHA"}

        return parse_product(html)


def parse_product(html):
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    node = soup.select_one("#productTitle")
    if node:
        title = node.get_text(strip=True)

    price = _first_price(soup, PRICE_SELECTORS)
    list_price = _first_price(soup, LIST_SELECTORS)

    availability = ""
    node = soup.select_one("#availability")
    if node:
        availability = " ".join(node.get_text(" ", strip=True).split())

    if price is None:
        unavailable = "currently unavailable" in html.lower()
        return {
            "status": "unavailable" if unavailable else "noprice",
            "title": title,
            "availability": availability,
            "note": "Currently unavailable" if unavailable else "No price on the page",
        }

    return {
        "status": "ok",
        "price": price,
        "list_price": list_price,
        "title": title,
        "availability": availability,
    }


def _first_price(soup, selectors):
    for selector in selectors:
        for node in soup.select(selector):
            match = MONEY.search(node.get_text(strip=True))
            if match:
                return float(match.group(1).replace(",", ""))
    return None


def verdict(deal_price, amz, list_price=None):
    """Compare the feed's claimed price with what Amazon is showing now."""
    status = amz.get("status")
    if status == "ok":
        live = amz["price"]
        # Scraped figures wildly off the known price are parse failures, not
        # bargains, so they are never presented as fact. Creators API data is
        # structured and authoritative, so it skips this guard.
        reference = list_price or deal_price
        scraped = amz.get("source") != "creators"
        if scraped and reference and (live > reference * 5 or live < reference * 0.02):
            return "unreliable", (
                f"Read ${live:,.2f} off the page, which does not look credible - "
                "Amazon's markup varies, so check the page yourself"
            )
        if deal_price and live <= deal_price * 1.02:
            return "confirmed", f"Amazon is showing ${live:.2f} - the deal is live"
        if deal_price and live > deal_price * 1.02:
            gap = live - deal_price
            return "gone", f"Amazon now shows ${live:.2f} (${gap:.2f} above the listed price)"
        return "confirmed", f"Amazon is showing ${live:.2f}"
    return {
        "blocked": ("blocked", "Amazon blocked the automated check - open the page yourself"),
        "capped": ("capped", "Hourly check limit reached"),
        "unavailable": ("gone", "Amazon lists this as currently unavailable"),
        "missing": ("gone", "Product page no longer exists"),
        "noprice": ("unknown", "No price shown - may be out of stock or app-only"),
    }.get(status, ("unknown", amz.get("note") or "Check failed"))
