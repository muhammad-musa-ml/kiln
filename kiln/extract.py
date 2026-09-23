"""Extraction: turn acquired bytes into a structured note.

One multimodal call replaces the old Whisper + OCR + entity stack. Two
things here are load-bearing and both were measured, not assumed:

  * Extraction is NON-DETERMINISTIC. The same model on the same 11 images
    returned 3/3 links and 91 lines on one run, 2/3 and 51 on the next.
    High-value items therefore get a second pass and the two results are
    UNIONed rather than one being trusted.
  * THINKING HURTS HERE. Budget spent reasoning is budget not spent
    transcribing (51 lines -> 18). config.THINKING_BUDGET keeps it at 0
    for extract and saves it for the judgement calls.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import config, models
from .acquire import Acquired

# A creator saying "comment X and I'll send it" means the payload is NOT in
# the post. Half of a real 121-caption sample did this. Detecting the gate
# and surfacing the keyword turns a dead end into a one-tap action.
GATE_RE = re.compile(
    r"(?:comment|drop|type|dm|send)\s+(?:me\s+)?[\"'“‘]?([A-Za-z0-9 ]{2,20})[\"'”’]?"
    r"(?:\s+(?:below|down|now|and|to|for|in the comments))",
    re.I,
)
LINKBIO_RE = re.compile(r"link\s+in\s+(?:my\s+)?bio", re.I)

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
  "open_questions": ["what a curious reader would still need answered"]
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
        bits.append(f"This is a {len(acq.slides)}-slide carousel. Cover every slide.")
    if acq.focus_slide:
        bits.append(
            f"NOTE: the person saving this linked directly to slide {acq.focus_slide} - "
            "treat that slide as the one they cared about most and give it extra detail."
        )
    if acq.comment_count:
        bits.append(f"The post has {acq.comment_count} comments.")
    if user_note:
        bits.append(f"What the person saving it said: \"{user_note}\"")
    return "\n".join(bits)


def _media_for(acq: Acquired, limit: int = 16) -> list[Path]:
    if acq.video:
        return [Path(acq.video)]
    return [Path(p) for p in acq.slides[:limit]]


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
                  "code_snippets", "topics", "open_questions"):
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


def extract_item(acq: Acquired, *, user_note: str = "", deep: bool = False,
                 double_pass: bool | None = None) -> dict:
    """Read an acquired item into a structured note.

    Returns the note dict plus a `_meta` block describing how it was produced,
    so the UI can be honest about provenance.
    """
    media = _media_for(acq)
    prompt = PROMPT.format(context=_context_block(acq, user_note))

    task = "extract_deep" if deep else "extract"
    r1 = models.generate(task, prompt, media)
    meta: dict[str, Any] = {
        "passes": [], "cost_usd": 0.0, "escalated": deep, "media_count": len(media),
    }

    def log(r):
        meta["passes"].append({
            "model": r.label, "ok": r.ok, "seconds": round(r.seconds, 1),
            "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "cost_usd": round(r.cost_usd, 5), "error": r.error[:160],
            "attempts": r.attempts,
        })
        meta["cost_usd"] = round(meta["cost_usd"] + r.cost_usd, 5)

    log(r1)
    note = r1.data if (r1.ok and isinstance(r1.data, dict)) else {}

    if not note:
        return {"_meta": meta, "_error": r1.error or "extraction failed",
                "title": acq.title or acq.caption[:70] or acq.url,
                "kind": "other", "sections": [], "links": [], "entities": [],
                "onscreen_text": [], "topics": [], "action_hint": "reference"}

    # Second independent pass for the kinds where a miss actually costs
    # something, then union. Beats the measured run-to-run variance.
    # A THIN read is the real signal, not the item's kind. Measured: the same
    # deck returned 123 on-screen lines on one model and 24 on the fallback,
    # with code snippets going 5 -> 0. Fewer than ~3 transcribed lines per
    # slide means the pass skimmed, whatever it claims to have found.
    n_media = max(1, len(media))
    lines = len(note.get("onscreen_text") or [])
    thin = lines < 3 * n_media or not note.get("sections")
    if double_pass is None:
        double_pass = thin or note.get("kind") in config.DOUBLE_PASS_KINDS or deep
    meta["thin_first_pass"] = thin
    meta["lines_per_media"] = round(lines / n_media, 1)
    if double_pass:
        r2 = models.generate(task, prompt + "\n\nBe exhaustive. Prefer completeness over brevity.", media)
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
