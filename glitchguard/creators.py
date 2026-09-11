"""Amazon Creators API client.

Replaces the Product Advertising API, which Amazon deprecated on 30 Apr 2026 and
switched off on 15 May 2026. Auth moved from AWS SigV4 to OAuth 2.0 client
credentials, the host is now a single global endpoint, and every field name is
lowerCamelCase.

Credentials never live in the app settings (which are sent to the browser). They
come from environment variables or data/amazon_api.json - see README.
"""

import json
import os
import threading
import time

import requests

from . import config

API_BASE = "https://creatorsapi.amazon/catalog/v1"
SCOPE = "creatorsapi::default"

# Token endpoint is per region; the catalog host is global.
TOKEN_ENDPOINTS = {
    "NA": "https://api.amazon.com/auth/o2/token",
    "EU": "https://api.amazon.co.uk/auth/o2/token",
    "FE": "https://api.amazon.co.jp/auth/o2/token",
}

MARKETPLACE_REGION = {
    "www.amazon.com": "NA", "www.amazon.ca": "NA", "www.amazon.com.mx": "NA",
    "www.amazon.com.br": "NA",
    "www.amazon.co.uk": "EU", "www.amazon.de": "EU", "www.amazon.fr": "EU",
    "www.amazon.it": "EU", "www.amazon.es": "EU", "www.amazon.nl": "EU",
    "www.amazon.se": "EU", "www.amazon.pl": "EU", "www.amazon.com.tr": "EU",
    "www.amazon.ae": "EU", "www.amazon.sa": "EU", "www.amazon.in": "EU",
    "www.amazon.co.jp": "FE", "www.amazon.com.au": "FE", "www.amazon.sg": "FE",
}

RESOURCES = ["itemInfo.title", "offersV2", "images.primary.medium"]

CREDENTIALS_PATH = os.path.join(config.DATA_DIR, "amazon_api.json")

ERROR_HINTS = {
    "invalid_client": "Client ID or secret rejected - check for stray spaces",
    "invalid_scope": "Scope rejected - must be creatorsapi::default",
    "InvalidToken": "Access token rejected by Amazon",
    "UnauthorizedException": "Credentials are not authorised for the Creators API",
    "AccessDenied": "Amazon has not enabled Creators API access for this account yet",
    "ThrottlingException": "Rate limited by Amazon - the app will retry later",
    "TooManyRequests": "Rate limited by Amazon - the app will retry later",
    "InvalidParameterValue": "Amazon rejected a parameter or ASIN as invalid",
}

_lock = threading.Lock()
_creds_cache = None
_creds_mtime = None


