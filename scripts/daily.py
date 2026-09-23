"""One command for the scheduled run: ingest, publish, audit, push.

    python scripts/daily.py data/inbox_snapshot.txt

Refuses to publish if the leak audit finds anything, and says so loudly
rather than pushing and hoping.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import ingest, store  # noqa: E402


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: daily.py <inbox text file>")
        return 2
    text = Path(sys.argv[1]).read_text(encoding="utf-8")

    conn = store.connect()
    before = store.counts(conn)
    pending = ingest.new_items(text, conn)
    n_urls = sum(len(p.get("urls") or []) for p in pending)
    print(f"[1/4] inbox: {len(pending)} new line(s), {n_urls} url(s)", flush=True)

    t0 = time.time()
    processed = 0
    for r in ingest.ingest_text(text, source="gdoc", conn=conn):
        if r.get("status") == "processed":
            processed += 1
            print("      %-56s %s" % ((r.get("url") or "")[:56],
                                      (r.get("title") or "")[:40]), flush=True)
    after = store.counts(conn)
    conn.close()
    print(f"      done in {time.time()-t0:.0f}s, "
          f"{after['total']-before['total']} added, "
          f"spend ${after['spend']:.4f} total", flush=True)

    if after["total"] == before["total"]:
        print("[2/4] nothing new, stopping before publish")
        return 0

    code, out = run([sys.executable, "-m", "kiln.publish"])
    print(f"[2/4] publish exit={code}")
    if code != 0:
        print(out[-1500:])
        return 1

    code, out = run([sys.executable, "scripts/audit_public.py"])
    print(f"[3/4] audit exit={code}")
    print("      " + out.strip().splitlines()[-1] if out.strip() else "")
    if code != 0:
        print(out[-2000:])
        print("AUDIT FAILED - not pushing.")
        return 1

    # Only public/ goes out. It's the one folder the audit just checked, so a
    # stray log or half-finished work elsewhere can't ride along to GitHub.
    run(["git", "add", "-A", "--", "public"])
    code, _ = run(["git", "diff", "--cached", "--quiet", "--", "public"])
    if code == 0:
        print("[4/4] nothing to commit")
        return 0
    run(["git", "commit", "-m",
         f"Add {after['total']-before['total']} item(s) from the inbox",
         "--", "public"])
    code, out = run(["git", "push", "origin", "master"])
    print(f"[4/4] push exit={code}")
    if code != 0:
        print(out[-800:])
        return 1
    print("live site will update in about a minute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
