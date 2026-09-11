import json
import os
import threading

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")
WEB_DIR = os.path.join(APP_DIR, "web")
CONFIG_PATH = os.path.join(DATA_DIR, "settings.json")
DB_PATH = os.path.join(DATA_DIR, "deals.db")

LISTING_URL = "https://www.hiddenclearances.com/deals/online"
BASE_URL = "https://www.hiddenclearances.com"

DEFAULTS = {
    # Seconds between listing polls. Jitter is applied on top of this.
    "poll_interval": 180,
    # Fraction of poll_interval used as random jitter, so requests never land
    # on a predictable cadence.
    "jitter": 0.2,
    # Never send a listing request faster than this, even on manual refresh.
    "min_interval": 45,
    # Detail pages are fetched only for newly discovered deals.
    "detail_delay": 2.0,
    "max_details_per_cycle": 8,
    "request_timeout": 20,
    # Alerting
    "alert_score": 75,
    "sound_alerts": True,
    # Sound-only threshold: chime for any new deal at or above this discount,
    # without showing a notification. 0 disables it.
    "sound_discount": 0,
    "screen_glow": True,
    # Appearance, adjustable from the Settings tab.
    "bg_theme": "charcoal",
    "card_glow": True,
    "card_glow_discount": 50,
    "source_hiddenclearances": True,
    # Live Amazon lookups. Off by default: Amazon serves a CAPTCHA within a
    # couple of automated requests, so this is best-effort only.
    # Extra deal feeds, polled alongside the main listing.
    "source_camelcamelcamel": True,
    "source_slickdeals": True,
    "source_slickdeals_popular": True,
    "source_woot": True,
    "source_walmart": True,
    "source_techbargains": True,
    # Product types to hide. Books are on by default because Kindle price drops
    # otherwise dominate the Amazon feeds.
    "excluded_categories": ["books"],
    "exclude_keywords": "",
    # Comma-separated words to watch for. A new deal matching one of these
    # raises its own alert with a distinct sound.
    "watch_keywords": "",
    # How long a deal stays listed after it was last seen in any feed. These
    # feeds are rolling windows, so absence does not mean the deal ended.
    "deal_ttl_hours": 3,
    "amazon_live_check": False,
    "amazon_min_gap": 25,
    "amazon_hourly_cap": 12,
    # UI defaults
    "amazon_only": False,
    "min_discount": 0,
    "sort": "score",
    "port": 8765,
}

_lock = threading.Lock()
_cache = None


def _ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)


def load():
    global _cache
    with _lock:
        if _cache is None:
            _ensure_dirs()
            data = dict(DEFAULTS)
            if os.path.exists(CONFIG_PATH):
                try:
                    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                        data.update(json.load(fh))
                except (OSError, ValueError):
                    pass
            _cache = data
        return dict(_cache)


def update(changes):
    global _cache
    with _lock:
        _ensure_dirs()
        current = dict(_cache or DEFAULTS)
        for key, value in changes.items():
            if key in DEFAULTS:
                current[key] = value
        _cache = current
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(current, fh, indent=2)
        os.replace(tmp, CONFIG_PATH)
        return dict(current)
