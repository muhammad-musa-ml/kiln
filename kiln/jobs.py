"""Turn a project brief into something buildable.

Same text three ways: copy it into any chat, queue it, or run it here.
One description so the three can't drift apart.

The brief is written for a person to read. This rewrites it for an agent:
explicit in/out scope, pinned versions, acceptance criteria per step.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from . import config, store

JOBS_DIR = config.DATA / "jobs"
PENDING = JOBS_DIR / "pending"
DONE = JOBS_DIR / "done"
for _d in (JOBS_DIR, PENDING, DONE):
    _d.mkdir(parents=True, exist_ok=True)


def _slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "project").lower()).strip("-")
    return (s or "project")[:n]


# Enrichment cites its sources as [1][4]. Those numbers mean nothing to a
# build agent that never saw the source list, so they are stripped here.
_CITE = re.compile(r"\s*(?:\[\d+\])+")
_LEADNUM = re.compile(r"^\s*\d+[.)]\s*")


def clean(s: Any) -> str:
    """Strip citation markers and any leading numbering."""
    return _LEADNUM.sub("", _CITE.sub("", str(s or ""))).strip()


def split_scope(scope: Any) -> tuple[list[str], list[str]]:
    """Turn the brief's single prose `scope` into explicit IN and OUT lists.

    The schema stores one string ("IN: ... OUT: ..."). An agent handed that
    blob builds the wrong thing, so it is split before it is ever used.
    """
    if isinstance(scope, dict):
        return (list(scope.get("in") or []), list(scope.get("out") or []))
    text = str(scope or "")
    if not text.strip():
        return [], []
    m = re.split(r"\bOUT\s*[:\-]", text, maxsplit=1, flags=re.I)
    head = re.sub(r"^\s*IN\s*[:\-]\s*", "", m[0], flags=re.I)
    tail = m[1] if len(m) > 1 else ""

    def items(chunk: str) -> list[str]:
        parts = re.split(r"[;\n]|,(?![^(]*\))", chunk)
        return [p.strip(" .") for p in parts if len(p.strip(" .")) > 2]

    return items(head), items(tail)


def build_prompt(item: dict) -> str:
    """The self-contained prompt. Written to stand alone in any chat."""
    note = item.get("note") or {}
    enr = item.get("enrich") or {}
    proj = enr.get("project") or {}
    scope_in, scope_out = split_scope(proj.get("scope"))

    L: list[str] = []
    A = L.append

    A(f"# Build: {proj.get('name') or item.get('title') or 'project'}")
    A("")
    if proj.get("one_liner"):
        A(clean(proj["one_liner"]))
        A("")
    A("I want a working repository I can push to GitHub. Build it completely -")
    A("runnable code, tests where they make sense, and a README.")
    A("")

    if proj.get("why_portfolio_worthy"):
        A("## Why this matters")
        A(clean(proj["why_portfolio_worthy"]))
        A("")

    if scope_in or scope_out:
        A("## Scope")
        if scope_in:
            A("Build these:")
            for x in scope_in:
                A(f"- {clean(x)}")
        if scope_out:
            A("")
            A("Explicitly do NOT build these:")
            for x in scope_out:
                A(f"- {clean(x)}")
        A("")

    stack = proj.get("stack") or []
    if stack:
        A("## Stack - use these exact versions")
        for s in stack:
            A(f"- {clean(s)}")
        A("")

    ms = proj.get("milestones") or []
    if ms:
        A("## Milestones - each must be verifiably done before the next")
        for i, m in enumerate(ms, 1):
            A(f"{i}. **{clean(m.get('step',''))}**")
            if m.get("outcome"):
                A(f"   - Done when: {clean(m['outcome'])}")
        A("")

    if proj.get("readme_outline"):
        A("## README must cover")
        for s in proj["readme_outline"]:
            A(f"- {clean(s)}")
        A("")

    if proj.get("stretch"):
        A("## Only after everything above works")
        for s in proj["stretch"]:
            A(f"- {clean(s)}")
        A("")

    # Grounding: what the source actually said, and which links are alive.
    if enr.get("what_it_is"):
        A("## Background")
        A(clean(enr["what_it_is"]))
        A("")
    if enr.get("gotchas"):
        A("## Known traps - handle these, do not rediscover them")
        for g in enr["gotchas"]:
            A(f"- {clean(g)}")
        A("")

    live = [l for l in (item.get("links") or []) if l.get("alive")]
    docs = [d for d in (enr.get("official_docs") or []) if isinstance(d, dict)]
    if live or docs:
        A("## Reference (checked and reachable)")
        for d in docs[:6]:
            A(f"- {d.get('title','doc')}: {d.get('url','')}")
        for l in live[:6]:
            A(f"- {l.get('page_title') or l.get('url')}: {l.get('url')}")
        A("")

    A("## How I want it delivered")
    A("- A single repository, ready to `git init` and push.")
    A("- Pin every dependency to the versions above.")
    A("- A README that explains what it does and how to run it, written plainly.")
    A("- No placeholder code and no TODO stubs - if something is out of scope,")
    A("  leave it out rather than stubbing it.")
    A("")
    A(f"Source this came from: {item.get('url','')}")
    if proj.get("est_hours"):
        A(f"Rough size: about {proj['est_hours']} hours of work.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------
def existing(job_id: str) -> dict:
    """Where a job already lives, if it does."""
    for folder, state in ((PENDING, "pending"), (DONE, "done")):
        for f in sorted(folder.glob(f"{job_id}*.md")):
            return {"file": str(f), "job_state": state}
    return {}


def create(item_id: str, *, target: str = "copy", repo_name: str = "",
           directory: str = "", conn=None) -> dict:
    """Write a job. `target` is copy | local | actions.

    The id comes from the item, not the clock, so pressing the button twice
    finds the job that is already there instead of making another one.
    """
    own = conn is None
    conn = conn or store.connect()
    item = store.get_item(conn, item_id)
    if own:
        conn.close()
    if not item:
        return {"error": "unknown item"}

    proj = (item.get("enrich") or {}).get("project") or {}
    name = repo_name or _slug(proj.get("name") or item.get("title") or "project")
    jid = f"{item_id[:12]}-{name}"[:60]
    prompt = build_prompt(item)

    job = {
        "id": jid, "item_id": item_id, "target": target,
        "repo_name": name, "directory": directory,
        "title": proj.get("name") or item.get("title") or "",
        "source_url": item.get("url", ""),
        "created_at": time.time(), "state": "pending",
        "prompt": prompt,
    }

    if target in ("local", "actions"):
        prior = existing(jid)
        if prior:
            job.update(prior)
            job["already"] = True
            return job
        path = PENDING / f"{jid}.md"
        path.write_text(_job_file(job), encoding="utf-8")
        job["file"] = str(path)
    return job


def _job_file(job: dict) -> str:
    """Front-matter so a session can pick it up, then the prompt itself."""
    return (
        "---\n"
        f"job_id: {job['id']}\n"
        f"item_id: {job['item_id']}\n"
        f"repo_name: {job['repo_name']}\n"
        f"target: {job['target']}\n"
        f"directory: {job.get('directory','')}\n"
        f"source: {job['source_url']}\n"
        f"created: {time.strftime('%Y-%m-%d %H:%M', time.localtime(job['created_at']))}\n"
        "state: pending\n"
        "---\n\n"
        + job["prompt"] + "\n"
    )


def pending() -> list[dict]:
    out = []
    for f in sorted(PENDING.glob("*.md")):
        head: dict[str, str] = {}
        try:
            txt = f.read_text(encoding="utf-8")
            if txt.startswith("---"):
                for line in txt.split("---", 2)[1].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        head[k.strip()] = v.strip()
        except Exception:
            pass
        out.append({"file": str(f), "name": f.name, **head})
    return out


def complete(job_id: str, note: str = "") -> bool:
    for f in PENDING.glob(f"{job_id}*.md"):
        dest = DONE / f.name
        txt = f.read_text(encoding="utf-8").replace("state: pending", "state: done", 1)
        if note:
            txt += f"\n\n---\nresult: {note}\n"
        dest.write_text(txt, encoding="utf-8")
        f.unlink()
        return True
    return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "pending":
        for j in pending():
            print(f"{j['name']}  ->  {j.get('repo_name','')}  ({j.get('source','')})")
    elif len(sys.argv) > 2 and sys.argv[1] == "show":
        print(Path(sys.argv[2]).read_text(encoding="utf-8"))
    else:
        print(json.dumps(create(sys.argv[1] if len(sys.argv) > 1 else "",
                                target="copy"), indent=2)[:3000])
