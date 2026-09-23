"""SQLite plus full text search.

Tags are faceted rather than one flat list, because a flat list stops being
useful pretty fast. Four axes: what you'd do with it, what it's about, where
it is in your flow, and where it applies.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from . import config

ACTIONS = ["apply", "learn", "install", "read", "watch", "visit", "build", "reference"]
STATUSES = ["inbox", "triage", "active", "done", "dropped"]

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS items (
  id            TEXT PRIMARY KEY,      -- stable hash of the normalised URL
  url           TEXT NOT NULL,
  source        TEXT,                  -- gdoc | manual | chat_export
  kind          TEXT,                  -- tutorial | job | tool | repo | ...
  action        TEXT,                  -- see ACTIONS
  status        TEXT DEFAULT 'inbox',
  urgent        INTEGER DEFAULT 0,
  deadline      TEXT,
  title         TEXT,
  hook          TEXT,
  summary       TEXT,
  owner         TEXT,
  posted        TEXT,
  user_note     TEXT,                  -- what YOU wrote next to the link
  user_do       TEXT,                  -- the "do:" instruction
  slide_count   INTEGER DEFAULT 0,
  focus_slide   INTEGER,
  pdf_path      TEXT,
  media_dir     TEXT,
  gate_json     TEXT,                  -- comment/DM gate detection
  note_json     TEXT,                  -- full extraction
  enrich_json   TEXT,                  -- full enrichment
  cost_usd      REAL DEFAULT 0,
  created_at    REAL,
  updated_at    REAL,
  processed_at  REAL,
  error         TEXT
);

CREATE TABLE IF NOT EXISTS tags (
  item_id  TEXT NOT NULL,
  facet    TEXT NOT NULL,              -- action | topic | place | user | status
  value    TEXT NOT NULL,
  PRIMARY KEY (item_id, facet, value)
);
CREATE INDEX IF NOT EXISTS idx_tags_value ON tags(facet, value);

CREATE TABLE IF NOT EXISTS links (
  item_id     TEXT NOT NULL,
  url         TEXT NOT NULL,
  label       TEXT,
  where_found TEXT,
  alive       INTEGER,
  status_code INTEGER,
  page_title  TEXT,
  PRIMARY KEY (item_id, url)
);

CREATE TABLE IF NOT EXISTS seen (
  hash        TEXT PRIMARY KEY,        -- hash of a raw inbox line
  first_seen  REAL,
  item_id     TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id    TEXT,
  stage      TEXT,
  ok         INTEGER,
  detail     TEXT,
  seconds    REAL,
  cost_usd   REAL,
  at         REAL
);

CREATE TABLE IF NOT EXISTS actions_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id   TEXT,
  command   TEXT,
  exit_code INTEGER,
  output    TEXT,
  at        REAL
);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  id UNINDEXED, title, hook, summary, body, tokenize='porter'
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def item_id(url: str) -> str:
    norm = url.strip().lower()
    for junk in ("?igsh=", "&igsh=", "?utm_", "&utm_", "?stkn=", "&stkn="):
        i = norm.find(junk)
        if i > 0:
            norm = norm[:i]
    norm = norm.rstrip("/")
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def line_hash(line: str) -> str:
    return hashlib.sha1(" ".join(line.split()).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def upsert_item(conn: sqlite3.Connection, rec: dict) -> str:
    iid = rec.get("id") or item_id(rec["url"])
    rec["id"] = iid
    now = time.time()
    cur = conn.execute("SELECT id, created_at FROM items WHERE id=?", (iid,))
    row = cur.fetchone()
    rec.setdefault("created_at", row["created_at"] if row else now)
    rec["updated_at"] = now

    cols = [c for c in rec if c in {
        "id", "url", "source", "kind", "action", "status", "urgent", "deadline",
        "title", "hook", "summary", "owner", "posted", "user_note", "user_do",
        "slide_count", "focus_slide", "pdf_path", "media_dir", "gate_json",
        "note_json", "enrich_json", "cost_usd", "created_at", "updated_at",
        "processed_at", "error"}]
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO items ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        [rec[c] for c in cols],
    )
    conn.commit()
    return iid


def set_tags(conn: sqlite3.Connection, iid: str, facet: str, values: Iterable[str]) -> None:
    conn.execute("DELETE FROM tags WHERE item_id=? AND facet=?", (iid, facet))
    seen = set()
    for v in values or []:
        v = str(v).strip().lower()
        if not v or v in seen:
            continue
        seen.add(v)
        conn.execute("INSERT OR IGNORE INTO tags (item_id, facet, value) VALUES (?,?,?)",
                     (iid, facet, v))
    conn.commit()


def set_links(conn: sqlite3.Connection, iid: str, links: list[dict]) -> None:
    conn.execute("DELETE FROM links WHERE item_id=?", (iid,))
    for l in links or []:
        url = (l.get("url") or "").strip()
        if not url:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO links (item_id,url,label,where_found,alive,status_code,page_title)"
            " VALUES (?,?,?,?,?,?,?)",
            (iid, url, l.get("label", ""), l.get("where", ""),
             1 if l.get("alive") else 0, l.get("status", 0), l.get("page_title", "")),
        )
    conn.commit()


def index_fts(conn: sqlite3.Connection, iid: str, title: str, hook: str,
              summary: str, body: str) -> None:
    conn.execute("DELETE FROM items_fts WHERE id=?", (iid,))
    conn.execute("INSERT INTO items_fts (id,title,hook,summary,body) VALUES (?,?,?,?,?)",
                 (iid, title or "", hook or "", summary or "", (body or "")[:200000]))
    conn.commit()


def log_run(conn, iid, stage, ok, detail="", seconds=0.0, cost=0.0) -> None:
    conn.execute("INSERT INTO runs (item_id,stage,ok,detail,seconds,cost_usd,at)"
                 " VALUES (?,?,?,?,?,?,?)",
                 (iid, stage, 1 if ok else 0, str(detail)[:2000], seconds, cost, time.time()))
    conn.commit()


def mark_seen(conn, h: str, iid: str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO seen (hash, first_seen, item_id) VALUES (?,?,?)",
                 (h, time.time(), iid))
    conn.commit()


def already_seen(conn, h: str) -> bool:
    return conn.execute("SELECT 1 FROM seen WHERE hash=?", (h,)).fetchone() is not None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def get_item(conn, iid: str) -> dict | None:
    row = conn.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("note_json", "enrich_json", "gate_json"):
        if d.get(k):
            try:
                d[k.replace("_json", "")] = json.loads(d[k])
            except Exception:
                d[k.replace("_json", "")] = None
    d["tags"] = facets_for(conn, iid)
    d["links"] = [dict(r) for r in conn.execute(
        "SELECT url,label,where_found,alive,status_code,page_title FROM links WHERE item_id=?", (iid,))]
    return d


def facets_for(conn, iid: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in conn.execute("SELECT facet, value FROM tags WHERE item_id=?", (iid,)):
        out.setdefault(r["facet"], []).append(r["value"])
    return out


def list_items(conn, *, status: str = "", action: str = "", topic: str = "",
               place: str = "", q: str = "", urgent: bool = False,
               limit: int = 200) -> list[dict]:
    sql = ["SELECT i.* FROM items i"]
    args: list[Any] = []
    joins, where = [], []

    if q.strip():
        joins.append("JOIN items_fts f ON f.id = i.id")
        where.append("items_fts MATCH ?")
        args.append(q.strip())
    for facet, val in (("action", action), ("topic", topic), ("place", place)):
        if val:
            alias = f"t_{facet}"
            joins.append(f"JOIN tags {alias} ON {alias}.item_id=i.id "
                         f"AND {alias}.facet='{facet}' AND {alias}.value=?")
            args.append(val.lower())
    if status:
        where.append("i.status=?")
        args.append(status)
    if urgent:
        where.append("i.urgent=1")

    sql += joins
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY i.urgent DESC, COALESCE(i.processed_at, i.created_at) DESC LIMIT ?")
    args.append(limit)

    rows = conn.execute(" ".join(sql), args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("note_json", None)
        d.pop("enrich_json", None)
        d["tags"] = facets_for(conn, d["id"])
        if d.get("gate_json"):
            try:
                d["gate"] = json.loads(d["gate_json"])
            except Exception:
                d["gate"] = None
        d.pop("gate_json", None)
        d["link_count"] = conn.execute(
            "SELECT COUNT(*) c FROM links WHERE item_id=?", (d["id"],)).fetchone()["c"]
        d["dead_links"] = conn.execute(
            "SELECT COUNT(*) c FROM links WHERE item_id=? AND alive=0", (d["id"],)).fetchone()["c"]
        out.append(d)
    return out


def counts(conn) -> dict:
    out: dict[str, Any] = {}
    out["total"] = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
    out["by_status"] = {r["status"] or "inbox": r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM items GROUP BY status")}
    out["by_action"] = {r["value"]: r["c"] for r in conn.execute(
        "SELECT value, COUNT(*) c FROM tags WHERE facet='action' GROUP BY value ORDER BY c DESC")}
    out["by_topic"] = {r["value"]: r["c"] for r in conn.execute(
        "SELECT value, COUNT(*) c FROM tags WHERE facet='topic' GROUP BY value ORDER BY c DESC LIMIT 40")}
    out["by_place"] = {r["value"]: r["c"] for r in conn.execute(
        "SELECT value, COUNT(*) c FROM tags WHERE facet='place' GROUP BY value ORDER BY c DESC LIMIT 20")}
    out["gated"] = conn.execute(
        "SELECT COUNT(*) c FROM items WHERE gate_json LIKE '%\"gated\": true%'").fetchone()["c"]
    out["dead_links"] = conn.execute("SELECT COUNT(*) c FROM links WHERE alive=0").fetchone()["c"]
    out["spend"] = round(conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) s FROM items").fetchone()["s"] or 0, 4)
    return out
