"""The part that goes past what the post said.

Different questions per kind: is this current and what should I build with
it, is this tool any good and how do I install it, where's the real job
posting. Everything is grounded in pages it actually fetched.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import config, models

# Check every link before showing it. Plenty are already dead.
def resolve_links(links: list[dict | str], timeout: int = 12) -> list[dict]:
    import urllib.request
    import urllib.error

    out: list[dict] = []
    seen: set[str] = set()
    for item in links or []:
        url = (item.get("url") if isinstance(item, dict) else str(item)) or ""
        url = url.strip().strip("<>\"'")
        if not url:
            continue
        if not url.startswith("http"):
            url = "https://" + url.lstrip("/")
        key = url.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)

        rec: dict[str, Any] = dict(item) if isinstance(item, dict) else {}
        rec["url"] = url
        try:
            req = urllib.request.Request(url, method="GET", headers={
                "User-Agent": "Mozilla/5.0 (compatible; KilnLinkCheck/1.0)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                rec["status"] = r.status
                rec["final_url"] = r.url
                rec["alive"] = 200 <= r.status < 400
                head = r.read(4096).decode("utf-8", "replace")
                t = re.search(r"<title[^>]*>(.*?)</title>", head, re.S | re.I)
                if t:
                    rec["page_title"] = " ".join(t.group(1).split())[:160]
        except urllib.error.HTTPError as e:
            rec["status"] = e.code
            rec["alive"] = False
        except Exception as e:
            rec["status"] = 0
            rec["alive"] = False
            rec["error"] = type(e).__name__
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Prompts, one per kind
# ---------------------------------------------------------------------------
_LEARN = """Someone saved a post about **{subject}** because they want to LEARN it.
Search the live web. Today is {today}.

Return ONLY JSON:
{{
  "what_it_is": "2-3 sentences, concrete, no marketing",
  "current_state": "latest stable version and release date, and whether the
                    post's content is still accurate as of today",
  "why_it_matters": "what it actually unlocks that the alternatives don't",
  "prerequisites": ["what you must already know"],
  "time_to_useful": "realistic hours to go from zero to shipping something small",
  "official_docs": [{{"title": "...", "url": "..."}}],
  "best_free_resources": [{{"title": "...", "url": "...", "why": "..."}}],
  "gotchas": ["the things people get wrong"],
  "beyond_the_post": ["important things the post did NOT cover"],
  "project": {{
    "name": "short repo-ready name",
    "one_liner": "what it does, in a sentence a recruiter understands",
    "why_portfolio_worthy": "why this is not another tutorial clone",
    "scope": "what is IN and explicitly what is OUT",
    "stack": ["..."],
    "milestones": [{{"step": "...", "outcome": "what works after this step"}}],
    "stretch": ["optional upgrades once it works"],
    "readme_outline": ["the sections the README should have"],
    "est_hours": 0
  }}
}}

Be specific. Name real versions, real URLs, real commands. If you are not
sure a fact is current, say so in that field rather than guessing.

Context from the saved post:
{context}
"""

_TOOL = """Someone saved a post recommending **{subject}** and wants to know whether
to actually install it. Search the live web. Today is {today}.

Return ONLY JSON:
{{
  "what_it_is": "2-3 plain sentences",
  "is_it_good": {{
    "verdict": "yes | yes-with-caveats | no | cannot-tell",
    "confidence": "high | medium | low",
    "evidence": ["concrete signals: stars, downloads, release cadence, who maintains it"],
    "against": ["the honest reasons not to"]
  }},
  "maturity": {{"latest_version": "...", "last_release": "...", "maintained": "yes|no|unclear"}},
  "what_it_replaces": ["what you would stop using"],
  "where_it_applies": ["concrete situations in which you'd reach for it"],
  "install": {{
    "platform": "windows",
    "command": "the single exact command, or \\"\\" if there isn't one",
    "manager": "pip|npm|winget|ollama|git|other",
    "touches": "what it writes to the machine",
    "uninstall": "how to undo it"
  }},
  "alternatives": [{{"name": "...", "why_instead": "..."}}],
  "verdict_for_this_user": "one honest sentence: install it, or don't, and why"
}}

