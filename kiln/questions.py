"""Things a sync cannot decide on its own.

Syncs run twice a day and nobody is at the keyboard while they do, so a sync
cannot stop and ask me anything. When it hits a decision that is mine to
make, it writes the question down here and carries on with the rest of the
queue. Every sync prints the open questions before it does anything else,
and again at its end any that were raised or changed while it ran. The UI
shows them as cards I can answer by clicking.

One question per job per kind. Asking the same thing twice because the agent
was down for two syncs running is noise, not information.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config

QUESTIONS = config.DATA / "jobs" / "questions"
QUESTIONS.mkdir(parents=True, exist_ok=True)

# What every question is made of. A card that carries more, like the build
# queue's list of projects, puts it beside these and can never replace one.
# picked is here too because only an answer may set it.
_OWN = ("id", "job_id", "kind", "repo", "title", "detail", "options",
        "asked_at", "asked_count", "answered_at", "answer", "note", "picked")


def _path(job_id: str, kind: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in job_id)
    return QUESTIONS / f"{safe}.{kind}.json"


def ask(job_id: str, kind: str, title: str, detail: str,
        options: list[str] | None = None, repo: str = "",
        extra: dict | None = None) -> dict:
    """Record a question. Re-asking an open one refreshes its detail and extra.

    `extra` is stored at the top level of the question, for a card that needs
    more than words to be answered.
    """
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
            # choices off the card. Without this the second sync of the
            # same outage leaves me a question and no way to answer it.
            q["options"] = options or old.get("options") or []
            q["title"] = title or old.get("title") or ""
            if extra is None:
                extra = {k: v for k, v in old.items() if k not in _OWN}
    for k, v in (extra or {}).items():
        if k not in _OWN:
            q[k] = v
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


def answer(qid: str, choice: str, note: str = "",
           picked: list[str] | None = None) -> dict:
    """Record my answer. `picked` holds the ids I ticked, if the card had any."""
    p = QUESTIONS / f"{qid}.json"
    if not p.exists():
        return {"error": "no such question: %s" % qid}
    q = json.loads(p.read_text(encoding="utf-8"))
    q["answer"] = choice
    q["note"] = note
    # A lone id sent as text would otherwise be split into its letters.
    if isinstance(picked, str):
        picked = [picked]
    q["picked"] = [str(x) for x in picked or []]
    q["answered_at"] = time.time()
    p.write_text(json.dumps(q, indent=2), encoding="utf-8")
    return q


def pick_ids(qid: str, picks: list[str]) -> list[str]:
    """Turn what I typed after `some` into the ids a card with a list holds.

    A number is the one printed in brackets on the card, anything else is
    taken as an id. The UI sends ids; this is for answering from a terminal.
    """
    p = QUESTIONS / f"{qid}.json"
    try:
        listed = json.loads(p.read_text(encoding="utf-8")).get("projects") or []
    except Exception:
        listed = []
    by_n = {str(x.get("n")): str(x.get("job_id")) for x in listed if isinstance(x, dict)}
    return [by_n.get(s.strip("[],"), s.strip("[],")) for s in picks if s.strip("[],")]


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
    """The block a sync prints: at its start, and at its end for new ones."""
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
    elif len(sys.argv) > 4 and sys.argv[1] == "answer" and sys.argv[3] == "some":
        print(json.dumps(answer(sys.argv[2], "some",
                                picked=pick_ids(sys.argv[2], sys.argv[4:])), indent=2))
    elif len(sys.argv) > 3 and sys.argv[1] == "answer":
        print(json.dumps(answer(sys.argv[2], sys.argv[3],
                                " ".join(sys.argv[4:])), indent=2))
    else:
        print(__doc__)
        print("  python -m kiln.questions list")
        print("  python -m kiln.questions answer <id> <choice> [note]")
        print("  python -m kiln.questions answer <id> some <number or job id> ...")
