"""Find job files that describe the same project and keep only one.

Two things can put a second copy of a project in the queue. The job id scheme
changed once, so the old clock based name and the new item based name do not
match each other. And before the dedup check keyed on the item, pressing the
button on a project that was already built wrote a fresh file.

Nothing is deleted. Losers move to data/jobs/duplicates/ so that if this
picks wrong I can still see what it did and put it back.

    python scripts/dedupe_jobs.py            move duplicates aside
    python scripts/dedupe_jobs.py --dry-run  say what it would do
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import jobs, runner  # noqa: E402

ASIDE = jobs.JOBS_DIR / "duplicates"


def rank(job: dict) -> tuple:
    """Higher is better. A job that actually built beats one that has not."""
    state = runner.read_state(job.get("job_id") or Path(job["file"]).stem)
    built = 1 if state.get("state") == "done" else 0
    done = 1 if job.get("job_state") == "done" else 0
    files = int(state.get("files_written") or 0)
    return (built, done, files, job.get("created", ""))


def groups() -> dict:
    """Job files grouped by the item they came from."""
    out: dict[str, list] = {}
    for j in jobs.all_jobs():
        key = j.get("item_id") or j.get("repo_name") or Path(j["file"]).stem
        out.setdefault(key, []).append(j)
    return out


def main(dry: bool = False) -> int:
    moved = []
    for key, group in sorted(groups().items()):
        if len(group) < 2:
            continue
        group.sort(key=rank, reverse=True)
        keep, rest = group[0], group[1:]
        print("item %s has %d copies" % (key, len(group)))
        print("  keep %-52s (%s)" % (Path(keep["file"]).name, keep["job_state"]))
        for j in rest:
            src = Path(j["file"])
            print("  drop %-52s (%s)" % (src.name, j["job_state"]))
            if dry:
                continue
            ASIDE.mkdir(parents=True, exist_ok=True)
            dest = ASIDE / src.name
            # Keep both if the name is taken rather than overwriting a file
            # that an earlier run already set aside.
            n = 1
            while dest.exists():
                dest = ASIDE / ("%s.%d%s" % (src.stem, n, src.suffix))
                n += 1
            shutil.move(str(src), str(dest))
            moved.append(str(dest))

    if not moved and not dry:
        print("no duplicates")
    elif moved:
        print("\nmoved %d file(s) to %s" % (len(moved), ASIDE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--dry-run" in sys.argv))
