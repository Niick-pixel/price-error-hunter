import random
import threading
import time
import traceback

from . import amazon, config, creators, filters, scoring, scraper, sources, store


class Poller:
    """Background refresh loop with jitter, conditional GETs and backoff."""

    def __init__(self):
        self.scraper = scraper.Scraper()
        self.checker = amazon.AmazonChecker()
        self.api = creators.Client()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.status = {
            "last_run": None,
            "last_ok": None,
            "next_run": None,
            "last_error": None,
            "cycles": 0,
            "unchanged_streak": 0,
            "new_since_open": 0,
            "top_new": None,
            "running": False,
            "amazon_error": None,
            "source_errors": None,
            # Increments when discount-threshold deals arrive; the UI chimes on
            # a change and shows nothing.
            "sound_ping": 0,
            "sound_ping_count": 0,
            # Keyword watch: its own counter and payload so the UI can play a
            # distinct sound and name the word that matched.
            "watch_ping": 0,
            "watch_hit": None,
        }
        self._backoff = 0.0

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh_now(self):
        """Ask for an out-of-band cycle. Honours min_interval regardless."""
        cfg = config.load()
        last = self.status["last_run"]
        if last and time.time() - last < cfg["min_interval"]:
            return {
                "ok": False,
                "wait": round(cfg["min_interval"] - (time.time() - last), 1),
            }
        self._wake.set()
        return {"ok": True}

    def _loop(self):
        while not self._stop.is_set():
            delay = self._run_cycle()
            self.status["next_run"] = time.time() + delay
            self._wake.wait(delay)
            self._wake.clear()

    def _run_cycle(self):
        cfg = config.load()
        self.status["running"] = True
        self.status["last_run"] = time.time()
        try:
            cold_start = store.deal_count() == 0
            fresh = []

            if cfg.get("source_hiddenclearances", True):
                items, changed = self.scraper.fetch_listing()
                if changed:
                    fresh += store.upsert_listing(items, source="hiddenclearances")

            # Extra feeds run every cycle, independently of the main listing's
            # 304 handling, and one failing feed must not stop the others.
            fresh += self._fetch_sources(cfg)

            # Quiet means quiet everywhere, not just on the main listing.
            if fresh:
                self.status["unchanged_streak"] = 0
            else:
                self.status["unchanged_streak"] += 1

            # Score from feed data first so the limited detail budget is spent on
            # the most promising deals, then score again once details are in.
            self._rescore()
            self._fetch_details(cfg)
            self._backfill_targets(cfg)
            self._rescore()
            self._check_amazon(cfg)
            self._note_new(fresh, alert=not cold_start)

            self.status["last_ok"] = time.time()
            self.status["last_error"] = None
            self._backoff = 0.0
        except scraper.Blocked as exc:
            self._backoff = max(exc.retry_after or 0, min(max(self._backoff * 2, 60), 900))
            self.status["last_error"] = "Rate limited - backing off"
        except Exception as exc:  # network hiccups shouldn't kill the loop
            self._backoff = min(max(self._backoff * 2, 30), 600)
            self.status["last_error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            self.status["running"] = False
            self.status["cycles"] += 1

        if self._backoff:
            return self._backoff

        base = max(cfg["poll_interval"], cfg["min_interval"])
        # Ease off only when every source has been quiet for a while. This used
        # to key off Hidden Clearances' 304s alone and stretch to 3x, so with
        # six feeds a chosen 2 minutes drifted out past 6 - the other five could
        # be delivering deals while the streak kept climbing. The streak now
        # resets on any new deal from any source, and the ceiling is 2x.
        if self.status["unchanged_streak"] >= 5:
            base *= min(1 + 0.2 * (self.status["unchanged_streak"] - 4), 2.0)
        return base * (1 + random.uniform(-cfg["jitter"], cfg["jitter"]))

    def _fetch_details(self, cfg):
        for deal_id in store.pending_detail_ids(cfg["max_details_per_cycle"]):
            if self._stop.is_set():
                return
            deal = store.get(deal_id)
            if not deal:
                continue
            try:
                detail = self.scraper.fetch_detail(deal["url"])
                store.save_detail(
                    deal_id, detail["description"], detail["out_url"], detail["image"]
                )
                self._resolve_target(deal_id, detail["out_url"])
            except scraper.Blocked:
                raise
            except Exception:
                store.save_detail(deal_id, "", "", "", ok=False)

    def _fetch_sources(self, cfg):
        """Poll the extra RSS feeds, isolating failures per source."""
        fresh = []
        errors = []
        for source in sources.ALL:
            if not cfg.get(f"source_{source.name}", True):
                continue
            try:
                items = source.fetch(self.scraper.session, cfg["request_timeout"])
                fresh += store.upsert_listing(items, source=source.name)
            except Exception as exc:
                errors.append(f"{source.label}: {type(exc).__name__}")
        self.status["source_errors"] = errors or None
        return fresh

    def _backfill_targets(self, cfg):
        """Resolve destinations for deals whose details predate this feature."""
        for deal_id in store.pending_target_ids(cfg["max_details_per_cycle"]):
            if self._stop.is_set():
                return
            deal = store.get(deal_id)
            if deal:
                self._resolve_target(deal_id, deal["out_url"])

    def _resolve_target(self, deal_id, out_url):
        """Follow the affiliate hops once so links go straight to the retailer."""
        if not out_url:
            return
        try:
            final = self.scraper.resolve_target(out_url)
        except Exception:
            return
        if final:
            store.save_target(deal_id, final, scraper.extract_asin(final))

    def _check_amazon(self, cfg):
        """Prefer the official API; fall back to best-effort scraping."""
        if creators.configured():
            self._check_amazon_api()
        elif cfg["amazon_live_check"]:
            self._check_amazon_scrape(cfg)

    def _check_amazon_api(self):
        deal_ids = store.amazon_candidates(10)
        if not deal_ids:
            return
        deals = [d for d in (store.get(i) for i in deal_ids) if d]
        try:
            results = self.api.get_items([d["asin"] for d in deals])
        except creators.CreatorsError as exc:
            self.status["amazon_error"] = f"{exc.code}: {exc.message}"
            return
        except Exception as exc:
            self.status["amazon_error"] = f"{type(exc).__name__}: {exc}"
            return

        self.status["amazon_error"] = None
        for deal in deals:
            result = results.get(deal["asin"])
            if not result:
                continue
            tag, note = amazon.verdict(deal["price"], result, deal["list_price"])
            store.save_amazon(deal["id"], result, tag, note)
            # The API's detail page URL carries the user's own associate tag,
            # which Amazon requires us to use once we're pulling their data.
            if result.get("detail_url"):
                store.save_target(deal["id"], result["detail_url"], deal["asin"])

    def _check_amazon_scrape(self, cfg):
        for deal_id in store.amazon_candidates(2):
            if self._stop.is_set():
                return
            deal = store.get(deal_id)
            if not deal:
                continue
            result = self.checker.check(deal["asin"], cfg)
            if result.get("status") == "capped":
                return
            tag, note = amazon.verdict(deal["price"], result, deal["list_price"])
            store.save_amazon(deal_id, result, tag, note)

    def _rescore(self):
        for deal in store.list_deals(limit=500):
            value, tier, reasons = scoring.score(deal)
            if value != deal.get("score") or tier != deal.get("tier"):
                store.save_score(deal["id"], value, tier, reasons)

    def _note_new(self, fresh_ids, alert=True):
        # First populate: everything is "new", so an alert would be noise.
        if not fresh_ids or not alert:
            return
        cfg = config.load()
        cats, words = filters.settings_filter(cfg)
        # Hidden product types must not ring either. Filtering here covers both
        # the banner and the sound-only pass below, since both read this list.
        fresh = [
            d for d in (store.get(i) for i in fresh_ids)
            if d and not filters.suppressed(d, cats, words)
        ]
        if not fresh:
            return
        best = None
        for deal in fresh:
            if best is None or deal["score"] > best["score"]:
                best = deal
        # Count what the user can actually see, not what was ingested.
        self.status["new_since_open"] += len(fresh)

        # A word the user typed themselves outranks any score threshold, so the
        # watch pass runs first and claims the deal it matched.
        watch_id = self._note_watch(cfg, fresh)

        banner_id = best["id"] if best and best["score"] >= cfg["alert_score"] else None
        self._note_sound_only(cfg, fresh, banner_id, watch_id)

        if best and best["score"] >= cfg["alert_score"]:
            self.status["top_new"] = {
                "title": best["title"],
                "score": best["score"],
                "id": best["id"],
                # Without a URL the alert has nothing to open, which is why
                # clicking it used to do nothing.
                "url": best.get("direct_url") or best.get("out_url") or best.get("url"),
                "retailer": best.get("retailer") or "",
                "price": best.get("price"),
                "discount_pct": best.get("discount_pct"),
                "image": best.get("image") or "",
            }

    def _note_watch(self, cfg, fresh):
        """Raise a watch alert for a new deal matching a watched keyword.

        Returns the matched deal's id so the discount chime does not also fire
        for it - one find should make one sound.
        """
        keywords = filters.parse_keywords(cfg.get("watch_keywords"))
        if not keywords:
            return None
        for deal in fresh:
            word = filters.watch_match(deal, keywords)
            if not word:
                continue
            self.status["watch_ping"] += 1
            self.status["watch_hit"] = {
                "id": deal["id"],
                "keyword": word,
                "title": deal["title"],
                "score": deal.get("score"),
                "url": (deal.get("direct_url") or deal.get("out_url")
                        or deal.get("url")),
                "retailer": deal.get("retailer") or "",
                "price": deal.get("price"),
                "discount_pct": deal.get("discount_pct"),
                "image": deal.get("image") or "",
            }
            return deal["id"]
        return None

    def _note_sound_only(self, cfg, fresh, banner_id, watch_id=None):
        """Chime, with no banner, for new deals above the discount threshold.

        Deliberately carries no title or link: the UI only needs to know that
        the counter moved so it can play the sound once per batch. The deal that
        already raised the visual alert is skipped so it cannot chime twice.
        """
        threshold = cfg.get("sound_discount") or 0
        if not threshold:
            return
        hits = [
            d for d in fresh
            if d["id"] not in (banner_id, watch_id)
            and (d.get("discount_pct") or 0) >= threshold
        ]
        if hits:
            self.status["sound_ping"] += 1
            self.status["sound_ping_count"] = len(hits)