Context from the saved post:
{context}
"""

_JOB = """Someone saved a post about a JOB or application opportunity. Their goal is
to actually apply. Find the REAL posting. Search the live web. Today is {today}.

Return ONLY JSON:
{{
  "role": "...", "company": "...", "location": "...", "remote": "yes|no|hybrid|unclear",
  "posting_urls": [{{"url": "...", "source": "company site|ats|aggregator", "why": "..."}}],
  "is_open": "open | closed | unclear",
  "deadline": "date or rolling or unknown",
  "sponsors_visa": "yes | no | unclear - and what the evidence is",
  "requirements": ["..."],
  "how_to_stand_out": ["specific to this posting, not generic advice"],
  "next_action": "the single concrete next step",
  "confidence": "high|medium|low - how sure you are this is the same posting"
}}

If you cannot find the exact posting, say so in confidence and return the
closest real openings you DID find rather than inventing a URL.

Context from the saved post:
{context}
"""

_GENERIC = """Someone saved this post. Add the context they would want. Search the
live web. Today is {today}.

Return ONLY JSON:
{{
  "what_it_is": "...",
  "why_it_matters": "...",
  "current_state": "is this still accurate/available today?",
  "useful_links": [{{"title": "...", "url": "...", "why": "..."}}],
  "beyond_the_post": ["what the post left out"],
  "next_action": "the single most useful next step"
}}

Context from the saved post:
{context}
"""

_PROMPTS = {"learn": _LEARN, "tool": _TOOL, "job": _JOB}

# Appended whenever something was asked. The schemas above describe a thing;
# this is the only place an answer to a question can go.
ANSWER_BLOCK = """

THE ACTUAL JOB. Everything above is the standing description. This is what
was asked for, and it is the part that matters:

    {ask}

Add these two keys to the JSON you return, alongside the ones above:

  "answer": "the answer, at whatever length it takes. If they asked for a
             list, give the whole list. If they asked whether something is
             real or free, say which and on what evidence. If they asked for
             links, give the links. Write it out properly, not as a summary
             of what you would write."
  "answered": "fully | partly | no",

Rules for it:
- Answer from the live sources and from what is actually in the post. Never
  from memory, and never a plausible guess at a url.
- If the post names things, use their names. The post's own headline is not
  the subject.
- If you could not answer, set "answered" to "no" and say in "answer" what
  is missing and where it would have to come from. That is a useful result.
- Do not claim the post did not contain something unless you actually looked
  at the post and it did not.
- Write the answer so it stands on its own. Do not repeat the request back."""

# Appended to every enrichment, asked or not. Whatever is listed here is
# picked up and finished by Claude afterwards (kiln/brain.py), so a model
# that is honest about its limits gets its work completed rather than
# silently left half done.
SELF_REPORT = """

WHAT YOU COULD NOT DO. Add these two keys as well:

  "followups": [{"do": "a concrete next step that would finish the job",
                 "why": "what it would give",
                 "blocked_by": "why you could not do it yourself here"}],
  "could_not": ["anything you were asked or expected to do and could not, and why"]

