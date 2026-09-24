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

from . import config, jobs, questions, ship

RUNS = config.DATA / "jobs" / "runs"
RUNS.mkdir(parents=True, exist_ok=True)

# How many real failures before it stops retrying quietly and asks me what
# to do. Two, because one failure is often the model having a bad night and
# three mornings of the same crash is three wasted hours.
FAIL_LIMIT = 2

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
    # Never picked automatically. It is only reached when codex was down and
    # I answered the question saying to build that job with claude instead.
    ("claude", ["-p", "--permission-mode", "acceptEdits",
                "--permission-prompts", "none", "--output-format", "text",
                "--allowedTools", "Read", "Grep", "Glob", "Edit", "Write",
                "Bash(python *)", "Bash(py *)", "Bash(pytest *)",
                "Bash(pip *)", "Bash(ls*)", "Bash(dir*)", "Bash(cat*)",
                "Bash(mkdir*)"], True),
]

# The order agents are tried in when nothing has been chosen. claude sits
# outside it so a job never quietly costs Claude tokens without me saying so.
AUTO = ("codex", "gemini")


def available_agents() -> list[str]:
    return [name for name, _, _ in AGENTS if name in AUTO and shutil.which(name)]


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
    if code == 0:
        d = _write_state(job_id, state="done", exit_code=code,
                         finished=time.time(), files_written=files)
        jobs.complete(job_id, f"built in {workdir} ({files} files)")
        # Whatever it was stuck on before, it is not stuck on it now.
        questions.clear(job_id)
        return d
    return _failed(job_id, repo, picked, log, code, files)


def _tail(log: Path, n: int = 4000) -> str:
    try:
        size = log.stat().st_size
        with log.open("rb") as fh:
            fh.seek(max(0, size - n))
            return fh.read().decode("utf-8", "replace")
    except Exception:
        return ""


def _failed(job_id: str, repo: str, picked: str, log: Path, code: int,
            files: int) -> dict:
    """Work out whether the agent was down or the build is genuinely bad.

    These want opposite things. An agent that was unavailable should be
    tried again tomorrow and is not the project's fault, so it never counts
    against the retry limit. A build that runs and breaks is mine to look at.
    """
    tail = _tail(log)
    blocked = ship.agent_blocked(tail)
    now = time.time()

    if blocked:
        d = _write_state(job_id, state="blocked", exit_code=code,
                         finished=now, files_written=files,
                         blocked_reason=blocked, blocked_agent=picked)
        questions.ask(
            job_id, "agent_down", repo=repo,
            title="%s could not run %s (%s)" % (picked, repo, blocked),
            detail=("The build did not start properly, so this is not the "
                    "project failing. It is still queued and will be tried "
                    "again on the next morning run.\n"
                    "Last output:\n  %s" % tail.strip()[-400:]),
            options=["wait - leave it queued for the next 9am run",
                     "claude - build it with claude on this machine",
                     "claude cloud - build it in a cloud session"])
        return d

    attempts = int(read_state(job_id).get("attempts") or 0) + 1
    d = _write_state(job_id, state="failed", exit_code=code, finished=now,
                     files_written=files, attempts=attempts)
    if attempts >= FAIL_LIMIT:
        questions.ask(
            job_id, "build_failed", repo=repo,
            title="%s has failed %d times" % (repo, attempts),
            detail=("The agent ran and the build came out broken, so trying "
                    "it again unchanged will not help.\n"
                    "Exit code %s. Last output:\n  %s"
                    % (code, tail.strip()[-600:])),
            options=["skip - stop trying this one",
                     "retry - I have fixed something, try again",
                     "claude - hand it to claude instead"])
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


def _already_built(item_id: str, this_job: str) -> str:
    """Another job for the same item that has already been built, if any."""
    if not item_id:
        return ""
    for j in jobs.all_jobs():
        jid = j.get("job_id") or Path(j["file"]).stem
        if jid == this_job or j.get("item_id") != item_id:
            continue
        if read_state(jid).get("state") == "done":
            return jid
    return ""


def _chosen_agent(job_id: str) -> str:
    """Where an answered question says this job should go."""
    for q in questions.all_questions():
        if q.get("job_id") != job_id or not q.get("answered_at"):
            continue
        answer = (q.get("answer") or "").strip().lower()
        if answer.startswith("skip"):
            return "skip"
        if "claude" in answer:
            return "claude"
    return ""


def _verdict(job_id: str, kind: str) -> str:
    """open if it is still waiting on me, skip, go, or nothing was asked."""
    for q in questions.all_questions():
        if q.get("job_id") != job_id or q.get("kind") != kind:
            continue
        if not q.get("answered_at"):
            return "open"
        answer = (q.get("answer") or "").strip().lower()
        return "skip" if answer.startswith("skip") else "go"
    return ""


