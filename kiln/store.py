"""SQLite plus full text search.

Tags are faceted rather than one flat list, because a flat list stops being
useful pretty fast. Four axes: what you'd do with it, what it's about, where
it is in your flow, and where it applies. Sections are a fifth, and the only
one I name myself: open ended, with subsections, stored as a tag whose value
is the section's path.
"""
from __future__ import annotations

import hashlib
import json
import re
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
  links_checked TEXT,                  -- when the link check actually ran
  gate_json     TEXT,                  -- comment/DM gate detection
  note_json     TEXT,                  -- full extraction
  enrich_json   TEXT,                  -- full enrichment
  attempts      INTEGER DEFAULT 0,     -- reads tried, so a failure can retry
  created_at    REAL,
  updated_at    REAL,
  processed_at  REAL,
  error         TEXT
);

CREATE TABLE IF NOT EXISTS tags (
  item_id  TEXT NOT NULL,
  facet    TEXT NOT NULL,              -- action | topic | place | user | section
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
  hash        TEXT PRIMARY KEY,        -- hash of an inbox link, or of a note with none
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

-- Sections the owner asks for by name, with subsections inside them. The
-- action facet is a closed list (eight verbs, and redo for a link that could
-- not be read); this is the open one.
CREATE TABLE IF NOT EXISTS sections (
  id          TEXT PRIMARY KEY,        -- slug path: "to-watch" or "to-watch/rag"
  name        TEXT NOT NULL,
  parent      TEXT,                    -- id of the section above, or NULL
  about       TEXT,                    -- what belongs here, used to file later items
  asked       TEXT,                    -- the instruction that created it; never published
  created_at  REAL
);

-- What earlier follow-up work learned about handling items like this one.
CREATE TABLE IF NOT EXISTS playbook (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT,
  topics      TEXT,                    -- comma separated, lowercase
  lesson      TEXT NOT NULL,
  source      TEXT,                    -- the item it was learned on
  created_at  REAL,
  used        INTEGER DEFAULT 0,
  last_used   REAL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the schema above.

    CREATE TABLE IF NOT EXISTS leaves an existing file exactly as it was,
    so neither a dropped column nor an added one happens on its own.
    Safe to run on every connect.
    """
    for table, col, decl in (("items", "attempts", "INTEGER DEFAULT 0"),
                             ("items", "claude_state", "TEXT"),
                             ("items", "claude_json", "TEXT"),
                             ("items", "claude_attempts", "INTEGER DEFAULT 0"),
                             ("items", "claude_at", "REAL")):
        have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if col not in have:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
    _drop_cost_columns(conn)
    conn.commit()


def _drop_cost_columns(conn: sqlite3.Connection) -> None:
    """Old databases still carry the columns the cost meter wrote to.

    The schema above no longer declares them, but CREATE TABLE IF NOT
    EXISTS leaves an existing file exactly as it was, so without this the
    column sits there forever holding numbers nothing produces any more.
    Safe to run on every connect.
    """
    for table in ("items", "runs"):
        have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if "cost_usd" in have:
            conn.execute("ALTER TABLE %s DROP COLUMN cost_usd" % table)
    conn.commit()


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
        "slide_count", "focus_slide", "pdf_path", "media_dir", "links_checked", "gate_json",
        "note_json", "enrich_json", "attempts", "created_at", "updated_at",
        "processed_at", "error", "claude_state", "claude_json", "claude_attempts",
        "claude_at"}]
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


def log_run(conn, iid, stage, ok, detail="", seconds=0.0) -> None:
    conn.execute("INSERT INTO runs (item_id,stage,ok,detail,seconds,at)"
                 " VALUES (?,?,?,?,?,?)",
                 (iid, stage, 1 if ok else 0, str(detail)[:2000], seconds, time.time()))
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
    for k in ("note_json", "enrich_json", "gate_json", "claude_json"):
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
               place: str = "", section: str = "", q: str = "",
               urgent: bool = False, limit: int = 200) -> list[dict]:
    sql = ["SELECT i.* FROM items i"]
    # Kept apart because the joins come before the WHERE in the SQL text.
    # One shared list put the search words where a tag value belonged the
    # moment a search and a filter were both on, and the list came back empty.
    join_args: list[Any] = []
    where_args: list[Any] = []
    joins, where = [], []

    if q.strip():
        joins.append("JOIN items_fts f ON f.id = i.id")
        where.append("items_fts MATCH ?")
        where_args.append(q.strip())
    for facet, val in (("action", action), ("topic", topic), ("place", place)):
        if val:
            alias = f"t_{facet}"
            joins.append(f"JOIN tags {alias} ON {alias}.item_id=i.id "
                         f"AND {alias}.facet='{facet}' AND {alias}.value=?")
            join_args.append(val.lower())
    if section:
        # A section includes everything filed under its subsections.
        joins.append("JOIN (SELECT DISTINCT item_id FROM tags WHERE facet='section' "
                     "AND (value=? OR value LIKE ?)) t_section ON t_section.item_id=i.id")
        join_args += [section.lower(), section.lower() + "/%"]
    if status:
        where.append("i.status=?")
        where_args.append(status)
    if urgent:
        where.append("i.urgent=1")

    sql += joins
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY i.urgent DESC, COALESCE(i.processed_at, i.created_at) DESC LIMIT ?")

    rows = conn.execute(" ".join(sql), join_args + where_args + [limit]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("note_json", None)
        d.pop("enrich_json", None)
        # The tile only needs to know whether the follow-up answered, not the
        # answer. "fu" rather than the column name, because the page reading
        # this is also the one published, and it names no vendor.
        claude = {}
        try:
            claude = json.loads(d.pop("claude_json", None) or "{}") or {}
        except Exception:
            pass
        d["fu"] = {"state": d.get("claude_state") or "",
                   "answered": claude.get("answered", ""),
                   "artifacts": len(claude.get("artifacts") or []),
                   "verdict": claude.get("verdict", "")}
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
    out["sections"] = sections(conn)
    return out


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
# Two levels: a section, and types inside it. "make a new section called to
# watch with subsections for types of videos" is the request this exists
# for. Deeper trees were not asked for and are harder to file into well.
def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:40] or "section"


def ensure_section(conn, path: list[str], about: str = "", asked: str = "") -> str:
    """Create a section and its parent if they are missing. Returns the id."""
    parent, sid = "", ""
    names = [" ".join(str(n).split())[:60] for n in (path or [])[:2]]
    names = [n for n in names if n]
    for depth, name in enumerate(names):
        sid = (parent + "/" if parent else "") + _slug(name)
        last = depth == len(names) - 1
        row = conn.execute("SELECT about FROM sections WHERE id=?", (sid,)).fetchone()
        if not row:
            conn.execute("INSERT INTO sections (id,name,parent,about,asked,created_at)"
                         " VALUES (?,?,?,?,?,?)",
                         (sid, name, parent or None, about if last else "",
                          asked if last else "", time.time()))
        elif last and about and not (row["about"] or "").strip():
            conn.execute("UPDATE sections SET about=? WHERE id=?", (about, sid))
        parent = sid
    conn.commit()
    return sid


def file_item(conn, iid: str, section_ids: list[str]) -> None:
    """Put an item in sections. Adds to what it is already in, never removes."""
    have = facets_for(conn, iid).get("section") or []
    set_tags(conn, iid, "section", have + [s for s in section_ids if s])


def sections(conn) -> list[dict]:
    """Every section, each parent followed by its children, with item counts.

    A parent's count is the items in it or in any of its subsections,
    counted once each.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT id, name, parent, about FROM sections")]
    for r in rows:
        r["count"] = conn.execute(
            "SELECT COUNT(DISTINCT item_id) c FROM tags WHERE facet='section'"
            " AND (value=? OR value LIKE ?)", (r["id"], r["id"] + "/%")).fetchone()["c"]
    top = sorted((r for r in rows if not r["parent"]), key=lambda r: r["name"].lower())
    out = []
    for p in top:
        out.append(p)
        out += sorted((r for r in rows if r["parent"] == p["id"]),
                      key=lambda r: r["name"].lower())
    # A child whose parent row went missing still shows rather than vanishing.
    out += [r for r in rows if r not in out]
    return out


# ---------------------------------------------------------------------------
# Playbook
# ---------------------------------------------------------------------------
# Lessons are about how to handle a kind of item, never about one item's
# content. No links in them: a lesson is read by later prompts, and a link
# planted by a post would otherwise ride along into every one after it.
_LINKISH = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|io|org|net|ai|dev)\b", re.I)


def _norm_lesson(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", " ".join(str(text).lower().split()))


def add_lesson(conn, kind: str, topics: list[str], lesson: str,
               source: str = "") -> bool:
    """Keep a lesson unless it is empty, carries a link, or is already known."""
    lesson = " ".join(str(lesson or "").split())[:400]
    if len(lesson) < 12 or _LINKISH.search(lesson):
        return False
    norm = _norm_lesson(lesson)
    for r in conn.execute("SELECT lesson FROM playbook"):
        if _norm_lesson(r["lesson"]) == norm:
            return False
    tops = ",".join(sorted({str(t).strip().lower() for t in (topics or [])
                            if str(t).strip()}))[:300]
    conn.execute("INSERT INTO playbook (kind, topics, lesson, source, created_at)"
                 " VALUES (?,?,?,?,?)",
                 ((kind or "").strip().lower()[:40], tops, lesson, source, time.time()))
    conn.commit()
    return True


def lessons_for(conn, *, kinds=(), topics=(), text: str = "",
                limit: int = 10) -> list[dict]:
    """The lessons most likely to matter for the next item, best first."""
    kinds = {str(k).lower() for k in kinds if k}
    topics = {str(t).lower() for t in topics if t}
    words = {w for w in re.findall(r"[a-z]{5,}", (text or "").lower())}
    scored = []
    for r in conn.execute("SELECT * FROM playbook"):
        d = dict(r)
        score = 3 if (d.get("kind") or "") in kinds else 0
        mine = {t for t in (d.get("topics") or "").split(",") if t}
        score += 2 * len(mine & topics)
        score += min(3, len(words & set(re.findall(r"[a-z]{5,}", d["lesson"].lower()))))
        if score:
            scored.append((score, d.get("used") or 0, d.get("created_at") or 0, d))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [d for *_, d in scored[:limit]]


def mark_used(conn, ids: list[int]) -> None:
    now = time.time()
    for i in ids:
        conn.execute("UPDATE playbook SET used=COALESCE(used,0)+1, last_used=? WHERE id=?",
                     (now, i))
    conn.commit()
