import json
import mimetypes
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import amazon, config, creators, filters, store

TOKEN = secrets.token_urlsafe(24)


class Handler(BaseHTTPRequestHandler):
    server_version = "PriceErrorHunter"
    poller = None

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
            self._json(config.update(body))
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
        amazon_only = (query.get("amazon", [""])[0] or "").lower() in ("1", "true")
        try:
            min_discount = float(query.get("min", ["0"])[0] or 0)
        except ValueError:
            min_discount = 0
        sort = query.get("sort", [cfg["sort"]])[0]
        keywords = [w for w in (cfg.get("exclude_keywords") or "").split(",") if w.strip()]
        deals = store.list_deals(
            amazon_only=amazon_only, min_discount=min_discount, sort=sort,
            exclude_categories=cfg.get("excluded_categories") or (),
            exclude_keywords=keywords,
        )
        self._json({
            "deals": deals,
            "status": self._status(),
            "settings": cfg,
            "categories": filters.category_labels(),
        })

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
        status["amazon_budget"] = self.poller.checker.budget(cfg)
        # status() deliberately reports only whether keys exist, never the keys.
        status["paapi"] = creators.status()
        return status


def serve(poller, port):
    Handler.poller = poller
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return httpd