Be honest in both. If you suggest something you cannot do yourself (make a
document or a PDF, check a page you were not given, compare prices, verify a
claim you have no source for, find a link that is not in the sources), put it
in followups: it gets picked up and done after you. Use [] when there is
nothing."""

# note.kind / action_hint -> enricher
_KIND_MAP = {
    "tutorial": "learn", "course": "learn", "repo": "tool", "tool": "tool",
    "job": "job", "listicle": "generic", "recipe": "generic",
    "place": "generic", "opinion": "generic", "news": "generic",
}
_ACTION_MAP = {"learn": "learn", "install": "tool", "apply": "job", "build": "learn"}


def pick_enricher(note: dict) -> str:
    a = (note.get("action_hint") or "").lower()
    if a in _ACTION_MAP:
        return _ACTION_MAP[a]
    return _KIND_MAP.get((note.get("kind") or "").lower(), "generic")


def _subject(note: dict) -> str:
    ents = note.get("entities") or []
    for want in ("library", "tool", "repo", "course", "company", "product"):
        for e in ents:
            if isinstance(e, dict) and (e.get("type") or "").lower() == want:
                return e.get("name") or ""
    if ents and isinstance(ents[0], dict):
        return ents[0].get("name") or ""
    return note.get("title") or ""


def _context(note: dict, acq: Any = None, user_note: str = "") -> str:
    parts = [f"Title: {note.get('title','')}", f"Summary: {note.get('summary','')}"]
    secs = note.get("sections") or []
    if secs:
        parts.append("Sections covered: " + "; ".join(
            str(s.get("heading", ""))[:60] for s in secs[:20]))
    ents = [e.get("name") for e in (note.get("entities") or []) if isinstance(e, dict)]
    if ents:
        parts.append("Things mentioned: " + ", ".join(str(x) for x in ents[:15]))
    ost = note.get("onscreen_text") or []
    if ost:
        parts.append("On-screen text (sample): " + " | ".join(str(x) for x in ost[:25])[:1500])
    if acq is not None and getattr(acq, "caption", ""):
        parts.append(f"Creator caption: {acq.caption[:400]}")
    if user_note:
        parts.append(f"What the person saving it asked for: {user_note}")
    return "\n".join(parts)


ASK_QUERIES = """Someone saved a post and wants something out of it.
Write the web searches that would actually get it.

What they asked for:
{ask}

What the post turned out to contain:
{context}
{lessons}
Return ONLY JSON: {{"queries": ["...", "..."]}}
Up to 6 searches. Rules that matter:
- Search for the THINGS in the post, by name. If it names eleven companies,
  search for those companies, not for the post's own headline.
