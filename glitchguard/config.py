import json
import os
import sys
import threading

# Packaged, the executable's folder is the app folder, so data/ sits beside
# GlitchGuard.exe and the whole thing stays portable: zip the folder, move it,
# and the settings and deal history go with it. The read-only web assets are
# unpacked by PyInstaller into its bundle directory instead.
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BUNDLE_DIR = APP_DIR
DATA_DIR = os.path.join(APP_DIR, "data")
WEB_DIR = os.path.join(BUNDLE_DIR, "web")
ASSETS_DIR = os.path.join(BUNDLE_DIR, "assets")
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
    "bg_theme": "espresso",
    "card_glow": True,
    "card_glow_discount": 50,
    # Glow appearance. "rainbow" cycles the four brand-adjacent hues; "solid"
    # uses glow_color for all four, which stills the rotation and reads as one
    # steady light behind the card.
    "glow_style": "rainbow",
    "glow_color": "#e9a23c",
    # 0-100. Drives alpha, offset and blur together - turning one up without
    # the others just makes a harder edge, not a brighter light.
    "glow_strength": 70,
    # Screen-edge glow intensity, 0-100. Separate from card strength because
    # the two are read at different distances: an edge effect filling the whole
    # window is overbearing long before a halo round a card is.
    "screen_glow_intensity": 45,
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
    # Which sources may raise an alert. A source can be worth listing without
    # being worth interrupting for: the popularity-ranked feeds surface deals
    # hours after they go up, so a fresh-sounding alert from one is a fiction.
    # Defaults to every source, so behaviour is unchanged until this is edited.
    # Pinned products ignore this entirely - those were asked for by name.
    "alert_sources": [
        "hiddenclearances", "camelcamelcamel", "slickdeals",
        "slickdeals_popular", "woot", "walmart", "techbargains",
    ],
    # Product types to hide. Books are on by default because Kindle price drops
    # otherwise dominate the Amazon feeds.
    "excluded_categories": ["books"],
    "exclude_keywords": "",
    # Comma-separated words to watch for. A new deal matching one of these
    # raises its own alert with a distinct sound.
    "watch_keywords": "",
    # Pinned ASINs or product URLs, newline separated. These bypass the score
    # and age gates: the user asked for them by name, so they always alert.
    "watchlist": "",
    # Outbound alert destinations. Empty means off - nothing is sent unless a
    # destination is configured, and only alert-worthy finds are ever sent.
    "discord_webhook": "",
    "telegram_token": "",
    "telegram_chat_id": "",
    # Desktop build. Low power stops every continuous animation - the glow
    # drift, the status ring and the screen-edge overlay - leaving static
    # halos, which cost nothing once painted. Effects also pause on their own
    # whenever the window is not focused, whatever this says.
    "low_power": False,
    # Launch into the tray at login. Only acted on by the packaged app: from
    # source there is no stable executable path to register.
    "autostart": True,
    # Windows toast notifications while the window is hidden or minimised.
    "native_toasts": True,
    # One anonymous request to GitHub per launch to see if a release is newer.
    "check_updates": True,
    # Maximum age of a listed deal, measured from when it was posted - the same
    # figure shown on the card, so the two can never disagree.
    "deal_ttl_hours": 12,
    # Alerts are about catching something early. A deal can be new to us and
    # hours old already - the popular feed ranks by popularity, so items enter
    # it around ten hours after posting - so alerting is gated on how long ago
    # the deal was posted, not on when we happened to find it. 0 disables.
    "alert_max_age_minutes": 60,
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
