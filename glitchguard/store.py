import json
import sqlite3
import threading
import time

from . import config, filters, scoring

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id            TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    title         TEXT,
    retailer      TEXT,
    price         REAL,
    list_price    REAL,
    prev_price    REAL,
    discount_pct  REAL,
    savings       REAL,
    image         TEXT,
    age_text      TEXT,
    description   TEXT,
    out_url       TEXT,
    score         REAL DEFAULT 0,
    tier          TEXT,
    reasons       TEXT,
    first_seen    REAL,
    last_seen     REAL,
    detail_state  INTEGER DEFAULT 0,
    is_new        INTEGER DEFAULT 1,
    gone          INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deals_score ON deals(score DESC);
CREATE INDEX IF NOT EXISTS idx_deals_seen ON deals(first_seen DESC);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Columns added after the first release; applied to existing databases on open.
MIGRATIONS = (
    ("source", "TEXT DEFAULT 'hiddenclearances'"),
    ("posted_at", "REAL"),
    ("category", "TEXT"),
    ("hidden", "INTEGER DEFAULT 0"),
    ("promo_code", "TEXT"),
    ("direct_url", "TEXT"),
    ("asin", "TEXT"),
    ("amz_price", "REAL"),
    ("amz_list", "REAL"),
    ("amz_status", "TEXT"),
    ("amz_note", "TEXT"),
    ("amz_verdict", "TEXT"),
    ("amz_checked", "REAL"),
)


def _migrate(db):
    have = {r["name"] for r in db.execute("PRAGMA table_info(deals)")}
    for name, coltype in MIGRATIONS:
        if name not in have:
            db.execute(f"ALTER TABLE deals ADD COLUMN {name} {coltype}")
    # Backfill rows that predate posted_at. age_text was written at last_seen,
    # so measuring back from there recovers a real posting time; rows whose age
    # will not parse fall back to when we first saw them.
    # posted_at = first_seen also catches rows written by an earlier, cruder
    # backfill. Only a positive parsed age is applied, so this converges after
    # one pass instead of drifting forward on every start.
    pending = db.execute(
        "SELECT id, age_text, first_seen, last_seen, posted_at FROM deals"
        " WHERE posted_at IS NULL OR posted_at = first_seen"
    ).fetchall()
    for row in pending:
        minutes = scoring.age_minutes(row["age_text"])
        if minutes:
            posted = (row["last_seen"] or row["first_seen"]) - minutes * 60
        elif row["posted_at"] is None:
            posted = row["first_seen"]
        else:
            continue  # already correct; leave it alone
        db.execute("UPDATE deals SET posted_at=? WHERE id=?", (posted, row["id"]))

    # Classify rows stored before categories existed.
    for row in db.execute(
        "SELECT id, title, asin, price, list_price FROM deals WHERE category IS NULL"
    ).fetchall():
        db.execute("UPDATE deals SET category=? WHERE id=?",
                   (filters.classify(dict(row)), row["id"]))
    db.commit()


def _posted_at(age_text, now):
    """Turn '12 min ago' into an absolute timestamp.

    Sorting on first_seen is unreliable because a cold start inserts every deal
    in one cycle, leaving them all tied. Every feed reports an age, so derive a
    real posting time from it instead.
    """
    minutes = scoring.age_minutes(age_text)
    return now - minutes * 60 if minutes is not None else now