- One search per thing when they asked about several things.
- Make them searches a person would type, not sentences.
- If they asked whether something is real, free, or worth it, search for
  that specifically: pricing, reviews, whether it still exists."""

_LESSONS = """
What earlier work on posts like this one learned. Follow it:
{0}
"""


def _queries_from_ask(ask: str, note: dict, context: str,
                      lessons: list[str] | None = None) -> list[str]:
    """Turn the owner's instruction into searches, using what the post holds.

    The templates below search for a subject picked out of the note, which
    on a listicle is the post's own clickbait headline. Measured: a carousel
    naming eleven companies, with an instruction asking for those companies'
    websites and application links, was searched three times for
    "11 AI Startup Job Postings: Companies to Make You a Millionaire" and
    never once for a company.

    With no instruction this still runs when there are lessons for items of
    this kind, so what was learned last time changes the searches this time.
    """
    if not ask and not lessons:
        return []
    try:
        r = models.generate("classify", ASK_QUERIES.format(
            ask=(ask or "nothing specific; what the post is plainly for")[:800],
            context=context[:2500],
            lessons=_LESSONS.format("\n".join("- " + l for l in lessons))
            if lessons else ""), want_json=True)
        qs = (r.data or {}).get("queries") if isinstance(r.data, dict) else None
        out = [str(q).strip() for q in (qs or []) if str(q).strip()][:6]
        return out
    except Exception:
        return []


def _queries_for(which: str, subject: str, note: dict) -> list[str]:
    """What to actually go and read before answering."""
    s = subject or note.get("title", "")
    if which == "learn":
        return [f"{s} official documentation", f"{s} latest version release notes",
                f"{s} tutorial getting started", f"{s} common mistakes gotchas"]
    if which == "tool":
        return [f"{s} github repository", f"{s} install",
                f"{s} review worth it", f"{s} alternatives comparison"]
    if which == "job":
        comp = ""
        for e in (note.get("entities") or []):
            if isinstance(e, dict) and (e.get("type") or "").lower() == "company":
                comp = e.get("name", "")
                break
        return [f"{comp} {s} careers job posting".strip(),
                f"{comp} {s} apply".strip(),
                f"{comp} visa sponsorship".strip() or f"{s} visa sponsorship"]
    return [s, f"{s} official site", f"{s} 2026"]


def enrich_note(note: dict, acq: Any = None, *, user_note: str = "",
                today: str = "", lessons: list[str] | None = None) -> dict:
    """Run the right enricher and attach link health. Never raises.

    Grounding is done by Kiln's own retrieval (search.py), not by Gemini's
    grounded-search tool, whose free tier 429s immediately. Same result -
    real fetched pages and real citations - without a quota to run out of.
    """
    import datetime
    from . import search as ksearch

    today = today or datetime.date.today().isoformat()
    which = pick_enricher(note)
    subject = _subject(note) or note.get("title", "")

    ctx = _context(note, acq, user_note)
    # What they asked for comes first, because that is the thing that has to
    # be answered. The template searches stay behind it as a floor.
    queries = _queries_from_ask(user_note, note, ctx, lessons)
    queries += [q for q in _queries_for(which, subject, note) if q not in queries]
    queries = queries[:8]
    try:
        web_context, sources = ksearch.research(queries)
    except Exception:
        web_context, sources = "", []

    prompt = _PROMPTS.get(which, _GENERIC).format(
        subject=subject, today=today, context=ctx)
    if user_note:
        # The schemas are fixed shapes for describing a thing. None of them
        # has anywhere to put an answer to a question, so an instruction
        # could be read, understood, and still have nowhere to land. One of
        # these came back conceding it could not list the companies, which
        # was true of the read it was given and false of the post.
        prompt += ANSWER_BLOCK.format(ask=user_note[:1200])
    prompt += SELF_REPORT
    if lessons:
        prompt += _LESSONS.format("\n".join("- " + l for l in lessons))
    if web_context:
        prompt += (
            "\n\nLIVE SOURCES fetched just now. Ground every factual claim in "
            "these, and put the source number in brackets like [2] next to any "
            "version, date, figure or URL you take from them. If the sources do "
            "not answer something, say so rather than filling it in from memory."
            f"\n\n{web_context[:60000]}"
        )

    # Plain generation over fetched text - NOT the grounded-search tool.
    r = models.generate("reason", prompt, want_json=True)
    out: dict[str, Any] = {
        "_enricher": which,
        "_subject": subject,
        "_meta": {
            "model": r.label, "ok": r.ok, "seconds": round(r.seconds, 1),
            "error": r.error[:200],
            "attempts": r.attempts,
        },
        "_citations": r.citations or sources,
        "_queries": queries,
        "_sources_fetched": len([s for s in sources if s.get("n")]),
    }
    if r.ok and isinstance(r.data, dict):
        out.update(r.data)
    elif r.ok and r.text:
        out["raw"] = r.text[:4000]

    # Link health on everything we are about to show the user.
    candidates: list[dict | str] = list(note.get("links") or [])
    for key in ("official_docs", "best_free_resources", "useful_links", "posting_urls"):
        for it in (out.get(key) or []):
            if isinstance(it, dict) and it.get("url"):
                candidates.append(it)
    out["_link_health"] = resolve_links(candidates)
    return out


def make_install_preview(enriched: dict) -> dict | None:
    """Turn an install command into something the UI can show and gate.

    The user chose one-click-with-preview, so the contract is: show the exact
    command, what it touches, how to undo it - and mark it runnable ONLY if
    its base binary is allow-listed and it contains no shell-composition.
    """
    inst = enriched.get("install") or {}
    cmd = (inst.get("command") or "").strip()
    if not cmd:
        return None
    low = cmd.lower()
    base = re.split(r"[\s]+", cmd.strip())[0].lower()
    base = base.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].removesuffix(".exe")

    blocked = [p for p in config.FORBIDDEN_PATTERNS if p in low]
    allowed = base in config.RUNNABLE_BINARIES
    return {
        "command": cmd,
        "base": base,
        "manager": inst.get("manager", ""),
        "touches": inst.get("touches", ""),
        "uninstall": inst.get("uninstall", ""),
        "runnable": bool(allowed and not blocked),
        "reason": ("ok" if allowed and not blocked
                   else f"blocked: {', '.join(blocked)}" if blocked
                   else f"'{base}' is not on the allow-list"),
    }
