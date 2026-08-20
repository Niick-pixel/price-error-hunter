import json
import sqlite3
import threading
import time

from . import config

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
    db.commit()


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
                " source, asin, direct_url, detail_state)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item["id"], item["url"], item["title"], item["retailer"],
                    item["price"], item["list_price"], item["discount_pct"],
                    item["savings"], item["image"], item["age_text"], now, now,
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
                " prev_price=COALESCE(?, prev_price) WHERE id=?",
                (
                    item["url"], item["title"], item["retailer"], item["price"],
                    item["list_price"], item["discount_pct"], item["savings"],
                    item["image"], item["age_text"], now, prev, item["id"],
                ),
            )
    if seen_ids:
        # Scope expiry to this source, so one feed never retires another's deals.
        marks = ",".join("?" * len(seen_ids))
        db.execute(
            f"UPDATE deals SET gone=1 WHERE gone=0 AND source=? AND id NOT IN ({marks})",
            [source] + seen_ids,
        )
    db.commit()
    return fresh


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


def list_deals(amazon_only=False, min_discount=0, sort="score", limit=300):
    where = ["gone=0"]
    args = []
    if amazon_only:
        # Some deals are filed under a generic retailer but still resolve to an
        # Amazon product, so treat a known ASIN as proof it belongs here.
        where.append("(LOWER(retailer)='amazon' OR (asin IS NOT NULL AND asin<>''))")
    if min_discount:
        where.append("discount_pct >= ?")
        args.append(min_discount)
    order = {
        "score": "score DESC, first_seen DESC",
        "newest": "first_seen DESC",
        "discount": "discount_pct DESC, savings DESC",
        "savings": "savings DESC",
    }.get(sort, "score DESC, first_seen DESC")
    args.append(limit)
    rows = conn().execute(
        f"SELECT * FROM deals WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
        args,
    ).fetchall()
    return [_to_dict(r) for r in rows]


def clear_new_flags(ids):
    if not ids:
        return
    db = conn()
    db.execute(
        f"UPDATE deals SET is_new=0 WHERE id IN ({','.join('?' * len(ids))})", ids
    )
    db.commit()


def _to_dict(row):
    data = dict(row)
    try:
        data["reasons"] = json.loads(data.get("reasons") or "[]")
    except ValueError:
        data["reasons"] = []
    return data
