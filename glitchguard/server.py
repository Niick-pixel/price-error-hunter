import json
import mimetypes
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import csv
import traceback
import io

from . import (__version__, amazon, config, creators, filters, notify, store,
               updates)

TOKEN = secrets.token_urlsafe(24)


class Handler(BaseHTTPRequestHandler):
    server_version = "GlitchGuard"
    poller = None
    # Set by the desktop shell. None when running in a plain browser, which is
    # also how the page knows whether to offer the desktop-only settings.
    on_settings = None
    desktop = None

    def log_message(self, *args):
        pass

    # --- helpers -----------------------------------------------------------
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _token_ok(self, query):
        supplied = self.headers.get("X-PH-Token") or (query.get("t") or [""])[0]
        return secrets.compare_digest(supplied, TOKEN)

    def _serve_file(self, relpath):
        safe = os.path.normpath(relpath).lstrip("\\/")
        full = os.path.join(config.WEB_DIR, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(config.WEB_DIR)):
            self.send_error(403)
            return
        if not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            data = fh.read()
        if full.endswith("index.html"):
            data = data.replace(b"__TOKEN__", TOKEN.encode())
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # --- routes ------------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            self.send_error(403)
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._serve_file("index.html")
            return
        if path.startswith("/static/"):
            self._serve_file(path[len("/static/"):])
            return

        if path.startswith("/api/"):
            if not self._token_ok(query):
                self._json({"error": "bad token"}, 403)
                return
            if path == "/api/deals":
                self._api_deals(query)
                return
            if path == "/api/status":
                self._json(self._status())
                return
            if path == "/api/version":
                self._json(updates.status())
                return
            if path == "/api/export.csv":
                self._export_csv(query)
                return
        self.send_error(404)

    def do_POST(self):
        if not self._host_ok():
            self.send_error(403)
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._token_ok(query):
            self._json({"error": "bad token"}, 403)
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}

        if parsed.path == "/api/refresh":
            self._json(self.poller.refresh_now())
            return
        if parsed.path == "/api/settings":
            cfg = config.update(body)
            if self.on_settings:
                # e.g. registering or removing the login item. A failure there
                # must not lose the save that already happened.
                try:
                    self.on_settings(cfg)
                except Exception:
                    traceback.print_exc()
            self._json(cfg)
            return
        if parsed.path == "/api/toast/test":
            self._json(self.desktop.test_toast() if self.desktop
                       else {"ok": False, "note": "Only in the desktop app"})
            return
        if parsed.path == "/api/show":
            # A second launch asks the running copy to come forward instead of
            # starting another poller against the same feeds.
            if self.desktop:
                self.desktop.show()
            self._json({"ok": bool(self.desktop)})
            return
        if parsed.path == "/api/alerts/clear":
            store.clear_alerts()
            self._json({"ok": True})
            return
        if parsed.path == "/api/notify/test":
            self._json(notify.send_test(config.load()))
            return
        if parsed.path == "/api/hide":
            store.hide_deal(body.get("id"))
            self._json({"ok": True})
            return
        if parsed.path == "/api/amazon/check":
            self._json(self._amazon_check(body.get("id")))
            return
        if parsed.path == "/api/seen":
            store.clear_new_flags(body.get("ids") or [])
            self.poller.status["new_since_open"] = 0
            self.poller.status["top_new"] = None
            self._json({"ok": True})
            return
        self.send_error(404)

    def _api_deals(self, query):
        cfg = config.load()
        section = (query.get("section", ["feed"])[0] or "feed").lower()
        if section not in store.SECTIONS:
            section = "feed"
        try:
            min_discount = float(query.get("min", ["0"])[0] or 0)
        except ValueError:
            min_discount = 0
        sort = query.get("sort", [cfg["sort"]])[0]
        keywords = [w for w in (cfg.get("exclude_keywords") or "").split(",") if w.strip()]
        # One query serves the listing and every tab count, so a tab can never
        # advertise a number the list does not actually contain.
        everything = store.list_deals(
            section="feed", min_discount=min_discount, sort=sort,
            exclude_categories=cfg.get("excluded_categories") or (),
            exclude_keywords=keywords,
            max_age_hours=cfg.get("deal_ttl_hours"),
        )
        counts = {
            name: sum(1 for d in everything if store.in_section(d, name))
            for name in store.SECTIONS
        }
        deals = [d for d in everything if store.in_section(d, section)]
        self._json({
            "deals": deals,
            "counts": counts,
            "status": self._status(),
            "settings": cfg,
            "categories": filters.category_labels(),
            # Measured, not assumed: the settings UI prints each source's real
            # median delay so "alert from this one" is an informed choice.
            "source_latency": store.source_latency(),
        })

    def _export_csv(self, query):
        section = query.get("section", ["feed"])[0]
        if section not in store.SECTIONS:
            section = "feed"
        text, _ = export_rows(section)
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="glitchguard-{section}.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _amazon_check(self, deal_id):
        deal = store.get(deal_id) if deal_id else None
        if not deal:
            return {"ok": False, "note": "Unknown deal"}
        if not deal.get("asin"):
            return {"ok": False, "note": "No ASIN resolved for this deal yet"}
        cfg = config.load()
        if creators.configured():
            try:
                results = self.poller.api.get_items([deal["asin"]])
                result = results.get(deal["asin"]) or {
                    "status": "missing", "note": "Not returned by Amazon"
                }
            except creators.CreatorsError as exc:
                return {"ok": False, "verdict": "blocked",
                        "note": f"{exc.code}: {exc.message}"}
        else:
            result = self.poller.checker.check(deal["asin"], cfg)

        tag, note = amazon.verdict(deal["price"], result, deal["list_price"])
        store.save_amazon(deal_id, result, tag, note)
        if result.get("detail_url"):
            store.save_target(deal_id, result["detail_url"], deal["asin"])
        return {
            "ok": result.get("status") == "ok",
            "verdict": tag,
            "note": note,
            "price": result.get("price"),
            "source": result.get("source", "scrape"),
            "budget": self.poller.checker.budget(cfg),
        }

    def _status(self):
        status = dict(self.poller.status)
        now = time.time()
        status["seconds_to_next"] = (
            max(0, round(status["next_run"] - now)) if status.get("next_run") else None
        )
        cfg = config.load()
        status["settings"] = cfg
        status["desktop"] = self.desktop.info() if self.desktop else None
        status["amazon_budget"] = self.poller.checker.budget(cfg)
        # status() deliberately reports only whether keys exist, never the keys.
        status["paapi"] = creators.status()
        return status


