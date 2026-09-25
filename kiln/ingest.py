"""Parse the inbox doc into work.

Read only, never writes to the doc, and remembers each link it has read so
re-running doesn't repeat anything. A link added to a line later is still
read, and an instruction added under a link later still reaches it.
Grammar, all optional after the url:

    <url> | note: ... | do: ... | tag: a,b | by: Oct 14 | !
"""
from __future__ import annotations

import re
import time
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


# How people introduce an instruction before getting to it. Carrying this
# into the prompt tells the model nothing and eats the start of the sentence
# it does care about, so it comes off the front.
_PREAMBLE = re.compile(
    r"^\s*(?:with\s+(?:the\s+)?message\s*[:\-]?\s*|"
    r"message\s*[:\-]\s*|note\s*[:\-]\s*|ask\s*[:\-]\s*)", re.I)


def _strip_preamble(text: str) -> str:
    """Drop a leading "with message :" and any quotes wrapped round it."""
    out = _PREAMBLE.sub("", text).strip()
    if len(out) > 1 and out[0] in "\"'" and out[-1] == out[0]:
        out = out[1:-1].strip()
    return out or text.strip()
# Separators people actually use between a link and a comment.
_SEP = re.compile(r"\s*\|\s*|\s+[—–]\s+|\s+-\s+(?=[A-Za-z])")


def parse_line(raw: str) -> dict[str, Any] | None:
    """Parse one inbox line. Returns None for blanks and template scaffolding.

    A line may carry SEVERAL urls. Reading only the first quietly dropped six
    links the first time this met a real doc, so every url is kept.
    """
    line = _clean(raw)
    if not line or len(line) < 3:
        return None
    if re.match(r"^[=\-_]{3,}$", line):
        return None
    if re.match(r"^(KILN INBOX|HOW TO ADD|EXAMPLES?|WHAT KILN DOES|ANYTHING BELOW|links)\b",
                line, re.I):
        return None

    out: dict[str, Any] = {"raw": raw, "urgent": False, "tags": [],
                           "note": "", "do": "", "by": "", "url": "", "urls": []}

    urls = [u.rstrip(".,;:") for u in URL_RE.findall(line)]
    urls = [u for u in urls if not re.search(r"/(ABC123|DEF456|XYZ)\b", u)]
    if urls:
        out["urls"] = urls
        out["url"] = urls[0]
    rest = URL_RE.sub(" ", line)

    leftovers = []
    for p in (s.strip(" ,;") for s in _SEP.split(rest)):
        if not p:
            continue
        if p.startswith("!"):
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
        elif _BARE_DATE.match(p):
            out["saved_on"] = p
        else:
            leftovers.append(p)

    extra = " ".join(leftovers).strip()
    if extra:
        # Anything written next to a link is something the owner wants done
        # with it. This used to require the text to START with one of about
        # twenty verbs, and the four richest instructions in the real inbox
        # all began "with message :" instead, so all four were filed as
        # background colour. `do` is what the pipeline acts on, `note` is
        # what it merely reads, and guessing between them on the first word
        # of a sentence was never going to work. Presence decides now. A
        # genuine aside can still say so with an explicit `note:` prefix.
        out["do"] = (out["do"] + " " + _strip_preamble(extra)).strip() \
            if out["do"] else _strip_preamble(extra)

    if not out["urls"] and not (out["note"] or out["do"]):
        out["note"] = line
    if not out["urls"] and len((out["note"] or out["do"])) < 8:
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
        if not p:
            continue
        # A line with no url, straight after one that had urls, is a
        # continuation: the date and the instruction written underneath the
        # link. Treated as its own item it becomes a phantom note and the
        # instruction never reaches the thing it was written about.
        if not p.get("urls") and items and items[-1].get("urls"):
            prev = items[-1]
            if p.get("saved_on"):
                prev["saved_on"] = p["saved_on"]
            for field in ("do", "note"):
                if p.get(field):
                    prev[field] = (prev.get(field, "") + " " + p[field]).strip()
            prev["tags"] += p.get("tags") or []
            prev["urgent"] = prev.get("urgent") or p.get("urgent", False)
            continue
        items.append(p)
    return items


def _known(conn, url: str) -> bool:
    return (store.already_seen(conn, store.line_hash(url))
            or conn.execute("SELECT 1 FROM items WHERE id=?",
                            (store.item_id(url),)).fetchone() is not None)


