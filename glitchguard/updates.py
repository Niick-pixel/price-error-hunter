"""Tell the user when a newer release exists. Never downloads or installs.

One anonymous request to GitHub's public API per launch, and only while the
setting is on. Nothing about the user or their deals is sent. The result is a
link for the user to follow themselves - an app that watches for pricing
mistakes has no business replacing its own executable in the background.
"""

import json
import re
import threading
import urllib.error
import urllib.request

from . import __version__

REPO = "Niick-pixel/price-error-hunter"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 8

_lock = threading.Lock()
_result = {"current": __version__, "checked": False, "latest": None,
           "newer": False, "url": None, "error": None}


def _parse(tag):
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); anything unparseable sorts lowest."""
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def check():
    """Ask GitHub once. Safe to call from any thread; failures are recorded,
    never raised, because a missing network must not stop the app starting."""
    info = {"current": __version__, "checked": True, "latest": None,
            "newer": False, "url": None, "error": None}
    try:
        req = urllib.request.Request(LATEST, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"GlitchGuard/{__version__}",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name") or ""
        info["latest"] = tag.lstrip("vV") or None
        info["url"] = data.get("html_url")
        info["newer"] = _parse(tag) > _parse(__version__)
    except urllib.error.HTTPError as exc:
        # 404 simply means no release has been published yet.
        info["error"] = None if exc.code == 404 else f"HTTP {exc.code}"
    except Exception as exc:
        info["error"] = type(exc).__name__
    with _lock:
        _result.update(info)
    return dict(_result)


def check_async():
    threading.Thread(target=check, daemon=True).start()


def status():
    with _lock:
        return dict(_result)
