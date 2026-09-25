"""Work no model could do, written down for Claude to pick up.

The rule is that a fallback must not be worse than what it replaces. When
every rung in a ladder is out of quota or comes back below standard, the old
behaviour was to keep dropping until something answered, and the thing that
answered produced a read with no sections, no on-screen text and no links,
which was then filed as if it were fine.

Running out of models is allowed. Filing a bad read is not. So the item
stops here and a handoff is written instead: what was being read, where the
media is, what the owner asked for, and the exact shape the answer has to
take. The next sync asks me on a card whether Claude should read these, and
on a yes the follow-up (brain.py) does the read itself, which is the one
fallback that is not a downgrade. A later read by a free model that works
clears the brief on its own.

    python -m kiln.handoff list          what is waiting
    python -m kiln.handoff show <id>     the brief for one item
    python -m kiln.handoff fill <id> <file.json>    hand the answer back
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config

PENDING = config.DATA / "handoff"
PENDING.mkdir(parents=True, exist_ok=True)


def _path(item_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in item_id)
    return PENDING / f"{safe}.json"


def write(item_id: str, *, url: str, stage: str, why: str,
          media: list[str] | None = None, instruction: str = "",
          schema: str = "", context: str = "", tried: list[str] | None = None) -> dict:
    """Record that this item needs a person, or Claude, rather than a model."""
    brief = {
        "item_id": item_id,
        "url": url,
        "stage": stage,                 # extract | enrich | artifact
        "why": why,
        "media": media or [],
        "instruction": instruction,
        "schema": schema,
        "context": context[:4000],
        "models_tried": tried or [],
        "asked_at": time.time(),
        "done_at": 0,
    }
    _path(item_id).write_text(json.dumps(brief, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    return brief


def pending() -> list[dict]:
    out = []
    for f in sorted(PENDING.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not d.get("done_at"):
            out.append(d)
    return out


def clear(item_id: str) -> bool:
    p = _path(item_id)
    if p.exists():
        p.unlink()
        return True
    return False


def fill(item_id: str, note: dict) -> dict:
    """Store an answer Claude produced, as if a model had returned it.

    The note goes through the same pipeline stage the model's would have, so
    nothing downstream needs to know a person did it. What does get recorded
    is that it happened, because a read done by hand and a read done by a
    model are not the same evidence and the difference should be visible.
    """
    from . import pipeline, store

    p = _path(item_id)
    if not p.exists():
        return {"error": f"no handoff waiting for {item_id}"}
    brief = json.loads(p.read_text(encoding="utf-8"))

    meta = note.setdefault("_meta", {})
    meta["by"] = "claude"
    meta["why"] = brief.get("why", "")
    meta["passes"] = meta.get("passes") or [{"model": "claude", "ok": True}]

    conn = store.connect()
    try:
        item = store.get_item(conn, item_id)
        if not item:
            return {"error": f"no item {item_id}"}
        rec = {"id": item_id, "url": item["url"], "error": "",
               "title": note.get("title") or item.get("title") or item["url"],
               "hook": note.get("hook", ""), "summary": note.get("summary", ""),
               "kind": note.get("kind") or item.get("kind") or "other",
               "note_json": json.dumps(note, ensure_ascii=False),
               "status": "triage", "processed_at": time.time()}
        store.upsert_item(conn, rec)

        action = pipeline.derive_action(note, item.get("user_do", ""),
                                        media_kind=item.get("kind", ""))
        store.set_tags(conn, item_id, "action", [action])
        store.set_tags(conn, item_id, "topic",
                       pipeline.normalise_topics(note.get("topics") or []))
        conn.commit()
    finally:
        conn.close()

    brief["done_at"] = time.time()
    p.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "item_id": item_id, "action": action,
            "sections": len(note.get("sections") or [])}


def render(briefs: list[dict] | None = None) -> str:
    """The block the run prints so the work is not invisible."""
    briefs = pending() if briefs is None else briefs
    if not briefs:
        return ""
    lines = ["", "=" * 68,
             "%d item%s no model could read" % (len(briefs),
                                                "" if len(briefs) == 1 else "s"),
             "=" * 68]
    for b in briefs:
        lines.append("")
        lines.append("  %s" % b.get("url", b["item_id"]))
        lines.append("  stage: %s   %s" % (b.get("stage"), b.get("why", "")))
        if b.get("instruction"):
            lines.append("  asked: %s" % b["instruction"][:200])
        if b.get("media"):
            lines.append("  media: %d file(s) under %s"
                         % (len(b["media"]), Path(b["media"][0]).parent))
        if b.get("models_tried"):
            lines.append("  tried: %s" % ", ".join(b["models_tried"][:6]))
        lines.append("  brief: python -m kiln.handoff show %s" % b["item_id"])
    lines += ["", "=" * 68, ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(render() or "nothing waiting")
    elif len(sys.argv) > 2 and sys.argv[1] == "show":
        p = _path(sys.argv[2])
        print(p.read_text(encoding="utf-8") if p.exists()
              else f"no handoff for {sys.argv[2]}")
    elif len(sys.argv) > 3 and sys.argv[1] == "fill":
        data = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        print(json.dumps(fill(sys.argv[2], data), indent=2))
    else:
        print(__doc__)
