"""Build the public site.

Whitelist, not blacklist. Fields are named one by one, so anything I add to
the database later stays private until I deliberately list it here.

Output is a folder of static files. No database, no keys, no write routes.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from . import config, store

OUT = config.ROOT / "public"

# --- the whitelist -------------------------------------------------------
ITEM_FIELDS = ("id", "url", "kind", "action", "title", "hook", "summary",
               "owner", "posted", "slide_count", "focus_slide", "links_checked")
# Added by public_item(): media_id, pdf_file - both opaque, neither a real path.

NOTE_FIELDS = ("sections", "onscreen_text", "entities", "topics",
               "code_snippets", "spoken_transcript", "open_questions")

ENRICH_FIELDS = ("what_it_is", "current_state", "why_it_matters",
                 "prerequisites", "time_to_useful", "gotchas",
                 "beyond_the_post", "official_docs", "best_free_resources",
                 "project", "is_it_good", "maturity", "alternatives",
                 "where_it_applies", "what_it_replaces",
                 "role", "company", "location", "remote", "is_open",
                 "deadline_public", "requirements", "how_to_stand_out",
                 "useful_links", "next_action")

# What the follow-up produced that a stranger may see: the answer, the files
# and where the facts came from. Why it ran, what it could not do, and which
# models did the work stay here, the same as the read's own provenance.
FOLLOWUP_FIELDS = ("answer_html", "answered", "artifacts", "sources",
                   "extra_sections", "next_action")
ARTIFACT_FIELDS = ("file", "title", "about", "kind", "pages")
# No HTML among them: a page a model wrote would run its scripts on the
# site's own origin. When a document's PDF could not be made, it stays local.
PUBLISH_KINDS = {".pdf", ".md", ".csv", ".txt", ".json"}

# Never exported, for the avoidance of doubt. Enforced by the whitelist
# above; listed here so the audit can assert their absence.
NEVER = ("user_note", "user_do", "status", "urgent", "deadline", "cost_usd",
         "error", "media_dir", "pdf_path", "source", "processed_at",
         "created_at", "updated_at", "note_json", "enrich_json", "gate_json",
         "_meta", "_install_preview", "attempts", "quota", "local_token",
         "claude_json", "claude_state", "claude_attempts", "missing", "run_dir",
         "unit_items", "asked")

_ABS_PATH = re.compile(r"[A-Za-z]:\\\\?[^\s\"']+|/(?:home|Users)/[^\s\"']+")
_KEYISH = re.compile(r"AIza[0-9A-Za-z_\-]{10,}|sk-[0-9A-Za-z_\-]{10,}"
                     r"|sb_secret_[0-9A-Za-z_\-]+")


def scrub(value: Any) -> Any:
    """Remove absolute paths and key-shaped strings from anything exported."""
    if isinstance(value, str):
        v = _ABS_PATH.sub("[local path]", value)
        return _KEYISH.sub("[redacted]", v)
    if isinstance(value, list):
        return [scrub(x) for x in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not k.startswith("_")}
    return value


def pick(src: dict, fields: tuple[str, ...]) -> dict:
    out = {}
    for f in fields:
        if f in src and src[f] not in (None, "", [], {}):
            out[f] = scrub(src[f])
    return out


def public_item(full: dict) -> dict:
    """One item, reduced to what a stranger may see."""
    note = full.get("note") or {}
    enr = full.get("enrich") or {}
    gate = full.get("gate") or {}

    d = pick(full, ITEM_FIELDS)
    d["note"] = pick(note, NOTE_FIELDS)
    d["enrich"] = pick(enr, ENRICH_FIELDS)

    # The gate is useful publicly (it says what to comment) but the advice
    # string is the only part worth showing.
    if gate.get("gated"):
        d["gate"] = {"gated": True, "how": gate.get("how", ""),
                     "keyword": gate.get("keyword", "")}

    tags = full.get("tags") or {}
    d["tags"] = {k: v for k, v in tags.items()
                 if k in ("action", "topic", "place", "section")}

    fu = followup(full)
    if fu:
        d["followup"] = fu

    d["links"] = [{"url": l.get("url", ""), "label": l.get("label", ""),
                   "alive": bool(l.get("alive")),
                   "page_title": l.get("page_title", "")}
                  for l in (full.get("links") or []) if l.get("url")]

    # Media is addressed by an OPAQUE id under media/<item id>/. The real
    # directory and the absolute pdf path never leave this machine - only the
    # bare filename does, which reveals nothing.
    if full.get("slide_count"):
        d["slide_count"] = full["slide_count"]
        d["media_id"] = full["id"]
        pdf = full.get("pdf_path") or ""
        if pdf:
            d["pdf_file"] = Path(pdf).name

    # Ship the build prompt with the data rather than rebuilding it in JS.
    # The published page has no server, and two implementations of the same
    # text drift. This way jobs.py stays the only place it is written.
    if (enr.get("project") or {}).get("name"):
        try:
            from . import jobs
            d["build_prompt"] = scrub(jobs.build_prompt(full))
        except Exception:
            pass
    return d


def followup(full: dict) -> dict:
    """The part of an item's answer that is safe to publish, or {}.

    The follow-up's answer when there is one, otherwise the first pass's
    answer to the instruction. Both are stored as Markdown and rendered here,
    every time, so a fix to the renderer reaches every answer already stored
    rather than only the next one.
    """
    from . import artifacts

    c = full.get("claude") or {}
    enr = full.get("enrich") or {}
    out: dict = {}
    if c.get("answer"):
        out["answer_html"] = artifacts.markdown(str(c["answer"]))
        out["answered"] = c.get("answered", "")
    elif enr.get("answer"):
        out["answer_html"] = artifacts.markdown(str(enr["answer"]))
        out["answered"] = enr.get("answered", "")
    arts = [{k: a[k] for k in ARTIFACT_FIELDS if a.get(k) not in (None, "")}
            for a in c.get("artifacts") or []
            if a.get("file") and not a.get("error")
            and Path(str(a["file"])).suffix.lower() in PUBLISH_KINDS]
    if arts:
        out["artifacts"] = arts
    for k in ("sources", "extra_sections", "next_action"):
        if c.get(k):
            out[k] = c[k]
    return {k: scrub(v) for k, v in out.items() if k in FOLLOWUP_FIELDS}


def build(out: Path = OUT, copy_media: bool = True) -> dict:
    conn = store.connect()
    rows = store.list_items(conn, limit=10000)
    items = []
    for r in rows:
        full = store.get_item(conn, r["id"])
        if full:
            items.append(public_item(full))
    tree = store.sections(conn)
    conn.close()

    # Clear the CONTENTS, never the directory itself. On Windows a process
    # serving the folder (a preview server, an open Explorer window) holds a
    # handle on it, and rmtree on the root then fails HALFWAY - after the
    # files are gone. That leaves a broken build rather than no build.
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except PermissionError:
            pass
    (out / "data").mkdir(parents=True, exist_ok=True)

    built = time.strftime("%d %b %Y", time.localtime())

    # facets recomputed from the PUBLIC items, so a private-only tag cannot
    # appear in the sidebar counts.
    facets: dict[str, dict[str, int]] = {"by_action": {}, "by_topic": {}, "by_place": {}}
    for it in items:
        for facet, key in (("action", "by_action"), ("topic", "by_topic"), ("place", "by_place")):
            for v in (it.get("tags") or {}).get(facet, []) or []:
                facets[key][v] = facets[key].get(v, 0) + 1

    # The section tree, with names and counts only. What a section is for is
    # written from my instruction, so it stays here like the instruction does.
    filed = [set((it.get("tags") or {}).get("section") or []) for it in items]
    sections = []
    for s in tree:
        n = sum(1 for f in filed if any(v == s["id"] or v.startswith(s["id"] + "/")
                                        for v in f))
        if n:
            sections.append({"id": s["id"], "name": s["name"],
                             "parent": s.get("parent") or "", "count": n})

    (out / "data" / "items.json").write_text(
        json.dumps({"items": items, "built": built}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out / "data" / "facets.json").write_text(
        json.dumps({"total": len(items), **facets, "sections": sections,
                    "by_status": {}, "gated": sum(1 for i in items if i.get("gate")),
                    "dead_links": sum(1 for i in items for l in i.get("links", []) if not l["alive"])},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    # The page, switched to static mode.
    html = (config.WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace("</head>",
                        f'<script>window.KILN_STATIC=true;window.KILN_BUILT="{built}";</script></head>', 1)
    (out / "index.html").write_text(html, encoding="utf-8")

    # Host config travels WITH the build, so it can never drift out of sync.
    # The CSP is the answer to "secure even through inspecting elements":
    # a viewer can read every byte, and none of it can call anything.
    csp = ("default-src 'self'; "
           "script-src 'self' 'unsafe-inline'; "
           "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
           "font-src 'self' https://fonts.gstatic.com; "
           "img-src 'self' data:; "
           "connect-src 'self'; "          # no outbound calls, to anywhere
           "form-action 'none'; "
           "frame-ancestors 'none'; "
           "base-uri 'none'; "
           "object-src 'none'")
    (out / "vercel.json").write_text(json.dumps({
        "$schema": "https://openapi.vercel.sh/vercel.json",
        "headers": [{
            "source": "/(.*)",
            "headers": [
                {"key": "Content-Security-Policy", "value": csp},
                {"key": "X-Content-Type-Options", "value": "nosniff"},
                {"key": "X-Frame-Options", "value": "DENY"},
                {"key": "Referrer-Policy", "value": "no-referrer"},
                {"key": "Permissions-Policy",
                 "value": "camera=(), microphone=(), geolocation=(), interest-cohort=()"},
                {"key": "Strict-Transport-Security",
                 "value": "max-age=63072000; includeSubDomains"},
            ],
        }],
        "cleanUrls": True,
        "trailingSlash": False,
    }, indent=2), encoding="utf-8")

    copied = 0
    if copy_media:
        from . import artifacts
        for it in items:
            # Documents the follow-up made go under files/, so one called
            # doc.pdf can never overwrite the carousel's own bound PDF.
            for a in (it.get("followup") or {}).get("artifacts") or []:
                f = artifacts.item_dir(it["id"]) / a["file"]
                if f.is_file() and f.suffix.lower() in PUBLISH_KINDS:
                    dest = out / "media" / it["id"] / "files"
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest / f.name)
                    copied += 1
            src = config.MEDIA / _media_key(it)
            if not src.is_dir():
                continue
            dest = out / "media" / it["id"]
            dest.mkdir(parents=True, exist_ok=True)

            # Renamed to 01.webp, 02.webp, doc.pdf. The published filename
            # carries no shortcode and no account name - just an index - so
            # the media folder reveals nothing on its own.
            slides = sorted(p for p in src.iterdir()
                            if p.suffix.lower() in (".webp", ".jpg", ".jpeg", ".png"))
            for i, f in enumerate(slides, 1):
                shutil.copy2(f, dest / f"{i:02d}{f.suffix.lower()}")
                copied += 1
            it["slide_ext"] = slides[0].suffix.lower() if slides else ".webp"

            for f in src.glob("*.pdf"):
                shutil.copy2(f, dest / "doc.pdf")
                it["pdf_file"] = "doc.pdf"
                copied += 1
                break

        # rewrite items.json now that media names are settled
        (out / "data" / "items.json").write_text(
            json.dumps({"items": items, "built": built}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    return {"items": len(items), "media_files": copied, "out": str(out), "built": built}


def _media_key(it: dict) -> str:
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)",
                  it.get("url", ""))
    return m.group(1) if m else it["id"]


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
