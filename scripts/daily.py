"""One command for the scheduled run: inbox, Claude, site, builds, publish, check.

    python scripts/daily.py data/inbox_snapshot.txt [--builds ask|yes|no]

It runs twice a day and every pass does the same six stages. The free
models read what is new, Claude finishes whatever they could not (the rule
is that this happens without asking), the site is rebuilt, and then the
build queue: builds are never started on a schedule any more. The queue is
offered as a card listing each project and roughly how long it takes, and
whatever I pick is built on the next pass.

Anything the run could not decide on its own is printed at the top, before
any work, because that is the moment I am actually reading the output.

Refuses to publish the site if the leak audit finds anything, and says so
loudly rather than pushing and hoping.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import brain, health, ingest, pipeline, questions, runner, store  # noqa: E402

# Three at once. Each is its own agent in its own directory, so they do not
# interfere, and a batch finishes in about the time one of them takes.
AT_ONCE = 3
STAGES = 6


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def is_morning() -> bool:
    return time.localtime().tm_hour < 12


def stage_inbox(text: str) -> tuple[int, int]:
    """Read the inbox and process what is new. Returns added and the total."""
    conn = store.connect()
    before = store.counts(conn)
    pending = ingest.new_items(text, conn)
    n_urls = sum(len(p.get("_new", p.get("urls")) or []) for p in pending)
    print(f"[1/{STAGES}] inbox: {len(pending)} new line(s), {n_urls} url(s)", flush=True)

    t0 = time.time()
    for r in ingest.ingest_text(text, source="gdoc", conn=conn):
        if r.get("status") == "processed":
            print("      %-56s %s" % ((r.get("url") or "")[:56],
                                      (r.get("title") or "")[:40]), flush=True)
    # A link that failed on a bad night gets a few more goes on later passes.
    for it in pipeline.retry_failed(conn):
        print("      retried %-48s %s" % ((it.get("url") or "")[:48],
                                          "failed again" if it.get("error")
                                          else (it.get("title") or "")[:40]), flush=True)
    after = store.counts(conn)
    conn.close()
    added = after["total"] - before["total"]
    print(f"      done in {time.time()-t0:.0f}s, {added} added", flush=True)
    return added, after["total"]


def stage_claude() -> dict:
    """Claude finishes what the free models could not. See kiln/brain.py."""
    t0 = time.time()
    print(f"[2/{STAGES}] claude: following up on what the free models left", flush=True)
    try:
        result = brain.sweep()
    except Exception as e:
        # brain.sweep is not meant to raise. If it does, the rest of the sync
        # still runs; the site and the queue do not depend on it.
        print(f"      failed: {type(e).__name__}: {e}")
        return {}
    print(brain.render(result), flush=True)
    print(f"      done in {time.time()-t0:.0f}s", flush=True)
    return result


def stage_site() -> tuple[bool, str]:
    """Rebuild the public site, audit it, and push if anything moved.

    This runs every pass rather than only when the inbox had something new.
    The site is a copy of the local page, so anything I change in the app
    is only live once this has run, and a site a day behind the app is the
    kind of drift nobody notices until it matters.
    """
    code, out = run([sys.executable, "-m", "kiln.publish"])
    print(f"[3/{STAGES}] site rebuilt, exit={code}")
    if code != 0:
        print(out[-1500:])
        return False, "publish failed"

    code, out = run([sys.executable, "scripts/audit_public.py"])
    last = out.strip().splitlines()[-1] if out.strip() else ""
    print(f"      leak audit exit={code}  {last}")
    if code != 0:
        print(out[-2000:])
        print("AUDIT FAILED - not pushing.")
        return False, "audit failed"

    # Only public/ goes out. It is the one folder the audit just checked, so
    # a stray log or half finished work elsewhere cannot ride along.
    run(["git", "add", "-A", "--", "public"])
    code, _ = run(["git", "diff", "--cached", "--quiet", "--", "public"])
    if code == 0:
        print("      site unchanged, nothing to push")
        return True, "unchanged"

    run(["git", "commit", "-m", "Update the published library", "--", "public"])
    code, out = run(["git", "push", "origin", "master"])
    print(f"      push exit={code}")
    if code != 0:
        print(out[-800:])
        return False, "push failed"
    print("      live site will update in about a minute")
    return True, "pushed"


def stage_builds(mode: str = "ask") -> list[dict]:
    """Build what I said yes to, then offer whatever is left.

    The answer is read before the offer is refreshed, so a card answered
    between passes is acted on rather than replaced by a fresh copy of
    itself.
    """
    code, out = run([sys.executable, "scripts/dedupe_jobs.py"])
    if "no duplicates" not in out:
        print("      " + out.strip().replace("\n", "\n      "))

    if mode == "no":
        print(f"[4/{STAGES}] queue: skipped (--builds no)")
        return []
    if mode == "yes":
        ids = [j.get("job_id") or Path(j["file"]).stem for j in runner.jobs.pending()]
        why = "building everything queued (--builds yes)"
    else:
        consent = runner.consented()
        ids = consent.get("job_ids") or []
        why = ("you picked %s" % consent.get("choice") if consent.get("answered")
               else "nobody has answered the queue card yet")
    print(f"[4/{STAGES}] queue: {len(ids)} to build now, {why}", flush=True)

    built = runner.run_consented(ids, at_once=AT_ONCE) if ids else []
    for b in built:
        print("      %-40s %-11s %s"
              % (str(b.get("repo", ""))[:40], b.get("state"),
                 b.get("blocked_reason") or b.get("directory", "")), flush=True)

    offer = runner.offer_queue(at_once=AT_ONCE)
    if offer and offer.get("answered_at"):
        # Answered while this pass was running. The next pass reads it.
        print("      the queue card was answered during this pass; the next one "
              "builds what it says", flush=True)
    elif offer:
        n = len(offer.get("projects") or [])
        print("      offered %d queued project%s, about %d min if all run; "
              "answer the card to build them"
              % (n, "" if n == 1 else "s", int(offer.get("total_min") or 0)), flush=True)
    return built


def stage_ship() -> list[dict]:
    waiting = runner.needs_ship()
    print(f"[5/{STAGES}] publish: {len(waiting)} project(s) ready for review", flush=True)
    if not waiting:
        return []

    shipped = runner.ship_done(limit=AT_ONCE)
    for s in shipped:
        if s.get("ok"):
            print("      %-40s published  %s"
                  % (str(s.get("repo", ""))[:40], s.get("url", "")), flush=True)
            print("      %-40s %s" % ("", runner.ci_line(s.get("ci") or {})), flush=True)
        else:
            print("      %-40s stopped at %s: %s"
                  % (str(s.get("repo", ""))[:40], s.get("stage"),
                     s.get("why")), flush=True)
    return shipped


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: daily.py <inbox text file> [--builds ask|yes|no]")
        return 2

    mode = "ask"
    for i, a in enumerate(sys.argv):
        if a == "--builds" and i + 1 < len(sys.argv):
            mode = sys.argv[i + 1]
    # "auto" was the old morning-only rule. It now means the same as ask.
    if mode not in ("ask", "yes", "no"):
        mode = "ask"

    # Before anything else. This is the one moment the output gets read.
    waiting = questions.open_questions()
    if waiting:
        print(questions.render(waiting))
    shown = {q["id"]: q.get("asked_count") for q in waiting}

    text = Path(sys.argv[1]).read_text(encoding="utf-8")

    try:
        added, total = stage_inbox(text)
    except Exception as e:
        print(f"[1/{STAGES}] inbox failed: {type(e).__name__}: {e}")
        added, total = 0, 0

    followed = stage_claude()
    ok, site = stage_site()
    built = stage_builds(mode)
    shipped = stage_ship()

    # Last, so it is checking the state this pass leaves behind rather than
    # the one it inherited. It reads the previous heartbeat before the new
    # one is written, which is how a skipped run gets noticed at all.
    found = health.check_all()
    print(f"[{STAGES}/{STAGES}] check: %d finding(s)" % len(found), flush=True)
    print(health.render(found), flush=True)
    health.raise_questions(found)
    health.beat("morning" if is_morning() else "evening", added)

    print("\n" + "-" * 60)
    print("items %d (+%d)   site %s" % (total, added, site))
    units = (followed or {}).get("units", []) + (followed or {}).get("reads", [])
    if units:
        worked = sum(1 for u in units if u.get("verdict") == "work" and u.get("state") == "done")
        print("claude followed up %d unit(s), did work on %d" % (len(units), worked))
    if built:
        done = sum(1 for b in built if b.get("state") == "done")
        print("built %d of %d attempted" % (done, len(built)))
    if shipped:
        live = [s for s in shipped if s.get("ok")]
        print("published %d of %d attempted" % (len(live), len(shipped)))
        for s in live:
            print("  %s  (%s)" % (s.get("url", ""),
                                  runner.ci_line(s.get("ci") or {}, with_url=False)))

    # The queue card, the unreadable-items card and the health cards are
    # mostly raised during the pass, after the block at the top was printed.
    # A card asked again with fresh detail counts as new too.
    still = questions.open_questions()
    fresh = [q for q in still if shown.get(q["id"]) != q.get("asked_count")]
    if fresh:
        print(questions.render(fresh))
    if still:
        where = []
        if len(still) > len(fresh):
            where.append("%d at the top of this output" % (len(still) - len(fresh)))
        if fresh:
            where.append("%d raised during this pass, just above" % len(fresh))
        print("\n%d question%s waiting for you: %s. Each is also a card in the "
              "Kiln UI." % (len(still), "" if len(still) == 1 else "s",
                            ", ".join(where)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
