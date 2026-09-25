"""A link goes in, a tagged and enriched item comes out.

acquire -> extract -> enrich -> tag -> store. The item is saved after the
read and again at the end, so a crash in a later stage still leaves the
read on the item. A re-run starts again from the link; nothing resumes.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import acquire as acq_mod
from . import config, enrich as enrich_mod, extract as extract_mod
from . import handoff, store

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

# What a link gets tagged when nothing could be read from it. Failures used
# to land under a guessed bucket or none at all, which is how a dead link
# ends up untitled at the bottom of the inbox with nothing pointing at it.
# One filter, and it says what to do rather than only that something broke.
REDO = "redo"

# How many reads a link whose read failed gets in all, the first one
# included, so two retries. The usual cause is something transient at the
# far end, so a couple of retries recovers most of them without grinding
# forever on one that is genuinely gone.
RETRY_READS = 3


def _day_spent(attempt: str) -> bool:
    """Did this model turn the read away because its free day was used up?"""
    return "budget spent" in attempt or "[quota: per day]" in attempt


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


_ACTION_WORDS = {
    "apply": ("apply", "application", "job", "intern", "position", "hiring"),
    "install": ("install", "set up", "setup", "try it", "use this"),
    "learn": ("learn", "understand", "study", "teach me", "course"),
    "build": ("build", "make", "project", "ship"),
    "read": ("read", "article"),
    "watch": ("watch", "video"),
    "visit": ("visit", "go to", "trip"),
}
# "put these in a section called to watch" names the bucket outright.
_NAMED = re.compile(
    r"(?:section|folder|list|bucket|group|tag)\s+(?:called|named|for)\s+"
    r"[\"']?(?:to\s+)?(\w+)", re.I)
# What the medium implies when nothing else is clear.
_KIND_BIAS = {"youtube": "watch", "tiktok": "watch", "instagram": "", "web": "read"}


def derive_action(note: dict, user_do: str = "", media_kind: str = "") -> str:
    """Which bucket this belongs in.

    Scored rather than first-match. An instruction like "make a new section
    called to watch" contains both "make" and "watch"; taking the first hit
    filed seven videos under build.
    """
    d = (user_do or "").lower()

    # Some actions simply do not apply to some media. A web page cannot be
    # watched, so no instruction and no keyword count should file it there.
    impossible = {"web": {"watch"}, "youtube": {"install", "visit"},
                  "tiktok": {"install", "visit"}}.get(media_kind, set())

    named = _NAMED.search(d)
    if named and named.group(1).lower() in store.ACTIONS:
        want = named.group(1).lower()
        # An instruction can name one section for a batch that isn't uniform:
        # "put these in to watch" alongside six videos and one article.
        if want not in impossible:
            return want
        # It named a section this item cannot belong to. The rest of that
        # sentence is about FILING, not about the item, so its verbs are not
        # evidence: "make a new section" must not make this a build task.
        d = ""

    scores = {a: sum(1 for w in words if w in d) for a, words in _ACTION_WORDS.items()}
    for a in impossible:
        scores[a] = -1
    # What the thing IS outweighs a single guess about it: a youtube link
    # with no instruction is something to watch, even if the model's hint
    # said learn.
    bias = _KIND_BIAS.get(media_kind, "")
    if bias and bias not in impossible:
        scores[bias] = scores.get(bias, 0) + 2
    hint = (note.get("action_hint") or "").lower()
    if hint in store.ACTIONS and hint not in impossible:
        scores[hint] = scores.get(hint, 0) + 1

    # Explicit tie-break, so the answer never depends on dict ordering.
    priority = ["apply", "install", "build", "watch", "read", "learn",
                "visit", "reference"]
    best = max(scores, key=lambda a: (scores[a], -priority.index(a)
                                      if a in priority else -99))
    if scores[best] > 0:
        return best
    if hint in store.ACTIONS:
        return hint
    return _ACTION_FALLBACK.get((note.get("kind") or "").lower(), "reference")


def _came_back_empty(note: dict, acq) -> bool:
    """Did the read actually get anything, or does it only look like it did?

    This used to be `not (sections or summary)`. An eleven slide carousel
    came back with no sections, no on-screen text, no links and no entities,
    and one summary clipped mid-sentence because the model ran out of room.
    The summary satisfied the or, so the item was filed as processed, shown
    with a title, and never surfaced by anything again.

    A post made of pictures that yields no sections and no on-screen text has
    not been read, whatever else came back with it.
    """
    if not (note.get("sections") or note.get("summary")):
        return True
    pictures = len(getattr(acq, "slides", []) or []) + (1 if getattr(acq, "video", "") else 0)
    if pictures >= 2 and not note.get("sections") and not note.get("onscreen_text"):
        return True
    return False


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
    tried = int((existing or {}).get("attempts") or 0)
    if existing and existing.get("processed_at") and not force:
        # A read that failed is not a read that is finished. Every reel in
        # the 2026-09-24 run set processed_at on its way out of the failure
        # branch, which meant the next run skipped it, and the one after
        # that, for good. Give a broken one a few more goes before it stops
        # asking, since the usual cause is something transient at the far end.
        if not (existing.get("error") and tried < RETRY_READS):
            return existing
    if user_tags is None and existing:
        # A re-fire or a retry passes no tags. Writing none would drop the
        # group tag that ties a link to the others on its line.
        user_tags = (existing.get("tags") or {}).get("user") or []

    rec: dict[str, Any] = {
        "id": iid, "url": url, "source": source, "status": "triage",
        "user_note": user_note, "user_do": user_do,
        "urgent": 1 if urgent else 0, "deadline": deadline,
        "created_at": (existing or {}).get("created_at") or time.time(),
        "attempts": tried + 1,
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
        # Nothing came back at all. Keep the link, say why in the open, and
        # tag it redo. This used to return here without setting a title or a
        # single tag, so a failed link became a blank untitled row that no
        # filter matched and nothing ever surfaced again.
        rec["status"] = "inbox"
        rec["action"] = REDO
        rec["title"] = acq.title or url
        rec["summary"] = "Nothing could be read from this link. %s" % acq.error
        rec["processed_at"] = time.time()
        store.upsert_item(conn, rec)
        store.set_tags(conn, iid, "action", [REDO])
        if own:
            conn.close()
        return store.get_item(conn, iid)

    # ---- extract -----------------------------------------------------
    t0 = time.time()
    # Anything the owner attached a message to gets the deep ladder and a
    # second pass. The old rule read user_do only and looked for the word
    # "job" in it, so an instruction saying "get the name of the companies
    # in the video ... links to apply ... deadlines" never triggered, because
    # the parser had filed it under user_note. Across 13 items the deep
    # ladder fired zero times.
    asked = (user_do or user_note or "").strip()
    deep = bool(urgent or asked)
    note = extract_mod.extract_item(acq, user_note=user_note or user_do, deep=deep)
    # The caption is where the company names and links usually are, and it
    # was only ever passed along in memory. Kept so later work can read it.
    note["_caption"] = (acq.caption or "")[:8000]
    if not note.get("_error"):
        # A brief written when every model was out is answered by this read.
        handoff.clear(iid)
    if (note.get("_meta") or {}).get("exhausted"):
        # Nothing on the ladder could read it. Write the brief and stop,
        # rather than storing whatever the last rung said. The next sync
        # asks whether Claude should read it instead.
        passes = (note.get("_meta") or {}).get("passes") or []
        models_tried = [a for pss in passes for a in (pss.get("attempts") or [])]
        handoff.write(
            iid, url=url, stage="extract",
            why=note.get("_error") or "no model on the ladder could read this",
            media=[str(m) for m in extract_mod._media_for(acq)],
            instruction=asked,
            schema=extract_mod.PROMPT.format(
                context="(the media is listed above)"),
            context=(acq.caption or "")[:2000],
            tried=models_tried)
        if models_tried and all(_day_spent(a) for a in models_tried):
            # Every model had used up its day before this read started, so
            # nothing was really tried. Counting it would spend one of the
            # link's three tries on a day when nothing could have worked.
            rec["attempts"] = tried

    store.log_run(conn, iid, "extract", not note.get("_error"),
                  note.get("_error", "") or f"{len(note.get('sections') or [])} sections",
                  time.time() - t0)

    rec.update({
        "kind": note.get("kind") or acq.kind,
        "title": note.get("title") or acq.title or acq.caption[:80],
        "hook": note.get("hook", ""),
        "summary": note.get("summary", ""),
        "note_json": json.dumps(note, ensure_ascii=False),
        "gate_json": json.dumps(note.get("_gate") or {}, ensure_ascii=False),
    })
    store.upsert_item(conn, rec)

    # ---- enrich ------------------------------------------------------
    enriched: dict = {}
    if do_enrich and not note.get("_error"):
        t0 = time.time()
        # What earlier follow-ups learned about items like this one. The
        # thirteenth reel on a topic should not be searched the same way as
        # the first.
        lessons = [l["lesson"] for l in store.lessons_for(
            conn, kinds=[note.get("kind")], topics=note.get("topics") or [],
            text=asked, limit=6)]
        try:
            enriched = enrich_mod.enrich_note(note, acq, user_note=user_do or user_note,
                                              lessons=lessons)
        except Exception as e:
            enriched = {"_meta": {"ok": False, "error": f"{type(e).__name__}: {e}"}}
        store.log_run(conn, iid, "enrich", (enriched.get("_meta") or {}).get("ok", False),
                      (enriched.get("_meta") or {}).get("error", "") or enriched.get("_enricher", ""),
                      time.time() - t0)
        preview = enrich_mod.make_install_preview(enriched)
        if preview:
            enriched["_install_preview"] = preview
        rec["enrich_json"] = json.dumps(enriched, ensure_ascii=False)

    # ---- tag ---------------------------------------------------------
    # An item that came back with nothing is not done, it is stuck. Working
    # this out before the tagging rather than after it, because a bucket
    # derived from an empty note is a guess, and redo is the truth.
    empty = _came_back_empty(note, acq)

    action = REDO if empty else derive_action(note, user_do, media_kind=acq.kind)
    topics = normalise_topics(note.get("topics") or [])
    places = derive_places(user_note, user_do, note.get("summary", ""),
                           " ".join(str(x) for x in (note.get("onscreen_text") or [])[:40]))

    store.set_tags(conn, iid, "action", [action])
    store.set_tags(conn, iid, "topic", topics)
    store.set_tags(conn, iid, "place", places)
    store.set_tags(conn, iid, "user", [t.lower() for t in (user_tags or [])])

    rec["action"] = action
    # Filing an empty note as triage makes it look processed; one slipped
    # through that way when every model rung was exhausted and the local
    # fallback was off.
    rec["status"] = "inbox" if empty else ("active" if urgent else "triage")
    if empty and not rec.get("error"):
        rec["error"] = "extraction returned nothing - re-fire when a model is free"
    if empty and not rec.get("title"):
        rec["title"] = acq.title or url
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
    # When the check actually ran. The published page can only show stored
    # results, so it has to say when they were taken rather than implying now.
    rec["links_checked"] = time.strftime("%d %b %Y", time.localtime())
    store.upsert_item(conn, rec)

    index(conn, iid)

    store.log_run(conn, iid, "total", True,
                  f"action={action} topics={topics}", time.time() - t_start)
    out = store.get_item(conn, iid)
    if own:
        conn.close()
    return out


def _texts(parts) -> str:
    return " ".join(str(s.get("heading", "")) + " " + str(s.get("detail", ""))
                    for s in parts or [] if isinstance(s, dict))


def index(conn, iid: str) -> None:
    """Rebuild one item's search entry from everything stored on it.

    One place, because two things now write to an item: the read and
    Claude's follow-up. An answer that search cannot find is half lost.
    """
    it = store.get_item(conn, iid)
    if not it:
        return
    note = it.get("note") or {}
    enriched = it.get("enrich") or {}
    claude = it.get("claude") or {}
    body = "\n".join([
        note.get("summary", "") or "",
        _texts(note.get("sections")),
        " ".join(str(x) for x in (note.get("onscreen_text") or [])),
        " ".join(str(e.get("name", "")) for e in (note.get("entities") or [])
                 if isinstance(e, dict)),
        note.get("spoken_transcript", "") or "",
        json.dumps(enriched, ensure_ascii=False)[:40000] if enriched else "",
        claude.get("answer", "") or "",
        _texts(claude.get("extra_sections")),
        it.get("user_note") or "", it.get("user_do") or "",
    ])
    store.index_fts(conn, iid, it.get("title", ""), it.get("hook", ""),
                    it.get("summary", ""), body)


def retry_failed(conn, limit: int = 5, gap: float = 6 * 3600) -> list[dict]:
    """Try the links whose read failed again, a few times, spaced out.

    process_url has been willing to retry a failed read since the reel fix,
    but nothing ever asked it to: the inbox only hands over lines it has not
    seen, and a failed line has been seen. So a reel that failed on a bad
    night stayed failed until somebody pressed re-fire by hand.
    """
    rows = conn.execute(
        "SELECT url, user_note, user_do, urgent, deadline, source, updated_at "
        "FROM items WHERE COALESCE(error, '') != '' AND COALESCE(attempts, 0) < ? "
        "ORDER BY created_at", (RETRY_READS,)).fetchall()
    out = []
    for r in rows:
        if len(out) >= limit:
            break
        if time.time() - float(r["updated_at"] or 0) < gap:
            continue
        out.append(process_url(r["url"], user_note=r["user_note"] or "",
                               user_do=r["user_do"] or "", urgent=bool(r["urgent"]),
                               deadline=r["deadline"] or "",
                               source=r["source"] or "retry", conn=conn))
    return out


if __name__ == "__main__":
    import sys
    item = process_url(sys.argv[1], user_do=" ".join(sys.argv[2:]))
    print(json.dumps({k: v for k, v in item.items()
                      if k not in ("note_json", "enrich_json", "note", "enrich")},
                     indent=2, ensure_ascii=False, default=str)[:3000])