def run_pending(limit: int = 3) -> list[dict]:
    """Build everything queued, up to `limit` of them at once.

    They run together rather than one after another. Each is a separate agent
    in its own directory with nothing to fight over, so three at a time turns
    a three hour morning into a one hour one.

    The cap is applied after the skipping, not before. Slicing the queue
    first means three finished jobs at the front hide everything behind them.
    """
    chosen: list[tuple] = []
    for j in jobs.pending():
        jid = j.get("job_id") or Path(j["file"]).stem
        st = _settle(read_state(jid))
        if st.get("state") in ("running", "done"):
            continue
        agent = _chosen_agent(jid)
        if agent == "skip":
            continue
        if _verdict(jid, "build_failed") == "open":
            # It ran and broke, and I have not said what to do about it.
            # Running the same thing again costs an hour and learns nothing.
            continue
        if _already_built(j.get("item_id", ""), jid):
            # Same project under an older job id. Building it again drops a
            # second agent into a directory that already holds a finished
            # project, and it comes out worse than either.
            continue
        chosen.append((j, agent))
        if len(chosen) >= limit:
            break

    results: list[dict] = []
    lock = threading.Lock()

    def one(job: dict, agent: str) -> None:
        d = start(job["file"], wait=True, agent=agent)
        with lock:
            results.append(d)

    threads = [threading.Thread(target=one, args=(j, a)) for j, a in chosen]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def needs_ship() -> list[dict]:
    """Builds that finished and have not been through the review chain.

    The whole run directory is checked every pass, not just what was built
    this morning, so a project that finished before any of this existed
    still gets picked up.
    """
    out = []
    for f in sorted(RUNS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        d = _settle(d)
        if d.get("state") != "done" or d.get("shipped"):
            continue
        jid = d.get("job_id") or f.stem
        if _verdict(jid, "ship_failed") in ("open", "skip"):
            continue
        if not Path(d.get("directory") or "").is_dir():
            continue
        # Already being reviewed somewhere else. Two of these running on one
        # project means two agents editing the same files and two attempts
        # to create the same repository.
        if time.time() - float(d.get("shipping") or 0) < 3 * 3600:
            continue
        out.append(d)
    return out


def _why_not(r: dict) -> str:
    """The short version of why the chain stopped, for the question card."""
    stage = r.get("stage", "")
    if stage == "review":
        rv = r.get("review") or {}
        lines = ["The reviewer would not sign it off."]
        if rv.get("summary"):
            lines.append("It said: " + str(rv["summary"])[:300])
        for b in (rv.get("blocking") or [])[:5]:
            lines.append("  - " + str(b)[:200])
        return "\n".join(lines)
    if stage == "readme":
        tries = (r.get("readme") or {}).get("attempts") or [{}]
        return ("The readme kept failing the writing check.\n"
                + str(tries[-1].get("report") or "")[:600])
    if stage == "gate":
        return ("Banned characters or a tool credit are still in the files.\n"
                + str((r.get("gate") or {}).get("report") or "")[:600])
    return str(r.get("why") or "unknown")


def _ship_one(d: dict, public: bool, results: list, lock) -> None:
    jid = d.get("job_id", "")
    workdir = Path(d["directory"])
    found = jobs.existing(jid)
    job = jobs.head_of(found["file"]) if found else {}
    job.setdefault("repo_name", d.get("repo") or workdir.name)

    _write_state(jid, shipping=time.time())
    r = ship.ship(workdir, job, public=public)
    url = (r.get("publish") or {}).get("url", "")
    attempts = int(d.get("ship_attempts") or 0) + 1
    # Keep the verdict. scrub() deletes kiln-review.json before the push, so
    # without this the only record of why a project was passed or stopped is
    # gone by the time anyone asks. tests_run is the one worth having: a
    # reviewer that could not run the suite is not the same as a green one.
    rv = r.get("review") or {}
    _write_state(jid, shipped=bool(r.get("ok")), ship_stage=r.get("stage", ""),
                 ship_why=r.get("why", ""), ship_attempts=attempts,
                 shipped_at=time.time(), repo_url=url, shipping=0,
                 tests_run=bool(rv.get("tests_run")),
                 tests_pass=bool(rv.get("tests_pass")),
                 review_summary=str(rv.get("summary") or "")[:800],
                 review_blocking=[str(b)[:300] for b in (rv.get("blocking") or [])])

    if r.get("ok"):
        questions.clear(jid, "ship_failed")
    elif attempts >= FAIL_LIMIT:
        questions.ask(
            jid, "ship_failed", repo=job.get("repo_name", ""),
            title="%s built but will not publish (%s)"
                  % (job.get("repo_name") or jid, r.get("stage", "")),
            detail=_why_not(r),
            options=["skip - leave it unpublished",
                     "retry - try the whole chain again",
                     "look - I will open the folder and fix it myself"])

    with lock:
        results.append({"job_id": jid, "repo": job.get("repo_name", ""),
                        "ok": bool(r.get("ok")), "stage": r.get("stage", ""),
                        "why": r.get("why", ""), "url": url})


def ship_done(limit: int = 3, public: bool = True) -> list[dict]:
    """Review, write a readme for, and publish everything that is waiting."""
    waiting = needs_ship()[:limit]
    results: list[dict] = []
    lock = threading.Lock()
    threads = [threading.Thread(target=_ship_one,
                                args=(d, public, results, lock))
               for d in waiting]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


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
    elif len(sys.argv) > 1 and sys.argv[1] == "ship":
        shipped = ship_done()
        print(json.dumps(shipped, indent=2, default=str) if shipped
              else "nothing waiting to publish")
    elif len(sys.argv) > 1 and sys.argv[1] == "reset":
        cleared = reset(sys.argv[2] if len(sys.argv) > 2 else "")
        print("cleared: " + (", ".join(cleared) if cleared else "nothing stuck"))
    elif len(sys.argv) > 2 and sys.argv[1] == "run":
        print(json.dumps(start(sys.argv[2], wait=True), indent=2, default=str))
    else:
        print(__doc__)
        print("agents available:", available_agents() or "none")
        print("workspace:", WORKSPACE)
        print("waiting to publish:", len(needs_ship()))
        print("\n  python -m kiln.runner pending")
        print("  python -m kiln.runner ship")
        print("  python -m kiln.runner run <job file>")
        print("  python -m kiln.runner status")
        print("  python -m kiln.runner reset [job id]")
