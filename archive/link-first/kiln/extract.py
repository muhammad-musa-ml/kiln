"""Turn acquired media into a structured note.

One multimodal call does speech, on-screen text and entities together.
Reads vary run to run, so anything important gets read twice and merged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import config, models
from .acquire import Acquired

# "comment X and I'll send it" means the thing isn't in the post at all.
# Catching the keyword at least tells you what to go and comment.
GATE_RE = re.compile(
    r"(?:comment|drop|type|dm|send)\s+(?:me\s+)?[\"'"']?([A-Za-z0-9 ]{2,20}?)[\"'"']?"
    r"(?:\s+(?:below|down|now|and|to|for|in the comments)\b)",
    re.I,
)
LINKBIO_RE = re.compile(r"link\s+in\s+(?:my\s+)?bio", re.I)

# Slides sent in one read. Instagram allows twenty in a carousel; this was
# sixteen, while the prompt still told the model to cover all eighteen of
# an eighteen-slide post.
MAX_SLIDES = 20

PROMPT = """You are reading a saved social-media post so it can be USED later,
not just remembered. Be exhaustive: this is the only pass over the pixels.

{context}

Return ONLY JSON matching this shape exactly:

{{
  "title": "punchy 6-12 word title naming the actual subject",
  "hook": "one sentence: what someone gets out of this",
  "kind": "tutorial | listicle | job | tool | repo | course | recipe | place | opinion | news | other",
  "summary": "3-6 sentences in the creator's voice, covering the whole thing",
  "sections": [
    {{"heading": "...", "detail": "full detail - do not compress away specifics"}}
  ],
  "onscreen_text": ["every line of text visible on screen, verbatim, in order"],
  "links": [
    {{"url": "exactly as written", "where": "onscreen|caption|spoken", "label": "what it is"}}
  ],
  "entities": [
    {{"name": "...", "type": "tool|library|person|company|book|course|repo|place|product|concept",
      "why": "what the post says about it"}}
  ],
  "spoken_transcript": "verbatim speech, or \\"\\" if the post is silent",
  "code_snippets": ["any code or commands shown on screen, verbatim"],
  "action_hint": "apply | learn | install | read | watch | visit | build | reference",
  "topics": ["3-6 lowercase topical tags"],
  "open_questions": ["what a curious reader would still need answered"],
  "could_not": ["anything you could not read or make out, and where it was"]
}}

Hard rules:
- onscreen_text is a LITERAL transcription. Never paraphrase it.
- NEVER invent, complete, or guess a URL. Copy only what is actually shown.
  A partially-readable URL goes in as-is; a plausible-looking one you cannot
  actually read must be omitted entirely.