def load_credentials():
    """Environment variables win; otherwise data/amazon_api.json."""
    global _creds_cache, _creds_mtime

    env = {
        "client_id": os.environ.get("CREATORS_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("CREATORS_CLIENT_SECRET", "").strip(),
        "partner_tag": os.environ.get("CREATORS_PARTNER_TAG", "").strip(),
        "marketplace": os.environ.get("CREATORS_MARKETPLACE", "www.amazon.com").strip(),
    }
    if env["client_id"] and env["client_secret"] and env["partner_tag"]:
        return env

    with _lock:
        try:
            mtime = os.path.getmtime(CREDENTIALS_PATH)
        except OSError:
            _creds_cache, _creds_mtime = None, None
            return None
        if _creds_cache is not None and mtime == _creds_mtime:
            return dict(_creds_cache)
        try:
            with open(CREDENTIALS_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return None

        creds = {
            "client_id": str(raw.get("client_id", "")).strip(),
            "client_secret": str(raw.get("client_secret", "")).strip(),
            "partner_tag": str(raw.get("partner_tag", "")).strip(),
            "marketplace": str(raw.get("marketplace") or "www.amazon.com").strip(),
        }
        if not (creds["client_id"] and creds["client_secret"] and creds["partner_tag"]):
            return None
        # Reject the shipped placeholder so a half-finished setup reads as absent.
        if creds["client_id"].startswith("YOUR_"):
            return None
        _creds_cache, _creds_mtime = dict(creds), mtime
        return dict(creds)


def configured():
    return load_credentials() is not None


def status():
    """Safe to send to the browser - never includes secret material."""
    creds = load_credentials()
    if not creds:
        return {"configured": False, "path": CREDENTIALS_PATH}
    return {
        "configured": True,
        "marketplace": creds["marketplace"],
        "partner_tag": creds["partner_tag"],
    }


class CreatorsError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Client:
    def __init__(self):
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._token = None
        self._expires = 0.0
        self._last_call = 0.0

    def _access_token(self, creds, timeout):
        """Cached bearer token; Amazon issues these with a one hour life."""
        with self._lock:
            if self._token and time.time() < self._expires - 60:
                return self._token

            region = MARKETPLACE_REGION.get(creds["marketplace"], "NA")
            resp = self.session.post(
                TOKEN_ENDPOINTS[region],
                headers={"Content-Type": "application/json"},
                data=json.dumps({
                    "grant_type": "client_credentials",
                    "client_id": creds["client_id"],
                    "client_secret": creds["client_secret"],
                    "scope": SCOPE,
                }),
                timeout=timeout,
            )
            try:
                body = resp.json()
            except ValueError:
                raise CreatorsError("BadResponse", f"HTTP {resp.status_code} from auth")

            if resp.status_code != 200 or "access_token" not in body:
                code = body.get("error", "AuthFailed")
                raise CreatorsError(code, ERROR_HINTS.get(
                    code, body.get("error_description", code)))

            self._token = body["access_token"]
            self._expires = time.time() + float(body.get("expires_in", 3600))
            return self._token

    def get_items(self, asins, timeout=25):
        """Look up to 10 ASINs. Returns {asin: result-dict}."""
        creds = load_credentials()
        if not creds:
            raise CreatorsError("NotConfigured", "Creators API credentials are not set up")
        asins = [a for a in dict.fromkeys(asins) if a][:10]
        if not asins:
            return {}

        token = self._access_token(creds, timeout)

        with self._lock:
            gap = 1.1 - (time.time() - self._last_call)
            if gap > 0:
                time.sleep(gap)
            self._last_call = time.time()

        resp = self.session.post(
            f"{API_BASE}/getItems",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-marketplace": creds["marketplace"],
            },
            data=json.dumps({
                "itemIds": asins,
                "itemIdType": "ASIN",
                "marketplace": creds["marketplace"],
                "partnerTag": creds["partner_tag"],
                "resources": RESOURCES,
            }),
            timeout=timeout,
        )

        if resp.status_code == 401:
            # Token may have been revoked early; drop it so the next call re-auths.
            with self._lock:
                self._token, self._expires = None, 0.0

        try:
            body = resp.json()
        except ValueError:
            raise CreatorsError("BadResponse", f"HTTP {resp.status_code} from Amazon")

        if resp.status_code != 200:
            code = body.get("reason") or body.get("type") or f"HTTP{resp.status_code}"
            raise CreatorsError(
                code, ERROR_HINTS.get(code, body.get("message", code))
            )

        results = {asin: {"status": "missing", "note": "Not returned by Amazon",
                          "source": "creators"} for asin in asins}
        for item in body.get("items") or body.get("itemsResult", {}).get("items") or []:
            asin = item.get("asin") or item.get("ASIN")
            if asin:
                results[asin] = _parse_item(item)
        for err in body.get("errors") or []:
            code = err.get("reason") or err.get("code") or ""
            for asin in asins:
                if asin in json.dumps(err):
                    results[asin] = {
                        "status": "missing",
                        "note": ERROR_HINTS.get(code, err.get("message", code)),
                        "source": "creators",
                    }
        return results


def _money(node):
    """OffersV2 wraps amounts as {"money": {"amount": .., "displayAmount": ".."}}."""
    if not isinstance(node, dict):
        return None
    money = node.get("money") if isinstance(node.get("money"), dict) else node
    amount = money.get("amount")
    try:
        return float(amount) if amount is not None else None
    except (TypeError, ValueError):
        return None


def _parse_item(item):
    info = item.get("itemInfo") or {}
    title = ((info.get("title") or {}).get("displayValue")
             or (info.get("title") or {}).get("value") or "")
    detail_url = (item.get("detailPageUrl") or item.get("detailPageURL")
                  or item.get("detailPageLink") or "")

    listings = ((item.get("offersV2") or {}).get("listings")) or []
    if not listings:
        return {
            "status": "unavailable", "title": title, "detail_url": detail_url,
            "note": "No buyable offer right now", "source": "creators",
        }

    listing = next((l for l in listings if l.get("isBuyBoxWinner")), listings[0])
    price_node = listing.get("price") or {}
    price = _money(price_node)
    list_price = _money(price_node.get("savingBasis") or {})

    availability = listing.get("availability") or {}
    message = availability.get("message") or availability.get("type") or ""

    if price is None:
        return {
            "status": "unavailable", "title": title, "detail_url": detail_url,
            "availability": message, "note": "No price returned",
            "source": "creators",
        }

    out_of_stock = str(availability.get("type", "")).upper() == "OUT_OF_STOCK"
    return {
        "status": "unavailable" if out_of_stock else "ok",
        "price": price,
        "list_price": list_price,
        "title": title,
        "detail_url": detail_url,
        "availability": message,
        "source": "creators",
    }
