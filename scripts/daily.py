"""One command for the scheduled run: inbox, site, builds, publish.

    python scripts/daily.py data/inbox_snapshot.txt

It runs twice a day. The inbox and the site are done on both passes. Builds
and the review chain are morning work only, because three agents at up to an
hour each, plus the review and readme pass on each of them, is not something
to start at nine at night.

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

from kiln import ingest, questions, runner, store  # noqa: E402

# Three at once. Each is its own agent in its own directory, so they do not
# interfere, and the morning finishes in about the time one of them takes.
AT_ONCE = 3


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def is_morning() -> bool:
    return time.localtime().tm_hour < 12


def stage_inbox(text: str) -> tuple[int, int, float]:
    """Read the inbox and process what is new. Returns added, total, estimate."""
    conn = store.connect()
    before = store.counts(conn)
    pending = ingest.new_items(text, conn)
    n_urls = sum(len(p.get("urls") or []) for p in pending)
    print(f"[1/4] inbox: {len(pending)} new line(s), {n_urls} url(s)", flush=True)

    t0 = time.time()
    for r in ingest.ingest_text(text, source="gdoc", conn=conn):
        if r.get("status") == "processed":
            print("      %-56s %s" % ((r.get("url") or "")[:56],
                                      (r.get("title") or "")[:40]), flush=True)
    after = store.counts(conn)
    conn.close()
    added = after["total"] - before["total"]
    print(f"      done in {time.time()-t0:.0f}s, {added} added, "
          f"est ${after['spend']:.4f} at paid rates", flush=True)
    return added, after["total"], after["spend"]


def stage_site() -> tuple[bool, str]:
    """Rebuild the public site, audit it, and push if anything moved.

    This runs every pass rather than only when the inbox had something new.
    The site is a copy of the local page, so anything I change in the app
    is only live once this has run, and a site a day behind the app is the
    kind of drift nobody notices until it matters.
    """
    code, out = run([sys.executable, "-m", "kiln.publish"])
    print(f"[2/4] site rebuilt, exit={code}")
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


def stage_builds() -> list[dict]:
    code, out = run([sys.executable, "scripts/dedupe_jobs.py"])
    if "no duplicates" not in out:
        print("      " + out.strip().replace("\n", "\n      "))

    waiting = len(runner.jobs.pending())
    print(f"[3/4] queue: {waiting} job(s) waiting, running up to {AT_ONCE} at once",
          flush=True)
    if not waiting:
        return []

    built = runner.run_pending(limit=AT_ONCE)
    for b in built:
        print("      %-40s %-11s %s"
              % (str(b.get("repo", ""))[:40], b.get("state"),
                 b.get("blocked_reason") or b.get("directory", "")), flush=True)
    return built


def stage_ship() -> list[dict]:
    waiting = runner.needs_ship()
    print(f"[4/4] publish: {len(waiting)} project(s) ready for review", flush=True)
    if not waiting:
        return []

    shipped = runner.ship_done(limit=AT_ONCE)
    for s in shipped:
        if s.get("ok"):
            print("      %-40s published  %s"
                  % (str(s.get("repo", ""))[:40], s.get("url", "")), flush=True)
        else:
            print("      %-40s stopped at %s: %s"
                  % (str(s.get("repo", ""))[:40], s.get("stage"),
                     s.get("why")), flush=True)
    return shipped


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: daily.py <inbox text file> [--builds auto|yes|no]")
        return 2

    mode = "auto"
    for i, a in enumerate(sys.argv):
        if a == "--builds" and i + 1 < len(sys.argv):
            mode = sys.argv[i + 1]
    do_builds = mode == "yes" or (mode == "auto" and is_morning())

    # Before anything else. This is the one moment the output gets read.
    waiting = questions.open_questions()
    if waiting:
        print(questions.render(waiting))

    text = Path(sys.argv[1]).read_text(encoding="utf-8")

    try:
        added, total, spend = stage_inbox(text)
    except Exception as e:
        print(f"[1/4] inbox failed: {type(e).__name__}: {e}")
        added, total, spend = 0, 0, 0.0

    ok, site = stage_site()

    built, shipped = [], []
    if do_builds:
        built = stage_builds()
        shipped = stage_ship()
    else:
        pending = len(runner.jobs.pending())
        ready = len(runner.needs_ship())
        print(f"[3/4] queue: {pending} waiting, builds are morning only")
        print(f"[4/4] publish: {ready} ready, held for the morning run")

    print("\n" + "-" * 60)
    print("items %d (+%d)   est $%.4f at paid rates   site %s"
          % (total, added, spend, site))
    if built:
        done = sum(1 for b in built if b.get("state") == "done")
        print("built %d of %d attempted" % (done, len(built)))
    if shipped:
        live = [s for s in shipped if s.get("ok")]
        print("published %d of %d attempted" % (len(live), len(shipped)))
        for s in live:
            print("  %s" % s.get("url", ""))

    still = questions.open_questions()
    if still:
        print("\n%d question%s waiting for you - see the top of this output,"
              % (len(still), "" if len(still) == 1 else "s"))
        print("or the cards in the Kiln UI.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