EXPORT_COLUMNS = (
    ("title", "Title"), ("retailer", "Retailer"), ("price", "Price"),
    ("list_price", "List price"), ("discount_pct", "Discount %"),
    ("savings", "Saving"), ("score", "Score"), ("tier", "Tier"),
    ("promo_code", "Promo code"), ("source", "Source"), ("asin", "ASIN"),
    ("age_text", "Posted"), ("alert_reason", "Alert reason"),
    ("alert_keyword", "Alert keyword"), ("link", "Link"),
)


def export_rows(section):
    """The same rows the tab shows, as CSV text, so an export never disagrees
    with what was on screen. Returns (text, row_count)."""
    if section not in store.SECTIONS:
        section = "feed"
    cfg = config.load()
    keywords = [w for w in (cfg.get("exclude_keywords") or "").split(",") if w.strip()]
    deals = store.list_deals(
        section=section, sort=cfg.get("sort", "score"), limit=5000,
        exclude_categories=cfg.get("excluded_categories") or (),
        exclude_keywords=keywords, max_age_hours=cfg.get("deal_ttl_hours"),
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for d in deals:
        d["link"] = d.get("direct_url") or d.get("out_url") or d.get("url")
        writer.writerow([_csv_cell(d.get(k)) for k, _ in EXPORT_COLUMNS])
    # A byte-order mark so Excel opens it as UTF-8 instead of mangling every
    # trademark sign and curly quote in the product titles.
    return "\ufeff" + buf.getvalue(), len(deals)


def _csv_cell(value):
    """Plain text for a spreadsheet, defusing formula injection.

    Product titles come from public feeds, and a cell that starts with = + - @
    is executed by Excel as a formula, so those get a leading apostrophe.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def serve(poller, port):
    Handler.poller = poller
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return httpd
