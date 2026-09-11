"""Outbound alerts to Discord and Telegram.

Both are opt-in and off unless a destination is configured. Only finds that
already cleared the in-app alert gates are ever sent, so turning these on does
not mean forwarding the whole feed to a chat channel.

Note on Discord: a webhook is outbound only. It can post into a channel but
cannot read one, so "watch a Discord server for deals" is a different feature
needing a bot token and server permission - deliberately not attempted here.

Failures are swallowed and reported through status rather than raised: a chat
service being down must never stop the poller.
"""

import json
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = 10
# One message per find is the point; this only guards against a feed burst
# turning into a flood of chat messages.
MIN_GAP_SECONDS = 3

_lock = threading.Lock()
_last_sent = 0.0


def configured(cfg):
    """Which destinations are set up, if any."""
    return {
        "discord": bool((cfg.get("discord_webhook") or "").strip()),
        "telegram": bool((cfg.get("telegram_token") or "").strip()
                         and (cfg.get("telegram_chat_id") or "").strip()),
    }


def _post(url, payload, headers=None):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status


def _throttle():
    global _last_sent
    with _lock:
        gap = MIN_GAP_SECONDS - (time.time() - _last_sent)
        if gap > 0:
            time.sleep(gap)
        _last_sent = time.time()


def _format(deal, reason):
    price = deal.get("price")
    was = deal.get("list_price")
    bits = []
    if isinstance(price, (int, float)):
        bits.append(f"${price:,.2f}")
    if isinstance(was, (int, float)) and was:
        bits.append(f"was ${was:,.2f}")
    if deal.get("discount_pct"):
        bits.append(f"{round(deal['discount_pct'])}% off")
    if deal.get("promo_code"):
        bits.append(f"code {deal['promo_code']}")
    return {
        "title": deal.get("title") or "Untitled",
        "url": (deal.get("direct_url") or deal.get("out_url")
                or deal.get("url") or ""),
        "line": " · ".join(bits),
        "retailer": deal.get("retailer") or "",
        "score": round(deal.get("score") or 0),
        "reason": reason,
        "image": deal.get("image") or "",
    }


def send(cfg, deal, reason="Possible price error"):
    """Send one find to every configured destination. Returns per-channel results."""
    dest = configured(cfg)
    if not any(dest.values()):
        return {}

    info = _format(deal, reason)
    results = {}
    _throttle()

    if dest["discord"]:
        results["discord"] = _send_discord(cfg["discord_webhook"].strip(), info)
    if dest["telegram"]:
        results["telegram"] = _send_telegram(
            cfg["telegram_token"].strip(), cfg["telegram_chat_id"].strip(), info
        )
    return results


def _send_discord(webhook, info):
    embed = {
        "title": info["title"][:250],
        "description": info["line"] or None,
        "color": 0xE9A23C,
        "footer": {"text": f"GlitchGuard · {info['reason']} · {info['score']}/100"},
    }
    if info["url"]:
        embed["url"] = info["url"]
    if info["image"]:
        embed["thumbnail"] = {"url": info["image"]}
    try:
        status = _post(webhook, {"embeds": [embed]})
        return {"ok": 200 <= status < 300, "status": status}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def _send_telegram(token, chat_id, info):
    # HTML parse mode rather than Markdown: product titles are full of
    # underscores and asterisks that Markdown would try to interpret.
    text = (
        f"<b>{_escape(info['title'])}</b>\n"
        f"{_escape(info['line'])}\n"
        f"<i>{_escape(info['reason'])} · {info['score']}/100</i>"
    )
    if info["url"]:
        text += f"\n{_escape(info['url'])}"
    try:
        status = _post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
             "disable_web_page_preview": False},
        )
        return {"ok": 200 <= status < 300, "status": status}
    except urllib.error.HTTPError as exc:
        # Telegram explains refusals in the body, which is far more useful than
        # the status code alone (a wrong chat id and a revoked token both 400).
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("description", "")
        except Exception:
            detail = ""
        return {"ok": False, "error": f"HTTP {exc.code}: {detail}"[:120]}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def _escape(text):
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def send_test(cfg):
    """Used by the Settings button so a destination can be proven before relying on it."""
    fake = {
        "title": "GlitchGuard test message",
        "price": 9.99, "list_price": 99.99, "discount_pct": 90,
        "retailer": "Test", "score": 95,
        "url": "https://github.com/Niick-pixel/price-error-hunter",
    }
    dest = configured(cfg)
    if not any(dest.values()):
        return {"ok": False, "note": "No destination configured"}
    results = send(cfg, fake, reason="Test")
    failed = {k: v for k, v in results.items() if not v.get("ok")}
    if failed:
        first = next(iter(failed.values()))
        return {"ok": False, "note": first.get("error", "Send failed"),
                "results": results}
    return {"ok": True, "note": f"Sent to {', '.join(results)}", "results": results}