def conn():
    db = getattr(_local, "db", None)
    if db is None:
        config.load()
        db = sqlite3.connect(config.DB_PATH, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        _migrate(db)
        _local.db = db
    return db


def get_meta(key, default=None):
    row = conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key, value):
    db = conn()
    db.execute(
        "INSERT INTO meta(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    db.commit()


def deal_count():
    return conn().execute("SELECT COUNT(*) AS n FROM deals").fetchone()["n"]


def upsert_listing(items, source="hiddenclearances"):
    """Insert/refresh one source's rows. Returns the ids newly discovered."""
    db = conn()
    now = time.time()
    fresh = []
    seen_ids = []
    for item in items:
        seen_ids.append(item["id"])
        row = db.execute(
            "SELECT id, price FROM deals WHERE id=?", (item["id"],)
        ).fetchone()
        if row is None:
            fresh.append(item["id"])
            db.execute(
                "INSERT INTO deals (id, url, title, retailer, price, list_price,"
                " discount_pct, savings, image, age_text, first_seen, last_seen,"
                " posted_at, category, description, promo_code,"
                " source, asin, direct_url, detail_state)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item["id"], item["url"], item["title"], item["retailer"],
                    item["price"], item["list_price"], item["discount_pct"],
                    item["savings"], item["image"], item["age_text"], now, now,
                    _posted_at(item.get("age_text"), now),
                    filters.classify(item),
                    # Feed descriptions are where promo codes live, so both the
                    # text and the extracted code are stored at ingest.
                    item.get("description", ""),
                    filters.find_promo_code(item.get("title"),
                                            item.get("description")),
                    source, item.get("asin", ""), item.get("direct_url", ""),
                    # Feed sources already carry everything; skip the detail fetch.
                    item.get("detail_state", 0),
                ),
            )
        else:
            # Keep the previous price only when it actually moved, so the UI can
            # surface "dropped since we first saw it".
            prev = row["price"] if row["price"] != item["price"] else None
            db.execute(
                "UPDATE deals SET url=?, title=?, retailer=?, price=?, list_price=?,"
                " discount_pct=?, savings=?, image=?, age_text=?, last_seen=?, gone=0,"
                " posted_at=COALESCE(posted_at, ?), category=?,"
                " description=COALESCE(NULLIF(?, ''), description),"
                " promo_code=COALESCE(NULLIF(?, ''), promo_code),"
                " prev_price=COALESCE(?, prev_price) WHERE id=?",
                (
                    item["url"], item["title"], item["retailer"], item["price"],
                    item["list_price"], item["discount_pct"], item["savings"],
                    item["image"], item["age_text"], now,
                    # Set once and keep: age_text drifts every poll, so
                    # recomputing would make the posting time wander.
                    _posted_at(item.get("age_text"), now),
                    # Recomputed every refresh so rows classified under older
                    # rules pick up improvements instead of staying stale.
                    filters.classify(item),
                    # Never blank an existing description: hiddenclearances
                    # fills it in later from its detail page.
                    item.get("description", "") or "",
                    filters.find_promo_code(item.get("title"),
                                            item.get("description")) or "",
                    prev, item["id"],
                ),
            )
    # Deliberately no expiry here. Most of these feeds are rolling windows -
    # Camel publishes the current top 20 drops, TechBargains 60 of hundreds -
    # so an item dropping out means it was pushed down the list, not that the
    # deal ended. Retiring on absence killed 99% of rows, many within the same
    # cycle they were found, which is why alerts pointed at deals that were
    # already gone from the list. Age decides now; see expire_stale.
    db.commit()
    return fresh


GRACE_SECONDS = 3600


def expire_stale(max_age_seconds):
    """Retire deals older than max_age_seconds. Returns the count.

    Age is measured from posted_at, the same clock the age label shows, so the
    setting means exactly what it says - with a limit of 3 hours nothing can
    still be listed reading "16 hr ago".

    The grace window is the safeguard: a deal found when it was already near
    the limit stays for an hour regardless, so an alert can never point at
    something that vanishes moments later. That was the original bug and it
    must not come back through the age rule.
    """
    db = conn()
    now = time.time()
    cur = db.execute(
        "UPDATE deals SET gone=1 WHERE gone=0"
        " AND COALESCE(posted_at, first_seen) < ?"
        " AND first_seen < ?",
        (now - max_age_seconds, now - GRACE_SECONDS),
    )
    db.commit()
    return cur.rowcount


def revive_recent(max_age_seconds):
    """Bring back deals retired by the old absence rule that are still fresh.

    One-off repair on startup: without it every deal expired under the previous
    logic would stay hidden for good. Scoped to the same age rule used for
    expiry, so nothing older than the limit is resurrected.
    """
    db = conn()
    cutoff = time.time() - max_age_seconds
    cur = db.execute(
        "UPDATE deals SET gone=0 WHERE gone=1 AND last_seen >= ?"
        " AND COALESCE(posted_at, first_seen) >= ?",
        (cutoff, cutoff),
    )
    db.commit()
    return cur.rowcount


