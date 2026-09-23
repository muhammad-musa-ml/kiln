"""Parse the inbox doc into work.

Read only, never writes to the doc, and hashes each line so re-running
doesn't repeat anything. Grammar, all optional after the url:

    <url> | note: ... | do: ... | tag: a,b | by: Oct 14 | !
"""
from __future__ import annotations

import re
from typing import Any

from . import store

URL_RE = re.compile(r"https?://[^\s|<>\"')\]]+")
# Docs escapes markdown, including & and = inside URLs, which breaks them.
_ESCAPES = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~=&?:/@$%^,;\"'])")
# A line that is only a date is the timestamp written next to a link, not
# a note of its own.
_BARE_DATE = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s*\d{0,4})\s*$",
    re.I)
_BULLET = re.compile(r"^\s*(?:[-*+\u2022\u25cf\u25aa]|\d+[.)])\s*")
_BOLD = re.compile(r"\*\*(.*?)\*\*")


def _clean(line: str) -> str:
    line = _ESCAPES.sub(r"\1", line)
    line = _BOLD.sub(r"\1", line)
    line = _BULLET.sub("", line)
    return line.strip()


def parse_line(raw: str) -> dict[str, Any] | None:
    """Parse one inbox line. Returns None for blanks/headers/instructions."""
    line = _clean(raw)
    if not line or len(line) < 3:
        return None
    # skip the template's own scaffolding
    if re.match(r"^[=\-_]{3,}$", line):
        return None
    if re.match(r"^(KILN INBOX|HOW TO ADD|EXAMPLES?|WHAT KILN DOES|ANYTHING BELOW|links)\b",
                line, re.I):
        return None

    out: dict[str, Any] = {"raw": raw, "urgent": False, "tags": [],
                           "note": "", "do": "", "by": "", "url": ""}

    m = URL_RE.search(line)
    if m:
        out["url"] = m.group(0).rstrip(".,;:")
        rest = (line[:m.start()] + " " + line[m.end():]).strip()
    else:
        rest = line

    # example rows in the template use a placeholder shortcode
    if re.search(r"/(ABC123|DEF456|XYZ)\b", out["url"]):
        return None

    parts = [p.strip() for p in rest.split("|")]
    leftovers = []
    for p in parts:
        if not p:
            continue
        if p == "!" or p.startswith("!"):
            out["urgent"] = True
            p = p.lstrip("!").strip()
            if not p:
                continue
        kv = re.match(r"^(note|do|tag|tags|by|due|deadline)\s*:\s*(.+)$", p, re.I)
        if kv:
            key, val = kv.group(1).lower(), kv.group(2).strip()
            if key in ("tag", "tags"):
                out["tags"] += [t.strip().lower() for t in re.split(r"[,;]", val) if t.strip()]
            elif key in ("by", "due", "deadline"):
                out["by"] = val
            else:
                out[key] = val
        else:
            leftovers.append(p)

    extra = " ".join(x for x in leftovers if x).strip()
    # A bare trailing date (the doc auto-stamps one) is not a note.
    if extra and not re.fullmatch(r"[\d]{4}-[\d]{2}-[\d]{2}|[\d/.\-]{6,10}", extra):
        out["note"] = (out["note"] + " " + extra).strip()

    if not out["url"] and not out["note"]:
        out["note"] = line
    if not out["url"] and len(out["note"]) < 8:
        return None
    return out


def parse_doc(text: str) -> list[dict]:
    """Parse a whole inbox document into candidate items.

    A bare date line is attached to the item above it as `saved_on` rather
    than becoming a phantom note - that is how people actually write these
    docs (link on one line, date under it).
    """
    items: list[dict] = []
    for raw in (text or "").splitlines():
        cleaned = _clean(raw)
        if _BARE_DATE.match(cleaned):
            if items:
                items[-1]["saved_on"] = cleaned
            continue
        p = parse_line(raw)
        if p:
            items.append(p)
    return items


def new_items(text: str, conn=None) -> list[dict]:
    """Only the lines Kiln has not already processed."""
    own = conn is None
    conn = conn or store.connect()
    out = []
    for p in parse_doc(text):
        key = p.get("url") or p.get("note", "")
        h = store.line_hash(key)
        if store.already_seen(conn, h):
            continue
        p["_hash"] = h
        out.append(p)
    if own:
        conn.close()
    return out


def ingest_text(text: str, *, source: str = "gdoc", conn=None,
                process: bool = True) -> list[dict]:
    """Process every unseen line. Returns what it did."""
    from . import pipeline
    own = conn is None
    conn = conn or store.connect()
    results = []
    for p in new_items(text, conn):
        if not p.get("url"):
            store.mark_seen(conn, p["_hash"], None)
            results.append({"note_only": p.get("note", "")[:120], "status": "noted"})
            continue
        if process:
            item = pipeline.process_url(
                p["url"], user_note=p.get("note", ""), user_do=p.get("do", ""),
                user_tags=p.get("tags") or [], urgent=bool(p.get("urgent")),
                deadline=p.get("by", ""), source=source, conn=conn)
            store.mark_seen(conn, p["_hash"], item.get("id") if item else None)
            results.append({"url": p["url"], "id": (item or {}).get("id"),
                            "title": (item or {}).get("title", "")[:90],
                            "status": "processed"})
        else:
            results.append({"url": p["url"], "status": "pending"})
    if own:
        conn.close()
    return results


if __name__ == "__main__":
    import json
    import sys
    txt = sys.stdin.read() if not sys.argv[1:] else open(sys.argv[1], encoding="utf-8").read()
    print(json.dumps(parse_doc(txt), indent=2, ensure_ascii=False))