- If there is no speech, spoken_transcript is "" - do not fabricate one.
- sections must cover EVERY slide/segment, in order. Do not stop early.
"""


def _context_block(acq: Acquired, user_note: str = "") -> str:
    bits = [f"Source: {acq.kind} post by @{acq.owner or 'unknown'}"]
    if acq.posted:
        bits.append(f"Posted: {acq.posted}")
    if acq.caption:
        bits.append(f'Caption as written by the creator: "{acq.caption}"')
    if acq.slides:
        n, sent = len(acq.slides), min(len(acq.slides), MAX_SLIDES)
        bits.append(f"This is a {n}-slide carousel. Cover every slide." if sent == n else
                    f"This is a {n}-slide carousel and you are given the first {sent}. "
                    f"Cover every one you are given, and say in could_not that the "
                    f"last {n - sent} were not sent.")
    if acq.focus_slide:
        bits.append(
            f"NOTE: the person saving this linked directly to slide {acq.focus_slide} - "
            "treat that slide as the one they cared about most and give it extra detail."
        )
    if acq.comment_count:
        bits.append(f"The post has {acq.comment_count} comments.")
    if getattr(acq, "duration", 0):
        bits.append(f"Runtime: {acq.duration // 60} minutes.")
    if user_note:
        # Framed as a job, not as something overheard. This used to read
        # "What the person saving it said", which is reported speech: the
        # model was told the sentence existed and never told to serve it.
        bits.append(
            "WHAT THIS IS BEING READ FOR. They asked for this:\n"
            f"    {user_note}\n"
            "Read with that in mind. Whatever answering it would need out of "
            "these pixels, get it: every name if they asked about the things "
            "named, every url if they asked for links, every price, date or "
            "deadline if they asked about those. Miss nothing they would need. "
            "You are not answering it here, the next stage does that, but it "
            "can only use what you pull out now.")

    # For a video with captions or an article there are no pixels to send,
    # and the transcript IS the content. Without this the model only ever
    # saw the description and wrote a note about the blurb.
    if acq.body_text and not acq.slides and not acq.video:
        label = ("Full transcript of the video" if acq.kind in ("youtube", "tiktok")
                 else "Full text of the page")
        bits.append(f"\n{label}:\n{acq.body_text[:120000]}")
    return "\n".join(bits)


def _media_for(acq: Acquired, limit: int | None = None) -> list[Path]:
    if acq.video:
        return [Path(acq.video)]
    return [Path(p) for p in acq.slides[:limit or MAX_SLIDES]]


def _union(a: dict, b: dict) -> dict:
    """Merge two independent passes. Lists union (order-preserving, deduped);
    scalars prefer the longer/more specific answer."""
    if not a:
        return b or {}
    if not b:
        return a

    out = dict(a)

    def key_of(x: Any) -> str:
        if isinstance(x, dict):
            for k in ("url", "name", "heading"):
                if x.get(k):
                    return str(x[k]).strip().lower().rstrip("/")
            return json.dumps(x, sort_keys=True)[:120].lower()
        return str(x).strip().lower()

    for field in ("sections", "onscreen_text", "links", "entities",
                  "code_snippets", "topics", "open_questions", "could_not"):
        merged, seen = [], set()
        for item in (a.get(field) or []) + (b.get(field) or []):
            k = key_of(item)
            if not k or k in seen:
                continue
            seen.add(k)
            merged.append(item)
        out[field] = merged

    for field in ("title", "hook", "summary", "spoken_transcript"):
        va, vb = (a.get(field) or ""), (b.get(field) or "")
        out[field] = va if len(str(va)) >= len(str(vb)) else vb

    out["kind"] = a.get("kind") or b.get("kind") or "other"
    out["action_hint"] = a.get("action_hint") or b.get("action_hint") or "reference"
    return out


def detect_gate(caption: str, onscreen: list[str] | None = None) -> dict:
    """Is the real payload gated behind a comment / DM / link-in-bio?"""
    hay = caption or ""
    if onscreen:
        hay += "\n" + "\n".join(str(x) for x in onscreen[:40])
    m = GATE_RE.search(hay)
    if m:
        kw = m.group(1).strip()
        if kw and kw.lower() not in {"below", "down", "now", "this", "and"}:
            return {"gated": True, "how": "comment", "keyword": kw,
                    "advice": f'Comment "{kw}" on the post - the creator sends the link/file back.'}
    if LINKBIO_RE.search(hay):
        return {"gated": True, "how": "link_in_bio", "keyword": "",
                "advice": "The payload is in the creator's bio link, not the post."}
    return {"gated": False}


def _floor_for(n_media: int, video: bool = False):
    """What a read of this item has to contain before it counts as one.

    Returns a callback for models.generate, or None when there is nothing to
    hold it to. The bar is deliberately low: it is not a quality score, it
    is a check that the model looked at the pictures at all. A carousel that
    comes back with no sections and no on-screen text was not read, and
    accepting that is how an eleven slide post ended up stored with a title
    and nothing else behind it.

    It used to apply only from two pictures up, which left a single image
    and every reel with no floor at all. A video can also pass on its speech.
    A page or a transcript with no media is not held to it: there is nothing
    to look at, only text that was already read.
    """
    if n_media < 1:
        return None

    def check(res) -> str:
        d = res.data if isinstance(res.data, dict) else {}
        if not d:
            return "no JSON came back"
        if not d.get("sections") and not d.get("onscreen_text") \
                and not (video and d.get("spoken_transcript")):
            return ("read %d piece%s of media and returned no sections and no "
                    "on-screen text%s" % (n_media, "" if n_media == 1 else "s",
                                          " or speech" if video else ""))
        return ""

    return check


def extract_item(acq: Acquired, *, user_note: str = "", deep: bool = False,
                 double_pass: bool | None = None) -> dict:
    """Read an acquired item into a structured note.

    Returns the note dict plus a `_meta` block describing how it was produced,
    so the UI can be honest about provenance.
    """
    media = _media_for(acq)
    prompt = PROMPT.format(context=_context_block(acq, user_note))

    task = "extract_deep" if deep else "extract"
    check = _floor_for(len(media), video=bool(acq.video))
    r1 = models.generate(task, prompt, media, accept=check)
    meta: dict[str, Any] = {
        "passes": [], "escalated": deep, "media_count": len(media),
    }

    def log(r):
        meta["passes"].append({
            "model": r.label, "ok": r.ok, "seconds": round(r.seconds, 1),
            "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "error": r.error[:160],
            "attempts": r.attempts,
        })

    log(r1)
    note = r1.data if (r1.ok and isinstance(r1.data, dict)) else {}

    # Every rung tried and none of them managed it. The caller hands the
    # item over rather than keeping whatever the last one happened to say.
    meta["exhausted"] = bool(getattr(r1, "exhausted", False))
    if not note:
        return {"_meta": meta, "_error": r1.error or "extraction failed",
                "title": acq.title or acq.caption[:70] or acq.url,
                "kind": "other", "sections": [], "links": [], "entities": [],
                "onscreen_text": [], "topics": [], "action_hint": "reference"}

    # Second independent pass for the kinds where a miss actually costs
    # something, then union. Beats the measured run-to-run variance.
    # Fewer than ~3 lines per slide means it skimmed, whatever it claims.
    n_media = max(1, len(media))
    lines = len(note.get("onscreen_text") or [])
    thin = lines < 3 * n_media or not note.get("sections")
    if double_pass is None:
        double_pass = thin or note.get("kind") in config.DOUBLE_PASS_KINDS or deep
    meta["thin_first_pass"] = thin
    meta["lines_per_media"] = round(lines / n_media, 1)
    if double_pass:
        r2 = models.generate(task, prompt + "\n\nBe exhaustive. Prefer completeness over brevity.",
                             media, accept=check)
        log(r2)
        if r2.ok and isinstance(r2.data, dict):
            before = len(note.get("onscreen_text") or []), len(note.get("links") or [])
            note = _union(note, r2.data)
            meta["union_gain"] = {
                "onscreen_text": len(note.get("onscreen_text") or []) - before[0],
                "links": len(note.get("links") or []) - before[1],
            }

    note["_meta"] = meta
    note["_gate"] = detect_gate(acq.caption, note.get("onscreen_text"))
    return note


if __name__ == "__main__":
    import sys
    from .acquire import acquire
    a = acquire(sys.argv[1])
    n = extract_item(a, deep="--deep" in sys.argv)
    print(json.dumps(n, indent=2, ensure_ascii=False)[:6000])
