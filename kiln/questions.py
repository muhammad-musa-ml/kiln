"""Things the nightly run cannot decide on its own.

The run happens at nine in the morning while I am asleep, so it cannot stop
and ask me anything. When it hits a decision that is mine to make, it writes
the question down here and carries on with the rest of the queue. The next
run prints every open question before it does anything else, and the UI shows
them as cards I can answer by clicking.

One question per job per kind. Asking the same thing twice because the agent
was down two mornings running is noise, not information.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config

QUESTIONS = config.DATA / "jobs" / "questions"
QUESTIONS.mkdir(parents=True, exist_ok=True)


def _path(job_id: str, kind: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in job_id)
    return QUESTIONS / f"{safe}.{kind}.json"


def ask(job_id: str, kind: str, title: str, detail: str,
        options: list[str] | None = None, repo: str = "") -> dict:
    """Record a question. Re-asking an open one only refreshes its detail."""
    p = _path(job_id, kind)
    now = time.time()
    q = {"id": p.stem, "job_id": job_id, "kind": kind, "repo": repo,
         "title": title, "detail": detail, "options": options or [],
         "asked_at": now, "asked_count": 1,
         "answered_at": 0, "answer": "", "note": ""}
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            old = {}
        if old.get("answered_at"):
            # Answered already. The condition came back, so this is a new
            # question about the same job rather than the old one repeating.
            old = {}
        if old:
            q["asked_at"] = old.get("asked_at", now)
            q["asked_count"] = int(old.get("asked_count") or 0) + 1
            # A repeat that only carries fresh detail must not strip the
            # choices off the card. Without this the second morning of the
            # same outage leaves me a question and no way to answer it.
            q["options"] = options or old.get("options") or []
            q["title"] = title or old.get("title") or ""
    p.write_text(json.dumps(q, indent=2), encoding="utf-8")
    return q


def all_questions() -> list[dict]:
    out = []
    for f in sorted(QUESTIONS.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def open_questions() -> list[dict]:
    return [q for q in all_questions() if not q.get("answered_at")]


def answer(qid: str, choice: str, note: str = "") -> dict:
    p = QUESTIONS / f"{qid}.json"
    if not p.exists():
        return {"error": "no such question: %s" % qid}
    q = json.loads(p.read_text(encoding="utf-8"))
    q["answer"] = choice
    q["note"] = note
    q["answered_at"] = time.time()
    p.write_text(json.dumps(q, indent=2), encoding="utf-8")
    return q


def clear(job_id: str, kind: str = "") -> list[str]:
    """Drop questions for a job once whatever they asked about is settled."""
    gone = []
    pattern = f"*.{kind}.json" if kind else "*.json"
    for f in QUESTIONS.glob(pattern):
        try:
            q = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if q.get("job_id") == job_id:
            f.unlink()
            gone.append(f.stem)
    return gone


def render(qs: list[dict] | None = None) -> str:
    """The block the next run prints before it starts work."""
    qs = open_questions() if qs is None else qs
    if not qs:
        return ""
    lines = ["", "=" * 68,
             "%d question%s waiting for you" % (len(qs), "" if len(qs) == 1 else "s"),
             "=" * 68]
    for q in qs:
        days = (time.time() - float(q.get("asked_at") or 0)) / 86400
        age = "today" if days < 1 else "%d days ago" % int(days)
        lines.append("")
        lines.append("  %s" % q.get("title", q["id"]))
        lines.append("  job: %s   first asked %s   seen %d time(s)"
                     % (q.get("job_id", ""), age, q.get("asked_count") or 1))
        for line in (q.get("detail") or "").strip().splitlines():
            lines.append("    " + line)
        for i, opt in enumerate(q.get("options") or [], 1):
            lines.append("    %d. %s" % (i, opt))
    lines.append("")
    lines.append("=" * 68)
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(render() or "nothing waiting")
    elif len(sys.argv) > 3 and sys.argv[1] == "answer":
        print(json.dumps(answer(sys.argv[2], sys.argv[3],
                                " ".join(sys.argv[4:])), indent=2))
    else:
        print(__doc__)
        print("  python -m kiln.questions list")
        print("  python -m kiln.questions answer <id> <choice> [note]")
