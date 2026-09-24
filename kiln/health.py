"""Check the run actually did what it says it did.

Everything in here is something I found by hand, once, by reading the
database and going "that number is wrong". A reel that failed and left an
untitled row. A site that said ten items while the database held twelve. A
job sitting in the queue under two names. None of it raised anything at the
time, because nothing was looking.

The run looks now, every time, and prints what it finds before anything
else. Findings that need me to decide something become questions; the rest
are printed and left alone, because a warning I see every morning and never
act on is just noise with extra steps.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, jobs, questions, runner, store

HEARTBEAT = config.DATA / "last_run.json"

# A pass happens twice a day. Eighteen hours means one did not.
MISSED_AFTER = 18 * 3600
# How long something can sit in the inbox before it is worth asking about.
STUCK_AFTER = 7 * 86400


def _finding(level: str, what: str, detail: str = "", fix: str = "") -> dict:
    return {"level": level, "what": what, "detail": detail, "fix": fix}


def beat(mode: str, added: int) -> None:
    """Leave a mark saying this pass got to the end."""
    try:
        HEARTBEAT.write_text(json.dumps(
            {"at": time.time(), "mode": mode, "added": added}, indent=2),
            encoding="utf-8")
    except Exception:
        pass


def last_beat() -> dict:
    try:
        return json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_last_run() -> list[dict]:
    """Did the previous pass finish, and was it when it should have been?"""
    beat_ = last_beat()
    if not beat_:
        return [_finding("info", "no record of a previous run",
                         "This is either the first pass since the check went "
                         "in, or the heartbeat was lost.")]
    gap = time.time() - float(beat_.get("at") or 0)
    if gap > MISSED_AFTER:
        return [_finding(
            "ask", "a scheduled run did not happen",
            "The last pass that finished was %.1f hours ago, and they are "
            "meant to be twelve apart. Either a run was skipped or one "
            "started and died part way through."
            % (gap / 3600),
            "Check the routine's run history in the app.")]
    return []


def check_site_matches_db(conn) -> list[dict]:
    """The published site should hold exactly what the database holds."""
    out = []
    items_file = config.ROOT / "public" / "data" / "items.json"
    if not items_file.exists():
        return [_finding("warn", "the site has never been built",
                         str(items_file))]
    try:
        published = len(json.loads(
            items_file.read_text(encoding="utf-8")).get("items") or [])
    except Exception as e:
        return [_finding("warn", "the published item list will not parse",
                         "%s: %s" % (type(e).__name__, e))]

    held = store.counts(conn)["total"]
    if published != held:
        out.append(_finding(
            "warn", "the site and the database disagree",
            "the database holds %d items, the published site shows %d"
            % (held, published),
            "python -m kiln.publish"))
    return out


def check_items(conn) -> list[dict]:
    """Rows that are in the library but not really usable."""
    out = []
    untitled, untagged, stuck, errored, redo = [], [], [], [], []
    now = time.time()

    for row in conn.execute(
            "SELECT id, url, title, status, error, created_at FROM items"):
        d = dict(row)
        tags = store.facets_for(conn, d["id"]).get("action") or []
        if not (d.get("title") or "").strip():
            untitled.append(d["url"])
        if not tags:
            untagged.append(d["url"])
        if "redo" in tags:
            redo.append(d["url"])
        if d.get("error"):
            errored.append("%s  %s" % (d["url"][:54], (d["error"] or "")[:60]))
        if (d.get("status") == "inbox"
                and now - float(d.get("created_at") or now) > STUCK_AFTER):
            stuck.append(d["url"])

    if untitled:
        out.append(_finding("warn", "%d item(s) with no title" % len(untitled),
                            "\n".join(untitled[:5]),
                            "these show as blank rows and no filter finds them"))
    if untagged:
        out.append(_finding("warn", "%d item(s) with no action tag" % len(untagged),
                            "\n".join(untagged[:5])))
    if redo:
        out.append(_finding("info", "%d link(s) tagged redo" % len(redo),
                            "\n".join(redo[:5]),
                            "they could not be read; re-fire when you want"))
    if errored:
        out.append(_finding("info", "%d item(s) carry an error" % len(errored),
                            "\n".join(errored[:5])))
    if stuck:
        out.append(_finding(
            "ask", "%d item(s) stuck in the inbox for over a week" % len(stuck),
            "\n".join(stuck[:5]),
            "re-fire them, or drop them"))
    return out


def check_jobs() -> list[dict]:
    """The build queue, and anything built that never went anywhere."""
    out = []
    by_item: dict[str, list] = {}
    for j in jobs.all_jobs():
        key = j.get("item_id") or j.get("repo_name") or j["name"]
        by_item.setdefault(key, []).append(j["name"])
    dupes = {k: v for k, v in by_item.items() if len(v) > 1}
    if dupes:
        out.append(_finding(
            "warn", "%d project(s) queued more than once" % len(dupes),
            "\n".join("%s: %s" % (k, ", ".join(v)) for k, v in list(dupes.items())[:4]),
            "python scripts/dedupe_jobs.py"))

    waiting = runner.needs_ship()
    old = [d for d in waiting
           if time.time() - float(d.get("finished") or 0) > 86400]
    if old:
        out.append(_finding(
            "warn", "%d build(s) finished over a day ago and are not published"
            % len(old),
            "\n".join(str(d.get("repo") or d.get("job_id")) for d in old[:5]),
            "python -m kiln.runner ship"))

    blocked = [d for d in runner.all_states()
               if d.get("state") == "blocked"]
    if blocked:
        out.append(_finding(
            "info", "%d build(s) waiting on an agent" % len(blocked),
            "\n".join("%s: %s" % (d.get("repo"), d.get("blocked_reason"))
                      for d in blocked[:5])))
    return out


def check_all(conn=None) -> list[dict]:
    own = conn is None
    conn = conn or store.connect()
    try:
        found = (check_last_run()
                 + check_site_matches_db(conn)
                 + check_items(conn)
                 + check_jobs())
    finally:
        if own:
            conn.close()
    return found


def render(found: list[dict]) -> str:
    if not found:
        return "      nothing out of place"
    order = {"ask": 0, "warn": 1, "info": 2}
    lines = []
    for f in sorted(found, key=lambda x: order.get(x["level"], 9)):
        lines.append("      [%s] %s" % (f["level"], f["what"]))
        for line in (f.get("detail") or "").splitlines():
            lines.append("            " + line[:96])
        if f.get("fix"):
            lines.append("            -> " + f["fix"])
    return "\n".join(lines)


def raise_questions(found: list[dict]) -> int:
    """Anything needing a decision becomes a card, the rest stays printed."""
    asked = 0
    for f in found:
        if f["level"] != "ask":
            continue
        key = "health-" + "".join(c if c.isalnum() else "-"
                                  for c in f["what"])[:40]
        questions.ask(key, "health", f["what"],
                      (f.get("detail") or "") + (
                          "\n" + f["fix"] if f.get("fix") else ""),
                      ["looked - I have dealt with it",
                       "ignore - stop telling me about this one"])
        asked += 1
    return asked


if __name__ == "__main__":
    f = check_all()
    print(render(f))
    print("\n%d finding(s)" % len(f))