def pending_detail_ids(limit):
    rows = conn().execute(
        "SELECT id FROM deals WHERE detail_state=0 AND gone=0"
        " ORDER BY score DESC, first_seen DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r["id"] for r in rows]


def save_detail(deal_id, description, out_url, image, ok=True):
    db = conn()
    if ok:
        db.execute(
            "UPDATE deals SET description=?, out_url=?,"
            " image=COALESCE(NULLIF(?,''), image), detail_state=1 WHERE id=?",
            (description, out_url, image or "", deal_id),
        )
    else:
        db.execute("UPDATE deals SET detail_state=2 WHERE id=?", (deal_id,))
    db.commit()


def save_target(deal_id, direct_url, asin):
    db = conn()
    db.execute(
        "UPDATE deals SET direct_url=?, asin=? WHERE id=?",
        (direct_url, asin, deal_id),
    )
    db.commit()


def save_amazon(deal_id, result, verdict_tag, note):
    db = conn()
    db.execute(
        "UPDATE deals SET amz_price=?, amz_list=?, amz_status=?, amz_note=?,"
        " amz_verdict=?, amz_checked=? WHERE id=?",
        (
            result.get("price"), result.get("list_price"), result.get("status"),
            note, verdict_tag, time.time(), deal_id,
        ),
    )
    db.commit()


def pending_target_ids(limit):
    """Deals with an outbound link whose final destination is not resolved yet."""
    rows = conn().execute(
        "SELECT id FROM deals WHERE gone=0 AND out_url IS NOT NULL AND out_url<>''"
        " AND (direct_url IS NULL OR direct_url='')"
        " ORDER BY score DESC, first_seen DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r["id"] for r in rows]


def amazon_candidates(limit):
    """Amazon deals with an ASIN that have never had a live check."""
    rows = conn().execute(
        "SELECT id FROM deals WHERE gone=0 AND asin IS NOT NULL AND asin<>''"
        " AND amz_checked IS NULL ORDER BY score DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r["id"] for r in rows]


def save_score(deal_id, score, tier, reasons):
    db = conn()
    db.execute(
        "UPDATE deals SET score=?, tier=?, reasons=? WHERE id=?",
        (score, tier, json.dumps(reasons), deal_id),
    )
    db.commit()


def get(deal_id):
    row = conn().execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    return _to_dict(row) if row else None


SECTIONS = ("feed", "amazon", "woot", "walmart")


def in_section(deal, section):
    """Which tab a deal belongs to.

    Kept in Python rather than SQL so the tab counts and the listing can never
    disagree about what belongs where.
    """
    if section == "amazon":
        # Some deals are filed under a generic retailer but still resolve to an
        # Amazon product, so a known ASIN is proof enough.
        return ((deal.get("retailer") or "").lower() == "amazon"
                or bool(deal.get("asin")))
    if section in ("woot", "walmart"):
        blob = " ".join([
            deal.get("retailer") or "", deal.get("direct_url") or "",
            deal.get("url") or "", deal.get("source") or "",
        ]).lower()
        return section in blob
    return True


def list_deals(section="feed", min_discount=0, sort="score", limit=300,
               exclude_categories=(), exclude_keywords=(), max_age_hours=None):
    # Category and keyword exclusion is applied in Python below rather than
    # here, so there is exactly one definition of "hidden" shared with alerts.
    where = ["gone=0", "hidden=0"]
    args = []
    if max_age_hours:
        # Applied here as well as in the expiry job so the setting bites the
        # moment it is changed, instead of waiting for the next poll, and so
        # nothing inside the expiry grace window can still be listed older
        # than the limit the user chose.
        where.append("COALESCE(posted_at, first_seen) >= ?")
        args.append(time.time() - float(max_age_hours) * 3600)
    if min_discount:
        where.append("discount_pct >= ?")
        args.append(min_discount)
    order = {
        "score": "score DESC, posted_at DESC",
        "newest": "posted_at DESC, first_seen DESC",
        "oldest": "posted_at ASC, first_seen ASC",
        "discount": "discount_pct DESC, savings DESC",
        "discount_asc": "discount_pct ASC, savings ASC",
        "savings": "savings DESC",
    }.get(sort, "score DESC, posted_at DESC")
    args.append(limit)
    rows = conn().execute(
        f"SELECT * FROM deals WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
        args,
    ).fetchall()
    # Visibility runs through the same helper the alert path uses, so the two
    # can never disagree about whether a deal is hidden.
    return [
        d for d in (_to_dict(r) for r in rows)
        if in_section(d, section)
        and not filters.suppressed(d, exclude_categories, exclude_keywords)
    ]


def hide_deal(deal_id):
    db = conn()
    db.execute("UPDATE deals SET hidden=1 WHERE id=?", (deal_id,))
    db.commit()


def clear_new_flags(ids):
    if not ids:
        return
    db = conn()
    db.execute(
        f"UPDATE deals SET is_new=0 WHERE id IN ({','.join('?' * len(ids))})", ids
    )
    db.commit()


def age_label(posted_at):
    """Human age from the one timestamp everything else agrees on."""
    if not posted_at:
        return ""
    minutes = max(0, int((time.time() - posted_at) / 60))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 1440:
        return f"{minutes // 60} hr ago"
    return f"{minutes // 1440} days ago"


def _to_dict(row):
    data = dict(row)
    try:
        data["reasons"] = json.loads(data.get("reasons") or "[]")
    except ValueError:
        data["reasons"] = []
    # The stored age_text is whatever the feed last claimed, and TechBargains
    # and Slickdeals' popular list republish items with fresh dates - 44 of 60
    # TechBargains rows were labelled "4 hr ago" while genuinely nine days old.
    # posted_at is fixed when a deal is first seen, so the label, the sort and
    # the age cutoff all read from it and cannot disagree.
    data["age_text"] = age_label(data.get("posted_at")) or data.get("age_text") or ""
    # Detected on read as well as at ingest, so rows stored before promo codes
    # existed - and hiddenclearances rows whose description only arrives with
    # the later detail fetch - pick one up without needing a re-import.
    if not data.get("promo_code"):
        data["promo_code"] = filters.find_promo_code(
            data.get("title"), data.get("description")
        )
    return data
