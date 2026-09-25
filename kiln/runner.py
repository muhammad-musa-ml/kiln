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
import statistics
import subprocess
import threading
import time
from pathlib import Path

from . import config, jobs, questions, ship

RUNS = config.DATA / "jobs" / "runs"
RUNS.mkdir(parents=True, exist_ok=True)

# How many real failures before it stops retrying quietly and asks me what
# to do. Two, because one failure is often the model having a bad night and
# three passes of the same crash is three wasted hours.
FAIL_LIMIT = 2

# Where a build is allowed to write. Anything outside is refused, so a bad
# directory in a job file cannot drop a repo in the middle of the system.
WORKSPACE = Path(os.environ.get("KILN_WORKSPACE", Path.home() / "kiln-builds"))

TIMEOUT = 3600

# What an estimate falls back to before anything has been timed here: the
# hour a build is allowed, and the half hour its reviewer is allowed.
DEFAULT_BUILD_MIN = TIMEOUT // 60
DEFAULT_SHIP_MIN = ship.REVIEW_TIMEOUT // 60

# The one card that asks which queued projects to build. It is filed like
# any other question, under a job id that is not a real job.
QUEUE_JOB = "build-queue"

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
    offered again on the next sync and is not the project's fault, so it
    never counts against the retry limit. A build that runs and breaks is
    mine to look at.
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
                    "project failing. It is still queued and will be offered "
                    "again on the next sync.\n"
                    "Last output:\n  %s" % tail.strip()[-400:]),
            # No cloud choice: nothing here can start one, and a choice that
            # quietly did the local build instead was a promise not kept.
            options=["wait - leave it queued for the next sync",
                     "claude - build it with claude on this machine"])
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
    """Where the answered questions say this job should go.

    A skip on any card wins. It used to lose to an older card answered
    claude, which sorts first by name, so skip did nothing at all.
    """
    answers = [(q.get("answer") or "").strip().lower() for q in questions.all_questions()
               if q.get("job_id") == job_id and q.get("answered_at")]
    if any(a.startswith("skip") for a in answers):
        return "skip"
    if any("claude" in a for a in answers):
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


def _jid(j: dict) -> str:
    return j.get("job_id") or Path(j["file"]).stem


def _eligible(only: list[str] | None = None) -> list[tuple[dict, str]]:
    """Queued jobs a build may start on now, each with the agent to use.

    The queue card offers from this and run_pending builds from it, so what
    I am asked about and what gets built cannot drift apart.
    """
    if isinstance(only, str):
        # A lone id as text would otherwise match as a substring.
        only = [only]
    chosen: list[tuple[dict, str]] = []
    for j in jobs.pending():
        jid = _jid(j)
        if only is not None and jid not in only:
            continue
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
    return chosen


def run_pending(limit: int = 3, only: list[str] | None = None) -> list[dict]:
    """Build up to `limit` of the queued jobs, all at once, and wait for them.

    What is left waits for the next call; run_consented loops over batches.

    They run together rather than one after another. Each is a separate agent
    in its own directory with nothing to fight over, so three at a time turns
    three hours of building into one.

    The cap is applied after the skipping, not before. Slicing the queue
    first means three finished jobs at the front hide everything behind them.

    With `only`, just those job ids are considered, and every rule above
    still applies to them. Naming a job cannot get it past one.
    """
    chosen = _eligible(only)[:max(0, limit)]

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


def _minutes(seconds: float) -> int:
    return max(1, int(round(seconds / 60)))


def _hm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if not h:
        return "%d min" % m
    return "%d h %d min" % (h, m) if m else "%d h" % h


def _timings() -> tuple[list[float], list[float]]:
    """Seconds each finished build took, and each timed publishing run."""
    builds: list[float] = []
    ships: list[float] = []
    for f in RUNS.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            took = float(d.get("finished") or 0) - float(d.get("started") or 0)
            if d.get("state") == "done" and d.get("started") and took > 0:
                builds.append(took)
            took = (float(d.get("shipped_at") or 0)
                    - float(d.get("ship_started") or 0))
            if d.get("ship_started") and took > 0:
                ships.append(took)
        except Exception:
            continue
    return builds, ships


# The paragraph jobs.build_prompt writes after the one-liner. A brief with no
# one-liner has this as its next line, and it says nothing about the project.
_BOILERPLATE = "I want a working repository"
_SIZE = re.compile(r"Rough size:\s*about\s*(\d+(?:\.\d+)?)\s*hours?\b")


