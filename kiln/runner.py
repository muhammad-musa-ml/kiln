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

TIMEOUT = 3600

# Name, args after the executable, and whether the prompt goes on stdin.
# codex leads because gemini's CLI cannot reach its endpoint from here. stdin
# keeps a job body full of quotes and newlines off the command line.
AGENTS = [
    ("codex", ["exec", "--skip-git-repo-check", "-s", "workspace-write",
               "--color", "never", "-"], True),
    ("gemini", ["-p", "{prompt}", "--approval-mode", "yolo", "--skip-trust"], False),
]


def available_agents() -> list[str]:
    return [name for name, _, _ in AGENTS if shutil.which(name)]


def _safe_dir(name: str, directory: str = "") -> Path:
    """Resolve the build directory, refusing anything outside the workspace."""
    if directory:
        p = Path(directory).expanduser().resolve()
    else:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "build"
        p = (WORKSPACE / slug).resolve()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    root = WORKSPACE.resolve()
    # Compare path segments, not text. A plain prefix test lets a sibling
    # directory named kiln-builds-anything pass as if it were inside.
    if p != root and not p.is_relative_to(root):
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


def _stale(d: dict) -> bool:
    """A run past its own hard timeout cannot still be going.

    Without this a build killed mid-flight stays "running" forever, and
    run_pending skips that job every time it looks.
    """
    if d.get("state") != "running":
        return False
    return time.time() - float(d.get("started") or 0) > TIMEOUT + 120


def _settle(d: dict) -> dict:
    if _stale(d):
        return _write_state(d.get("job_id", ""), state="interrupted",
                            finished=time.time())
    return d


def reset(job_id: str = "") -> list[str]:
    """Clear stuck run state so a job can be started again."""
    out = []
    for f in sorted(RUNS.glob("*.json")):
        if job_id and not f.stem.startswith(job_id):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("state") == "running":
            _write_state(f.stem, state="interrupted", finished=time.time())
            out.append(f.stem)
    return out


def all_states() -> list[dict]:
    out = []
    for f in sorted(RUNS.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        d = _settle(d)
        log = Path(d.get("log", ""))
        if log.exists():
            try:
                size = log.stat().st_size
                # Seek rather than read the file in. A build log runs to
                # megabytes, and the UI asks for this on every poll.
                with log.open("rb") as fh:
                    fh.seek(max(0, size - 4000))
                    d["tail"] = fh.read().decode("utf-8", "replace")[-1800:]
                d["log_bytes"] = size
            except Exception:
                pass
        out.append(d)
    return out


def _kill_tree(p: subprocess.Popen) -> None:
    """Kill the agent, not just the shim that launched it.

    On Windows the CLI on PATH is a .CMD wrapper. Killing it leaves the real
    process running, which is how a timed out build keeps going unattended.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                       capture_output=True)
    else:
        p.kill()
    try:
        p.wait(timeout=30)
    except Exception:
        pass


def _execute(job_id: str, picked: str, repo: str, workdir: Path, log: Path,
             cmd: list[str], prompt: str, on_stdin: bool) -> dict:
    """Run the agent to completion and record what happened."""
    code = -1
    note = ""
    try:
        with log.open("wb") as fh:
            fh.write(f"$ {picked} (building {repo})\n".encode("utf-8"))
            fh.write(f"$ cwd: {workdir}\n\n".encode("utf-8"))
            fh.flush()
            p = subprocess.Popen(
                cmd, cwd=str(workdir),
                stdin=subprocess.PIPE if on_stdin else subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT)
            if on_stdin:
                try:
                    p.stdin.write(prompt.encode("utf-8"))
                finally:
                    p.stdin.close()
            try:
                code = p.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                _kill_tree(p)
                note = f"[timed out after {TIMEOUT // 60} minutes]"
    except Exception as e:
        note = f"[failed to start: {type(e).__name__}: {e}]"

    if note:
        with log.open("ab") as fh:
            fh.write(f"\n\n{note}\n".encode("utf-8"))

    files = sum(1 for f in workdir.rglob("*") if f.is_file())
    d = _write_state(job_id, state="done" if code == 0 else "failed",
                     exit_code=code, finished=time.time(), files_written=files)
    if code == 0:
        jobs.complete(job_id, f"built in {workdir} ({files} files)")
    return d


def start(job_file: str, *, directory: str = "", agent: str = "",
          wait: bool = False) -> dict:
    """Launch a build. With wait, run it through and return the final state."""
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
        return {"error": "no coding CLI found. Install one: npm i -g @openai/codex"}
    spec = {name: (args, on_stdin) for name, args, on_stdin in AGENTS}
    if picked not in spec:
        return {"error": f"unknown agent: {picked}"}
    args, on_stdin = spec[picked]

    # shutil.which honours PATHEXT and finds the .CMD wrapper. Spawning the
    # bare name does not, and fails with a file-not-found that reads as if
    # the CLI were missing entirely.
    exe = shutil.which(picked)
    if not exe:
        return {"error": f"{picked} is not on PATH"}

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
    cmd = [exe] + [a.replace("{prompt}", prompt) for a in args]

    state = _write_state(job_id, state="running", agent=picked, repo=repo,
                         directory=str(workdir), log=str(log),
                         started=time.time(), finished=0, exit_code=None,
                         files_written=0, job_file=str(jf))

    run_args = (job_id, picked, repo, workdir, log, cmd, prompt, on_stdin)
    if wait:
        return _execute(*run_args)
    # Deliberately not a daemon thread. A daemon dies when the interpreter
    # exits, which silently threw away every build started from the CLI.
    threading.Thread(target=_execute, args=run_args).start()
    return state


def run_pending(limit: int = 3) -> list[dict]:
    """Start anything queued. Used by the scheduled sync."""
    out = []
    for j in jobs.pending()[:limit]:
        st = _settle(read_state(j.get("job_id", "")))
        if st.get("state") in ("running", "done"):
            continue
        out.append(start(j["file"], wait=True))
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        for s in all_states():
            print("%-34s %-11s %s" % (s.get("job_id", "")[:34], s.get("state"),
                                      s.get("directory", "")))
            if s.get("tail"):
                print("   " + s["tail"].strip().splitlines()[-1][:100])
    elif len(sys.argv) > 1 and sys.argv[1] == "pending":
        started = run_pending()
        print(json.dumps(started, indent=2, default=str)[:2000] if started
              else "nothing queued")
    elif len(sys.argv) > 1 and sys.argv[1] == "reset":
        cleared = reset(sys.argv[2] if len(sys.argv) > 2 else "")
        print("cleared: " + (", ".join(cleared) if cleared else "nothing stuck"))
    elif len(sys.argv) > 2 and sys.argv[1] == "run":
        print(json.dumps(start(sys.argv[2], wait=True), indent=2, default=str))
    else:
        print(__doc__)
        print("agents available:", available_agents() or "none")
        print("workspace:", WORKSPACE)
        print("\n  python -m kiln.runner pending")
        print("  python -m kiln.runner run <job file>")
        print("  python -m kiln.runner status")
        print("  python -m kiln.runner reset [job id]")
