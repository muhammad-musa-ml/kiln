"""A link goes in, a tagged and enriched item comes out.

acquire -> extract -> enrich -> tag -> store. Each stage is checkpointed so
a crash doesn't cost work you already paid for.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import acquire as acq_mod
from . import config, enrich as enrich_mod, extract as extract_mod, store

# Places worth noticing without asking a model.
_PLACES = {
    "la": "los angeles", "l.a.": "los angeles", "los angeles": "los angeles",
    "sf": "san francisco", "bay area": "san francisco", "san francisco": "san francisco",
    "nyc": "new york", "new york": "new york", "seattle": "seattle",
    "madison": "madison", "chicago": "chicago", "austin": "austin",
    "boston": "boston", "london": "london", "remote": "remote",
    "lahore": "lahore", "karachi": "karachi", "islamabad": "islamabad",
    "pakistan": "pakistan", "dubai": "dubai",
}

_ACTION_FALLBACK = {
    "job": "apply", "tool": "install", "repo": "install", "tutorial": "learn",
    "course": "learn", "recipe": "build", "place": "visit", "news": "read",
    "opinion": "read", "listicle": "read",
}


def derive_places(*texts: str) -> list[str]:
    hay = " ".join(t or "" for t in texts).lower()
    found = []
    for k, v in _PLACES.items():
        if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", hay) and v not in found:
            found.append(v)
    return found


def normalise_topics(topics: list[str]) -> list[str]:
    out, seen = [], set()
    for t in topics or []:
        t = re.sub(r"[^a-z0-9 +#.-]", "", str(t).lower()).strip()
        t = re.sub(r"\s+", " ", t)
        if len(t) < 2 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:8]


def derive_action(note: dict, user_do: str = "") -> str:
    d = (user_do or "").lower()
    for a, words in {
        "apply": ("apply", "application", "job", "intern", "position", "hiring"),
        "install": ("install", "set up", "setup", "try it", "use this"),
        "learn": ("learn", "understand", "study", "teach me", "course"),
        "build": ("build", "make", "project", "ship"),
        "read": ("read", "article"),
        "watch": ("watch",),
        "visit": ("visit", "go to", "trip"),
    }.items():
        if any(w in d for w in words):
            return a
    a = (note.get("action_hint") or "").lower()
    if a in store.ACTIONS:
        return a
    return _ACTION_FALLBACK.get((note.get("kind") or "").lower(), "reference")


def process_url(url: str, *, user_note: str = "", user_do: str = "",
                user_tags: list[str] | None = None, urgent: bool = False,
                deadline: str = "", source: str = "manual",
                conn=None, force: bool = False,
                do_enrich: bool = True) -> dict:
    """Run one link all the way through. Returns the stored item."""
    own = conn is None
    conn = conn or store.connect()
    iid = store.item_id(url)
    t_start = time.time()

    existing = store.get_item(conn, iid)
    if existing and existing.get("processed_at") and not force:
        return existing

    rec: dict[str, Any] = {
        "id": iid, "url": url, "source": source, "status": "triage",
        "user_note": user_note, "user_do": user_do,
        "urgent": 1 if urgent else 0, "deadline": deadline,
        "created_at": (existing or {}).get("created_at") or time.time(),
    }
    store.upsert_item(conn, rec)

    # ---- acquire -----------------------------------------------------
    t0 = time.time()
    try:
        acq = acq_mod.acquire(url)
    except Exception as e:
        acq = acq_mod.Acquired(url=url, kind=acq_mod.classify(url),
                               error=f"{type(e).__name__}: {e}")
    store.log_run(conn, iid, "acquire", not acq.error, acq.error or
                  f"{len(acq.slides)} slides, video={bool(acq.video)}", time.time() - t0)

    rec.update({
        "owner": acq.owner, "posted": acq.posted, "kind": acq.kind,
        "slide_count": len(acq.slides), "focus_slide": acq.focus_slide,
        "pdf_path": acq.pdf, "media_dir": str(config.MEDIA / acq.shortcode) if acq.shortcode else "",
        "error": acq.error,
    })
    if acq.error and not acq.slides and not acq.video and not acq.body_text:
        rec["status"] = "inbox"
        rec["processed_at"] = time.time()
        store.upsert_item(conn, rec)
        if own:
            conn.close()
        return store.get_item(conn, iid)

    # ---- extract -----------------------------------------------------
    t0 = time.time()
    deep = urgent or (acq.kind == "instagram" and (user_do or "").lower().find("job") >= 0)
    note = extract_mod.extract_item(acq, user_note=user_note or user_do, deep=deep)
    cost = (note.get("_meta") or {}).get("cost_usd", 0.0)
    store.log_run(conn, iid, "extract", not note.get("_error"),
                  note.get("_error", "") or f"{len(note.get('sections') or [])} sections",
                  time.time() - t0, cost)

    rec.update({
        "kind": note.get("kind") or acq.kind,
        "title": note.get("title") or acq.title or acq.caption[:80],
        "hook": note.get("hook", ""),
        "summary": note.get("summary", ""),
        "note_json": json.dumps(note, ensure_ascii=False),
        "gate_json": json.dumps(note.get("_gate") or {}, ensure_ascii=False),
        "cost_usd": cost,
    })
    store.upsert_item(conn, rec)

    # ---- enrich ------------------------------------------------------
    enriched: dict = {}
    if do_enrich and not note.get("_error"):
        t0 = time.time()
        try:
            enriched = enrich_mod.enrich_note(note, acq, user_note=user_do or user_note)
        except Exception as e:
            enriched = {"_meta": {"ok": False, "error": f"{type(e).__name__}: {e}"}}
        ecost = (enriched.get("_meta") or {}).get("cost_usd", 0.0)
        cost += ecost
        store.log_run(conn, iid, "enrich", (enriched.get("_meta") or {}).get("ok", False),
                      (enriched.get("_meta") or {}).get("error", "") or enriched.get("_enricher", ""),
                      time.time() - t0, ecost)
        preview = enrich_mod.make_install_preview(enriched)
        if preview:
            enriched["_install_preview"] = preview
        rec["enrich_json"] = json.dumps(enriched, ensure_ascii=False)
        rec["cost_usd"] = cost

    # ---- tag ---------------------------------------------------------
    action = derive_action(note, user_do)
    topics = normalise_topics(note.get("topics") or [])
    places = derive_places(user_note, user_do, note.get("summary", ""),
                           " ".join(str(x) for x in (note.get("onscreen_text") or [])[:40]))

    store.set_tags(conn, iid, "action", [action])
    store.set_tags(conn, iid, "topic", topics)
    store.set_tags(conn, iid, "place", places)
    store.set_tags(conn, iid, "user", [t.lower() for t in (user_tags or [])])

    rec["action"] = action
    rec["status"] = "active" if urgent else "triage"
    rec["processed_at"] = time.time()
    store.upsert_item(conn, rec)

    # ---- links + search index ---------------------------------------
    health = enriched.get("_link_health") or []
    if not health:
        try:
            health = enrich_mod.resolve_links(note.get("links") or [])
        except Exception:
            health = []
    store.set_links(conn, iid, health)

    body = "\n".join([
        note.get("summary", ""),
        " ".join(str(s.get("heading", "")) + " " + str(s.get("detail", ""))
                 for s in (note.get("sections") or [])),
        " ".join(str(x) for x in (note.get("onscreen_text") or [])),
        " ".join(str(e.get("name", "")) for e in (note.get("entities") or [])),
        note.get("spoken_transcript", "") or "",
        json.dumps(enriched, ensure_ascii=False)[:40000] if enriched else "",
        user_note, user_do,
    ])
    store.index_fts(conn, iid, rec.get("title", ""), rec.get("hook", ""),
                    rec.get("summary", ""), body)

    store.log_run(conn, iid, "total", True,
                  f"action={action} topics={topics}", time.time() - t_start, cost)
    out = store.get_item(conn, iid)
    if own:
        conn.close()
    return out


if __name__ == "__main__":
    import sys
    item = process_url(sys.argv[1], user_do=" ".join(sys.argv[2:]))
    print(json.dumps({k: v for k, v in item.items()
                      if k not in ("note_json", "enrich_json", "note", "enrich")},
                     indent=2, ensure_ascii=False, default=str)[:3000])