def new_items(text: str, conn=None) -> list[dict]:
    """The lines that carry something Kiln has not read yet.

    Decided link by link, not line by line. A line used to be remembered by
    its first link alone, so a second link added to it later was never read.
    `_new` holds the links still to read; `_hash` stays the first link's, the
    key every line seen before this change was stored under.
    """
    own = conn is None
    conn = conn or store.connect()
    out = []
    for p in parse_doc(text):
        urls = p.get("urls") or []
        if not urls:
            h = store.line_hash(p.get("note", ""))
            if store.already_seen(conn, h):
                continue
            p["_hash"], p["_new"] = h, []
            out.append(p)
            continue
        new = [u for u in urls if not _known(conn, u)]
        if not new:
            continue
        p["_hash"], p["_new"] = store.line_hash(urls[0]), new
        out.append(p)
    if own:
        conn.close()
    return out


def late_instructions(text: str, conn) -> list[dict]:
    """An instruction written under a link after the link was already read.

    The line is known, so it was skipped as a whole and the instruction never
    reached the item. Only an item with no instruction of its own takes one,
    so nothing I wrote earlier is ever overwritten. The follow-up then plans
    for it on the next sweep.
    """
    from . import pipeline
    out = []
    for p in parse_doc(text):
        do, note = (p.get("do") or "").strip(), (p.get("note") or "").strip()
        if not (do or note):
            continue
        for url in p.get("urls") or []:
            iid = store.item_id(url)
            row = conn.execute("SELECT user_do, user_note, processed_at FROM items "
                               "WHERE id=?", (iid,)).fetchone()
            if not row or not row["processed_at"] \
                    or (row["user_do"] or row["user_note"] or "").strip():
                continue
            conn.execute("UPDATE items SET user_do=?, user_note=?, claude_state='', "
                         "updated_at=? WHERE id=?", (do, note, time.time(), iid))
            conn.commit()
            pipeline.index(conn, iid)
            out.append({"url": url, "id": iid, "status": "instruction added"})
    return out


def ingest_text(text: str, *, source: str = "gdoc", conn=None,
                process: bool = True) -> list[dict]:
    """Process every unseen line. Returns what it did."""
    from . import pipeline
    own = conn is None
    conn = conn or store.connect()
    results = []
    for p in new_items(text, conn):
        urls = p.get("urls") or ([p["url"]] if p.get("url") else [])
        if not urls:
            store.mark_seen(conn, p["_hash"], None)
            results.append({"note_only": (p.get("note") or "")[:120], "status": "noted"})
            continue

        # One line can carry several links with a single instruction that
        # applies to all of them. Each becomes its own item, and they share
        # a group id so the instruction can be about the SET. The group comes
        # from the whole line, so a link added to it later joins the others.
        group = p["_hash"] if len(urls) > 1 else ""
        last_id = None
        for url in p.get("_new") or urls:
            if not process:
                results.append({"url": url, "status": "pending"})
                continue
            item = pipeline.process_url(
                url, user_note=p.get("note", ""), user_do=p.get("do", ""),
                user_tags=(p.get("tags") or []) + ([f"group:{group[:8]}"] if group else []),
                urgent=bool(p.get("urgent")), deadline=p.get("by", ""),
                source=source, conn=conn)
            last_id = (item or {}).get("id")
            store.mark_seen(conn, store.line_hash(url), last_id)
            results.append({"url": url, "id": last_id,
                            "title": ((item or {}).get("title") or "")[:90],
                            "status": "processed"})
        if process:
            store.mark_seen(conn, p["_hash"], last_id)
        if process and group:
            # A link read while it was alone on its line has no group tag.
            # Once the line has more, it belongs with the rest.
            tag = f"group:{group[:8]}"
            for url in urls:
                iid = store.item_id(url)
                if not conn.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
                    continue
                have = store.facets_for(conn, iid).get("user") or []
                if tag not in have:
                    store.set_tags(conn, iid, "user", have + [tag])
    if process:
        results += late_instructions(text, conn)
    if own:
        conn.close()
    return results


if __name__ == "__main__":
    import json
    import sys
    txt = sys.stdin.read() if not sys.argv[1:] else open(sys.argv[1], encoding="utf-8").read()
    print(json.dumps(parse_doc(txt), indent=2, ensure_ascii=False))
