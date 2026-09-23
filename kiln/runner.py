"""Actually run a build job.

Until now "Run here now" only wrote a file and said a local agent would pick
it up. Nothing picked it up, because nothing existed to. This is that thing.

It shells out to a coding CLI in a directory you choose, streams the output
to a log, and records state next to the job so the UI can show progress.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import config, jobs

RUNS = config.DATA / "jobs" / "runs"
RUNS.mkdir(parents=True, exist_ok=True)

# Where a build is allowed to write. Anything outside is refused, so a bad
# directory in a job file cannot drop a repo in the middle of the system.
WORKSPACE = Path(os.environ.get("KILN_WORKSPACE", Path.home() / "kiln-builds"))

AGENTS = [
    ("gemini", ["gemini", "-p", "{prompt}", "--approval-mode", "auto_edit"]),
    ("codex", ["codex", "exec", "{prompt}"]),
]


def available_agents() -> list[str]:
    return [name for name, _ in AGENTS if shutil.which(name)]


def _safe_dir(name: str, directory: str = "") -> Path:
    """Resolve the build directory, refusing anything outside the workspace."""
    if directory:
        p = Path(directory).expanduser().resolve()
    else:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "build"
        p = (WORKSPACE / slug).resolve()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    root = WORKSPACE.resolve()
    if not str(p).startswith(str(root)):
        raise ValueError(f"build directory must sit under {root}")
    return p


def _state_path(job_id: str) -> Path:
    return RUNS / f"{job_id}.json"


def _write_state(job_id: str, **kw) -> dict:
    p = _state_path(job_id)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        d = {"job_id": job_id}
    d.update(kw)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d


def read_state(job_id: str) -> dict:
    try:
        return json.loads(_state_path(job_id).read_text(encoding="utf-8"))
    except Exception:
        return {}


def all_states() -> list[dict]:
    out = []
    for f in sorted(RUNS.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        log = Path(d.get("log", ""))
        if log.exists():
            try:
                tail = log.read_text(encoding="utf-8", errors="replace")[-1800:]
                d["tail"] = tail
                d["log_bytes"] = log.stat().st_size
            except Exception:
                pass
        out.append(d)
    return out


def start(job_file: str, *, directory: str = "", agent: str = "") -> dict:
    """Launch a build in the background. Returns the initial state."""
    jf = Path(job_file)
    if not jf.exists():
        return {"error": f"no such job: {job_file}"}

    text = jf.read_text(encoding="utf-8")
    head: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        _, front, body = text.split("---", 2)
        for line in front.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                head[k.strip()] = v.strip()
    job_id = head.get("job_id") or jf.stem
    repo = head.get("repo_name") or "build"

    picked = agent or (available_agents()[0] if available_agents() else "")
    if not picked:
        return {"error": "no coding CLI found. Install one: npm i -g @google/gemini-cli"}
    cmd_tpl = dict(AGENTS)[picked]

    try:
        workdir = _safe_dir(repo, directory or head.get("directory", ""))
    except ValueError as e:
        return {"error": str(e)}
    workdir.mkdir(parents=True, exist_ok=True)

    prompt = body.strip()
    # The agent works in the directory, so tell it where it already is.
    prompt += (f"\n\nWork in the current directory. It is empty and yours. "
               f"Create the project here, then stop.")

    log = RUNS / f"{job_id}.log"
    cmd = [c.replace("{prompt}", prompt) for c in cmd_tpl]

    state = _write_state(job_id, state="running", agent=picked, repo=repo,
                         directory=str(workdir), log=str(log),
                         started=time.time(), finished=0, exit_code=None,
                         job_file=str(jf))

    def run():
        try:
            with log.open("w", encoding="utf-8", errors="replace") as fh:
                fh.write(f"$ {picked} (building {repo})\n")
                fh.write(f"$ cwd: {workdir}\n\n")
                fh.flush()
                p = subprocess.run(cmd, cwd=str(workdir), stdout=fh,
                                   stderr=subprocess.STDOUT, text=True,
                                   timeout=3600)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = -1
            log.open("a", encoding="utf-8").write("\n\n[timed out after 60 minutes]\n")
        except Exception as e:
            code = -1
            log.open("a", encoding="utf-8").write(f"\n\n[failed to start: {e}]\n")

        files = sum(1 for _ in workdir.rglob("*") if _.is_file())
        _write_state(job_id, state="done" if code == 0 else "failed",
                     exit_code=code, finished=time.time(), files_written=files)
        if code == 0:
            jobs.complete(job_id, f"built in {workdir} ({files} files)")

    threading.Thread(target=run, daemon=True).start()
    return state


def run_pending(limit: int = 3) -> list[dict]:
    """Start anything queued. Used by the scheduled sync."""
    out = []
    for j in jobs.pending()[:limit]:
        if read_state(j.get("job_id", "")).get("state") in ("running", "done"):
            continue
        out.append(start(j["file"]))
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        for s in all_states():
            print("%-34s %-8s %s" % (s.get("job_id", "")[:34], s.get("state"),
                                     s.get("directory", "")))
            if s.get("tail"):
                print("   " + s["tail"].strip().splitlines()[-1][:100])
    elif len(sys.argv) > 1 and sys.argv[1] == "pending":
        started = run_pending()
        print(json.dumps(started, indent=2, default=str)[:2000] if started
              else "nothing queued")
    elif len(sys.argv) > 2 and sys.argv[1] == "run":
        print(json.dumps(start(sys.argv[2]), indent=2, default=str))
    else:
        print(__doc__)
        print("agents available:", available_agents() or "none")
        print("workspace:", WORKSPACE)
        print("\n  python -m kiln.runner pending")
        print("  python -m kiln.runner run <job file>")
        print("  python -m kiln.runner status")
