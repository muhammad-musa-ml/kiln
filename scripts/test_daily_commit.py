"""The scheduled sync commits the built site and nothing else.

Runs the real daily.main() against a throwaway repo that pushes to a local
bare remote. Ingest, publish and the audit are stubbed. Every git call is real.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent

OLD_BUILD = '{"items": []}\n'
NEW_BUILD = '{"items": [{"id": "a"}]}\n'

# Set while a git hook runs, these would point every git call below at the
# repo running the hook instead of the throwaway one.
_REDIRECTS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
              "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR")
GIT_ENV = {k: v for k, v in os.environ.items() if k not in _REDIRECTS}

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(passed)
    if passed:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail else ""))


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def make_repo(base: Path) -> tuple[Path, Path]:
    base.mkdir(parents=True)
    origin, repo = base / "origin.git", base / "repo"
    git(base, "init", "-q", "--bare", "-b", "master", str(origin))
    git(base, "init", "-q", "-b", "master", str(repo))
    no_hooks = str(base / "no-hooks")
    git(origin, "config", "core.hooksPath", no_hooks)
    for key, value in (("user.name", "test"), ("user.email", "test@example.invalid"),
                       ("commit.gpgsign", "false"), ("core.hooksPath", no_hooks)):
        git(repo, "config", key, value)
    git(repo, "remote", "add", "origin", str(origin))

    (repo / "public" / "data").mkdir(parents=True)
    (repo / "public" / "data" / "items.json").write_text(OLD_BUILD, encoding="utf-8")
    (repo / "notes.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "push", "-q", "origin", "master")

    # What a working tree can have lying around when the sync runs.
    (repo / "cycle.log").write_text("Traceback (most recent call last):\n", encoding="utf-8")
    (repo / "notes.py").write_text("x = 2  # half done\n", encoding="utf-8")
    (repo / "wip.py").write_text("y = 1\n", encoding="utf-8")
    git(repo, "add", "wip.py")
    return repo, origin


def load_daily(repo: Path, build: str, morning: bool = False,
               answer: dict | None = None):
    """Import daily.py with kiln faked out and every command sent to `repo`.

    The real kiln package creates data dirs and a token file on import and
    probes the local model ports. None of that is under test here.

    Returns the module and a list the fakes append to, so a test can say
    what was reached rather than guessing from text. `answer` is what the
    queue card says when the pass reads it; None means nobody answered.
    """
    calls: list[tuple] = []
    counts = iter([{"total": 0}, {"total": 1}])
    store = types.ModuleType("kiln.store")
    store.connect = lambda: types.SimpleNamespace(close=lambda: None)
    store.counts = lambda conn: next(counts)
    ingest = types.ModuleType("kiln.ingest")
    ingest.new_items = lambda text, conn: [{"urls": ["https://example.com/a"]}]
    ingest.ingest_text = lambda text, source, conn: iter(
        [{"status": "processed", "url": "https://example.com/a", "title": "a"}])
    pipeline = types.ModuleType("kiln.pipeline")
    pipeline.retry_failed = lambda conn: calls.append(("retry",)) or []

    brain = types.ModuleType("kiln.brain")
    brain.sweep = lambda: calls.append(("claude",)) or {"units": [], "reads": []}
    brain.render = lambda result: "      nothing needed"

    questions = types.ModuleType("kiln.questions")
    questions.open_questions = lambda: []
    questions.render = lambda qs=None: ""

    def consented():
        calls.append(("read answer",))
        if answer is None:
            return {"answered": False, "choice": "", "job_ids": []}
        return {"answered": True, **answer}

    def build_now(job_ids, at_once=3):
        calls.append(("build", tuple(job_ids), at_once))
        return []

    def offer(at_once=3):
        calls.append(("offer", at_once))
        return {"projects": [{"job_id": "a"}], "total_min": 90}

    def ship_now(limit=3):
        calls.append(("ship", limit))
        return []

    runner = types.ModuleType("kiln.runner")
    runner.jobs = types.SimpleNamespace(pending=lambda: [{"file": "a.md", "job_id": "a"}])
    runner.needs_ship = lambda: [{"job_id": "a"}]
    runner.consented = consented
    runner.run_consented = build_now
    runner.offer_queue = offer
    runner.ship_done = ship_now

    health = types.ModuleType("kiln.health")
    health.check_all = lambda conn=None: []
    health.render = lambda found: "      nothing out of place"
    health.raise_questions = lambda found: 0
    health.beat = lambda mode, added: calls.append(("beat", mode))

    kiln = types.ModuleType("kiln")
    kiln.store, kiln.ingest, kiln.pipeline, kiln.brain = store, ingest, pipeline, brain
    kiln.questions, kiln.runner, kiln.health = questions, runner, health
    sys.modules.update({"kiln": kiln, "kiln.store": store,
                        "kiln.ingest": ingest, "kiln.pipeline": pipeline,
                        "kiln.brain": brain, "kiln.questions": questions,
                        "kiln.runner": runner, "kiln.health": health})

    spec = importlib.util.spec_from_file_location("daily_under_test", HERE / "daily.py")
    daily = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daily)

    def run(cmd: list[str]) -> tuple[int, str]:
        if cmd[0] == "git":
            p = subprocess.run(cmd, cwd=repo, env=GIT_ENV,
                               capture_output=True, text=True)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        if cmd[1:] == ["-m", "kiln.publish"]:
            (repo / "public" / "data" / "items.json").write_text(build, encoding="utf-8")
            return 0, ""
        if cmd[1:] == ["scripts/audit_public.py"]:
            return 0, "AUDIT PASSED - stubbed"
        if cmd[1:] == ["scripts/dedupe_jobs.py"]:
            return 0, "no duplicates"
        raise AssertionError(f"daily.py ran something unexpected: {cmd}")

    # Both, so a broken daily.py under test can't commit or push from this
    # checkout: every command goes through run(), which only knows `repo`.
    daily.ROOT = repo
    daily.run = run
    # Pinned, or the same test passes before noon and fails after it.
    daily.is_morning = lambda: morning
    return daily, calls


def sync(repo: Path, inbox: Path, build: str, morning: bool = False,
         answer: dict | None = None, args: list | None = None) -> tuple[int, str, list]:
    daily, calls = load_daily(repo, build, morning, answer)
    argv, sys.argv = sys.argv, ["daily.py", str(inbox)] + (args or [])
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = daily.main()
    finally:
        sys.argv = argv
    return code, out.getvalue(), calls


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        inbox = tmp / "inbox.txt"
        inbox.write_text("https://example.com/a\n", encoding="utf-8")

        print("new item, site rebuilt")
        repo, origin = make_repo(tmp / "one")
        code, out, calls = sync(repo, inbox, NEW_BUILD)
        check("sync returns 0", code == 0, out.strip()[-300:])
        changed = git(origin, "show", "--name-only", "--format=", "master").split()
        check("pushed commit touches only the built site",
              changed == ["public/data/items.json"], f"changed: {changed}")
        remote = git(origin, "ls-tree", "-r", "--name-only", "master").split()
        check("stray log and staged file stay off the remote",
              "cycle.log" not in remote and "wip.py" not in remote, f"remote has: {remote}")
        check("half-done edit stays off the remote",
              "half done" not in git(origin, "show", "master:notes.py"))
        staged = git(repo, "diff", "--cached", "--name-only").split()
        unstaged = git(repo, "diff", "--name-only").split()
        check("work in progress is left where it was",
              staged == ["wip.py"] and unstaged == ["notes.py"],
              f"staged: {staged}, unstaged: {unstaged}")

        check("with nobody's answer on the card, nothing is built",
              [c for c in calls if c[0] == "build"] == [], f"called: {calls}")
        check("the queue is offered instead, three at a time",
              ("offer", 3) in calls, f"called: {calls}")
        check("and the answer is read before the offer is refreshed",
              calls.index(("read answer",)) < calls.index(("offer", 3)), f"called: {calls}")
        check("Claude's follow-up runs on every pass",
              ("claude",) in calls, f"called: {calls}")
        check("failed reads get their retry on every pass",
              ("retry",) in calls, f"called: {calls}")
        stages = [line[:5] for line in out.splitlines() if line[:3] in ("[1/", "[2/", "[3/", "[4/", "[5/", "[6/")]
        check("all six stages print, in order",
              stages == ["[%d/6]" % n for n in range(1, 7)], f"stages: {stages}")
        check("every pass leaves a heartbeat so a missed run is noticed",
              ("beat", "evening") in calls, f"called: {calls}")

        print("new item, but the site came out the same")
        repo, origin = make_repo(tmp / "two")
        head = git(origin, "rev-parse", "master")
        code, out, calls = sync(repo, inbox, OLD_BUILD)
        check("sync returns 0", code == 0, out.strip()[-300:])
        check("says there is nothing to push",
              "nothing to push" in out, out.strip()[-300:])
        check("remote unchanged", git(origin, "rev-parse", "master") == head)

        print("an evening pass after I answered the card")
        repo, origin = make_repo(tmp / "three")
        head = git(origin, "rev-parse", "master")
        code, out, calls = sync(repo, inbox, OLD_BUILD, morning=False,
                                answer={"choice": "all", "job_ids": ["a"]})
        check("sync returns 0", code == 0, out.strip()[-300:])
        check("what I said yes to is built, at any hour, then published",
              [c for c in calls if c[0] in ("build", "ship")]
              == [("build", ("a",), 3), ("ship", 3)], f"called: {calls}")
        check("a site that did not change is still not pushed",
              git(origin, "rev-parse", "master") == head)

        print("a morning pass that I answered none on")
        repo, origin = make_repo(tmp / "five")
        code, out, calls = sync(repo, inbox, OLD_BUILD, morning=True,
                                answer={"choice": "none", "job_ids": []})
        check("none builds nothing", [c for c in calls if c[0] == "build"] == [],
              f"called: {calls}")
        check("and records it as a morning run",
              ("beat", "morning") in calls, f"called: {calls}")

        print("builds switched off for one run")
        repo, origin = make_repo(tmp / "six")
        code, out, calls = sync(repo, inbox, OLD_BUILD, args=["--builds", "no"],
                                answer={"choice": "all", "job_ids": ["a"]})
        check("--builds no neither builds nor reads the answer",
              not [c for c in calls if c[0] in ("build", "read answer", "offer")],
              f"called: {calls}")

        print("building everything without asking, by hand")
        repo, origin = make_repo(tmp / "seven")
        code, out, calls = sync(repo, inbox, OLD_BUILD, args=["--builds", "yes"])
        check("--builds yes builds the whole queue without reading a card",
              ("build", ("a",), 3) in calls and ("read answer",) not in calls,
              f"called: {calls}")

        print("the site is rebuilt even when the inbox had nothing new")
        repo, origin = make_repo(tmp / "four")
        daily, _ = load_daily(repo, NEW_BUILD)
        daily_calls: list = []
        real_run = daily.run
        daily.run = lambda cmd: (daily_calls.append(cmd[1:]), real_run(cmd))[1]
        argv, sys.argv = sys.argv, ["daily.py", str(inbox)]
        out2 = io.StringIO()
        try:
            with contextlib.redirect_stdout(out2):
                daily.stage_site()
        finally:
            sys.argv = argv
        check("publish runs unconditionally, not only on new items",
              ["-m", "kiln.publish"] in daily_calls, f"ran: {daily_calls}")

    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