def _what(job: dict, text: str) -> str:
    """One line on what the project is: the brief's name and its one-liner."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    name, line = "", ""
    for i, row in enumerate(lines):
        if row.startswith("# Build:"):
            name = row[len("# Build:"):].strip()
            after = next((x for x in lines[i + 1:] if x), "")
            if not after.startswith(("#", _BOILERPLATE)):
                line = after
            break
    name = name or job.get("repo_name") or job.get("job_id") or "project"
    what = f"{name}: {line}" if line else name
    if len(what) > 200:
        what = what[:197].rsplit(" ", 1)[0] + "..."
    return what


def estimate(job: dict) -> dict:
    """Rough minutes to build and publish one queued job, and their source.

    The times are the median of what past runs actually took here, so every
    number on the card can be traced to a run record. Until something has
    been timed the defaults above stand in, and `basis` says which it was.
    """
    builds, ships = _timings()
    if builds:
        build_min = _minutes(statistics.median(builds))
        basis = ["Build time is the median of %d past build%s."
                 % (len(builds), "" if len(builds) == 1 else "s")]
    else:
        build_min = DEFAULT_BUILD_MIN
        basis = ["Build time is a default of %d min, because no build has "
                 "finished yet." % build_min]
    if ships:
        ship_min = _minutes(statistics.median(ships))
        basis.append("Publishing time is the median of %d past run%s."
                     % (len(ships), "" if len(ships) == 1 else "s"))
    else:
        ship_min = DEFAULT_SHIP_MIN
        basis.append("Publishing time is a default of %d min, because no "
                     "publish has been timed yet." % ship_min)

    try:
        text = Path(job.get("file") or "").read_text(encoding="utf-8")
    except Exception:
        text = ""
    size = _SIZE.search(text)
    return {"build_min": build_min, "ship_min": ship_min,
            "total_min": build_min + ship_min, "basis": " ".join(basis),
            "size_hours": float(size.group(1)) if size else None,
            "what": _what(job, text)}


def _queue_card() -> dict:
    for q in questions.all_questions():
        if q.get("job_id") == QUEUE_JOB and q.get("kind") == "queue":
            return q
    return {}


def offer_queue(at_once: int = 3) -> dict | None:
    """Ask which queued projects to build, on one card that lists them all.

    Nothing is built until I answer it, and consented() is what reads the
    answer. Each project gets a rough time, and the card's total allows for
    `at_once` of them building together, the way run_consented does it.
    Returns the card as it now stands, or None when nothing can be built.
    """
    card = _queue_card()
    ready = _eligible()
    if not ready:
        # Only a card still waiting on me comes down. One I have answered
        # stays for consented() to read, even with nothing left to build.
        if card and not card.get("answered_at"):
            questions.clear(QUEUE_JOB, "queue")
        return None
    if card.get("answered_at"):
        # Answered and not yet read. Asking again would wipe the answer out
        # before the next sync could act on it.
        return card

    projects = []
    basis = ""
    for n, (j, _agent) in enumerate(ready, 1):
        est = estimate(j)
        basis = est["basis"]
        projects.append({"n": n, "job_id": _jid(j),
                         "repo": j.get("repo_name") or _jid(j),
                         "what": est["what"], "minutes": est["total_min"],
                         "size_hours": est["size_hours"]})
    at_once = max(1, int(at_once))
    mins = [p["minutes"] for p in projects]
    total = sum(max(mins[i:i + at_once]) for i in range(0, len(mins), at_once))

    lines = ["Nothing here is built until you answer. Tick the ones you want "
             "on the card in the Kiln UI, or answer all or none.", ""]
    for p in projects:
        size = ("; the brief puts it at about %g hours of work"
                % p["size_hours"] if p["size_hours"] else "")
        lines.append("[%d] %s" % (p["n"], p["what"]))
        lines.append("    about %s to build and publish%s"
                     % (_hm(p["minutes"]), size))
    n = len(projects)
    lines.append("")
    if n > 1:
        lines.append("All of them: about %s, up to %d at a time."
                     % (_hm(total), at_once))
    lines += [basis, "The answer is read when the next sync reaches its build "
                     "queue, after the inbox, the follow-up and the site."]
    return questions.ask(
        QUEUE_JOB, "queue",
        title="%d project%s queued to build, about %s%s"
              % (n, "" if n == 1 else "s", _hm(total),
                 "" if n == 1 else " for all of them"),
        detail="\n".join(lines), options=["all", "none"],
        extra={"projects": projects, "total_min": total})


def consented() -> dict:
    """Read my answer to the queue card, then take the card down.

    all is every project the card listed that can still be built, none is
    none, and ticked ids (how one and a few arrive) are those of them that
    can still be built. Taking the card down means the next sync offers
    whatever is left.
    """
    card = _queue_card()
    if not card.get("answered_at"):
        return {"answered": False, "choice": "", "job_ids": []}
    choice = str(card.get("answer") or "").strip()
    word = (choice.lower().split() or [""])[0]
    ready = [_jid(j) for j, _agent in _eligible()]
    listed = [str(p.get("job_id")) for p in card.get("projects") or []
              if isinstance(p, dict)]
    picked = card.get("picked") or []
    picked = {str(x) for x in ([picked] if isinstance(picked, str) else picked)}
    if word == "none":
        ids = []
    elif word == "all":
        # All means all of what the card showed me. A job queued after it
        # was asked waits for the next card instead of riding in on this.
        ids = [jid for jid in ready if jid in listed] if listed else ready
    else:
        ids = [jid for jid in ready if jid in picked]
    questions.clear(QUEUE_JOB, "queue")
    return {"answered": True, "choice": choice, "job_ids": ids}


def run_consented(job_ids: list[str], at_once: int = 3) -> list[dict]:
    """Build the jobs I said yes to, `at_once` at a time, each of them once.

    Every batch goes through run_pending and is waited for before the next
    one starts, so its rules are checked again for each batch.
    """
    if isinstance(job_ids, str):
        job_ids = [job_ids]
    at_once = max(1, int(at_once))
    todo = list(dict.fromkeys(job_ids))
    results: list[dict] = []
    while todo:
        batch, todo = todo[:at_once], todo[at_once:]
        results += run_pending(limit=at_once, only=batch)
    return results


def needs_ship() -> list[dict]:
    """Builds that finished and have not been through the review chain.

    The whole run directory is checked every pass, not just what the
    current sync built, so a project that finished before any of this
    existed still gets picked up.
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

    began = time.time()
    # shipping goes back to 0 when the chain ends, so the start is kept a
    # second time for estimate() to time the chain by.
    _write_state(jid, shipping=began, ship_started=began)
    r = ship.ship(workdir, job, public=public)
    url = (r.get("publish") or {}).get("url", "")
    attempts = int(d.get("ship_attempts") or 0) + 1
    # Keep the verdict. scrub() deletes kiln-review.json before the push, so
    # without this the only record of why a project was passed or stopped is
    # gone by the time anyone asks. tests_run is the one worth having: a
    # reviewer that could not run the suite is not the same as a green one.
    rv = r.get("review") or {}
    # CI runs after the push, so it cannot stop one. Kept so a project that
    # only breaks on a clean machine is reported rather than looking green.
    ci = {k: v for k, v in (r.get("ci") or {}).items()
          if k in ("checked", "ok", "conclusion", "url", "why")}
    _write_state(jid, shipped=bool(r.get("ok")), ship_stage=r.get("stage", ""),
                 ship_why=r.get("why", ""), ship_attempts=attempts,
                 shipped_at=time.time(), repo_url=url, shipping=0,
                 tests_run=bool(rv.get("tests_run")),
                 tests_pass=bool(rv.get("tests_pass")),
                 review_summary=str(rv.get("summary") or "")[:800],
                 review_blocking=[str(b)[:300] for b in (rv.get("blocking") or [])],
                 ci=ci)

    if r.get("ok"):
        questions.clear(jid, "ship_failed")
    elif attempts >= FAIL_LIMIT:
        questions.ask(
            jid, "ship_failed", repo=job.get("repo_name", ""),
            title="%s built but will not publish (%s)"
                  % (job.get("repo_name") or jid, r.get("stage", "")),
            detail=_why_not(r) + ("\n\nTo fix it by hand first: open %s, fix it, "
                                  "then answer retry." % workdir),
            # There used to be a "look" choice. It counted as retry, so the
            # chain ran again on the next sync whether or not I had fixed it.
            options=["skip - leave it unpublished",
                     "retry - try the whole chain again"])

    with lock:
        results.append({"job_id": jid, "repo": job.get("repo_name", ""),
                        "ok": bool(r.get("ok")), "stage": r.get("stage", ""),
                        "why": r.get("why", ""), "url": url, "ci": ci})


def ci_line(ci: dict, with_url: bool = True) -> str:
    """How the project's own CI went after the push, in a few words."""
    url = (" " + ci.get("url", "")) if with_url and (ci or {}).get("url") else ""
    if not ci:
        return "CI not checked"
    if not ci.get("checked"):
        return "CI not checked: %s" % (ci.get("why") or "no reason given")
    if ci.get("ok"):
        return "CI passed" + url
    return "CI FAILED (%s)%s" % (ci.get("conclusion") or ci.get("why") or "?", url)


def ship_done(limit: int = 3, public: bool = True) -> list[dict]:
    """Review, write a readme for, and publish up to `limit` finished builds.

    They go through the chain side by side. The rest wait for the next pass.
    """
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
