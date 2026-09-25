"""The parts of the build and publish chain that must not drift.

Nothing here talks to GitHub or starts an agent. The publish step is not
exercised on purpose: it creates a real public repository, and a test that
does that once by accident is a test I would have to go and clean up after.

Banned characters are written with chr() so this file stays plain ASCII and
does not match the very checks it is testing.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import jobs, questions, runner, ship, slop  # noqa: E402

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(passed)
    if passed:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail else ""))


# --- was the agent down, or is the build broken? -------------------------
def test_agent_blocked() -> None:
    print("telling an agent that could not run from a build that is broken")

    # The regression. "modulenotfounderror" contains the letters "enotfound",
    # so an unanchored network check swallowed the commonest build failure
    # there is and called it a network problem.
    ordinary = [
        "ModuleNotFoundError: No module named requests",
        "ImportError while loading conftest",
        "AssertionError: expected 3 got 4",
        "FAILED tests/test_parse.py::test_empty",
        "SyntaxError: invalid syntax",
        "wrote 4291 lines",
    ]
    for text in ordinary:
        got = ship.agent_blocked(text)
        check("a real failure is not read as the agent being down: %s"
              % text[:44], got == "", f"got {got!r}")

    down = [
        ("Error: rate limit exceeded", "rate limited"),
        ("HTTP 429 Too Many Requests", "rate limited"),
        ("fetch failed ENOTFOUND api.example.com", "network unreachable"),
        ("503 Service Unavailable", "service down"),
        ("401 Unauthorized", "not authorised"),
        ("insufficient_quota", "out of quota"),
        ("You are not authenticated. Run login first.", "not signed in"),
    ]
    for text, reason in down:
        got = ship.agent_blocked(text)
        check("agent down is named: %s" % text[:44], got == reason,
              f"got {got!r}, wanted {reason!r}")


# --- what stops a push, and what only gets mentioned ---------------------
def test_gate() -> None:
    print("what blocks a push and what is only reported")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)

        (d / "clean.md").write_text(
            "I built a small parser. Run it with python parse.py.\n",
            encoding="utf-8")
        g = ship.gate(d)
        check("a clean project passes", g["ok"], g["report"])

        (d / "dash.md").write_text(
            "This is a sentence %s with a dash in it.\n" % chr(0x2014),
            encoding="utf-8")
        g = ship.gate(d)
        check("a banned character blocks the push", not g["ok"])
        check("and it is named as a character finding",
              any(f["rule"] == "char" for f in g["hard"]), g["report"])
        (d / "dash.md").unlink()

        (d / "credit.md").write_text(
            "Co-Authored-By: Claude <noreply@anthropic.com>\n", encoding="utf-8")
        g = ship.gate(d)
        check("a tool credit blocks the push", not g["ok"])
        check("and it is named as an attribution finding",
              any(f["rule"] == "attribution" for f in g["hard"]), g["report"])
        (d / "credit.md").unlink()

        (d / "wordy.py").write_text(
            "# this seamlessly handles the plethora of cases\nx = 1\n",
            encoding="utf-8")
        g = ship.gate(d)
        check("a bad word is reported but does not block", g["ok"], g["report"])
        check("and it still shows up as something to look at",
              any(f["rule"] == "phrase" for f in g["soft"]),
              str(g["soft"])[:200])


# --- one project, one job ------------------------------------------------
def test_dedup() -> None:
    print("the same project cannot sit in the queue twice")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        old_p, old_d = jobs.PENDING, jobs.DONE
        jobs.PENDING, jobs.DONE = d / "pending", d / "done"
        jobs.PENDING.mkdir()
        jobs.DONE.mkdir()
        try:
            # The two id schemes that actually collided: a clock based name
            # and an item based one, for one project.
            (jobs.DONE / "1790151785-parser.md").write_text(
                "---\njob_id: 1790151785-parser\nitem_id: abc123\n"
                "repo_name: parser\nstate: done\n---\n\nbody\n",
                encoding="utf-8")

            found = jobs.existing("abc123def456-parser", item_id="abc123")
            check("a job is found by its item, not by its file name",
                  found.get("job_id") == "1790151785-parser", str(found))
            check("and it reports where that job really is",
                  found.get("job_state") == "done", str(found))

            miss = jobs.existing("zzz-other", item_id="different")
            check("a genuinely new item finds nothing", miss == {}, str(miss))
        finally:
            jobs.PENDING, jobs.DONE = old_p, old_d


# --- questions the run parks for me --------------------------------------
def test_questions() -> None:
    print("questions a sync cannot answer on its own")
    with tempfile.TemporaryDirectory() as t:
        old = questions.QUESTIONS
        questions.QUESTIONS = Path(t) / "questions"
        questions.QUESTIONS.mkdir()
        try:
            q = questions.ask("job-1", "agent_down", "codex was down",
                              "it could not start", ["wait", "claude"], "parser")
            check("asking records one open question",
                  len(questions.open_questions()) == 1)

            again = questions.ask("job-1", "agent_down", "codex was down",
                                  "it could not start again")
            check("asking the same thing again does not make a second one",
                  len(questions.open_questions()) == 1)
            check("but it counts how many times it has come up",
                  again["asked_count"] == 2, str(again["asked_count"]))

            text = questions.render()
            check("the printed block names the question",
                  "codex was down" in text, text[:200])
            check("and offers the choices", "claude" in text, text[:200])

            questions.answer(q["id"], "claude - build it with claude")
            check("an answered question stops being open",
                  questions.open_questions() == [])
            check("and the answer is readable afterwards",
                  questions.all_questions()[0]["answer"].startswith("claude"))

            questions.clear("job-1")
            check("clearing removes it", questions.all_questions() == [])
        finally:
            questions.QUESTIONS = old


# --- which jobs a build run actually picks --------------------------------
def _job_file(folder: Path, jid: str, item: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{jid}.md").write_text(
        f"---\njob_id: {jid}\nitem_id: {item}\nrepo_name: {jid}\n"
        f"state: pending\n---\n\nbody\n", encoding="utf-8")


def test_selection() -> None:
    print("which jobs a run picks up")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        old = (jobs.PENDING, jobs.DONE, runner.RUNS, questions.QUESTIONS,
               runner.start)
        jobs.PENDING, jobs.DONE = d / "pending", d / "done"
        runner.RUNS = d / "runs"
        questions.QUESTIONS = d / "questions"
        for p in (jobs.PENDING, jobs.DONE, runner.RUNS, questions.QUESTIONS):
            p.mkdir(parents=True)

        started: list[str] = []

        def fake_start(job_file, *, directory="", agent="", wait=False):
            started.append(Path(job_file).stem)
            return {"job_id": Path(job_file).stem, "state": "done",
                    "agent": agent}

        runner.start = fake_start
        try:
            # Four queued. The first three are already built, so a run that
            # takes the first three and then filters would do nothing at all.
            for i, jid in enumerate(["a-one", "b-two", "c-three", "d-four"]):
                _job_file(jobs.PENDING, jid, f"item{i}")
            for jid in ["a-one", "b-two", "c-three"]:
                (runner.RUNS / f"{jid}.json").write_text(
                    json.dumps({"job_id": jid, "state": "done"}),
                    encoding="utf-8")

            runner.run_pending(limit=3)
            check("finished jobs at the front do not hide the queue behind them",
                  started == ["d-four"], f"started: {started}")

            # A second job for an item that was built under another job id.
            started.clear()
            _job_file(jobs.PENDING, "e-five", "item0")
            runner.run_pending(limit=3)
            check("a project already built under an older id is not built again",
                  "e-five" not in started, f"started: {started}")

            # An unanswered failure should stop it spinning on the same job.
            started.clear()
            (runner.RUNS / "d-four.json").write_text(
                json.dumps({"job_id": "d-four", "state": "failed",
                            "attempts": 2}), encoding="utf-8")
            questions.ask("d-four", "build_failed", "it keeps failing", "x")
            runner.run_pending(limit=3)
            check("a job waiting on me is left alone until I answer",
                  "d-four" not in started, f"started: {started}")

            started.clear()
            questions.answer("d-four.build_failed", "retry - try it again")
            runner.run_pending(limit=3)
            check("and it is picked up once I have answered",
                  "d-four" in started, f"started: {started}")

            started.clear()
            questions.answer("d-four.build_failed", "skip - stop trying this")
            runner.run_pending(limit=3)
            check("skip means skip", "d-four" not in started,
                  f"started: {started}")
        finally:
            (jobs.PENDING, jobs.DONE, runner.RUNS, questions.QUESTIONS,
             runner.start) = old


def test_failure_routing() -> None:
    print("where a failed build sends me")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        old = (runner.RUNS, questions.QUESTIONS)
        runner.RUNS, questions.QUESTIONS = d / "runs", d / "questions"
        runner.RUNS.mkdir()
        questions.QUESTIONS.mkdir()
        try:
            log = d / "one.log"
            log.write_text("Error: rate limit exceeded\n", encoding="utf-8")
            state = runner._failed("one", "parser", "codex", log, 1, 0)
            check("an agent that was down leaves the job blocked, not failed",
                  state["state"] == "blocked", str(state.get("state")))
            check("the reason is recorded",
                  state.get("blocked_reason") == "rate limited", str(state))
            check("and it asks me straight away",
                  len(questions.open_questions()) == 1)
            check("without counting against the retry limit",
                  not state.get("attempts"), str(state.get("attempts")))

            questions.clear("one")
            log2 = d / "two.log"
            log2.write_text("AssertionError: 3 != 4\n", encoding="utf-8")
            s1 = runner._failed("two", "parser", "codex", log2, 1, 12)
            check("a real failure counts once and stays quiet",
                  s1["attempts"] == 1 and not questions.open_questions(),
                  str(s1.get("attempts")))
            s2 = runner._failed("two", "parser", "codex", log2, 1, 12)
            check("the second one asks me what to do",
                  s2["attempts"] == 2 and len(questions.open_questions()) == 1,
                  str(s2.get("attempts")))
        finally:
            runner.RUNS, questions.QUESTIONS = old


def test_allowlist() -> None:
    """A rule with a space in it must reach the CLI as one argument.

    Measured once against the real CLI: passed as two arguments it refuses
    the rule and the reviewer cannot run a single command, while still
    writing a verdict. That reads exactly like a project that failed review.
    """
    print("the reviewer's allowlist survives a command line")
    cmd = ship._claude_cmd("claude.exe", "hello", ship.REVIEW_TOOLS)
    rules = cmd[cmd.index("--allowedTools") + 1:]
    check("a rule with a space in it stays one argument",
          "Bash(python *)" in rules, str(rules))
    check("no half of a rule is left standing on its own",
          not any(r in ("Bash(python", "*)", "Bash(pip") for r in rules),
          str(rules))
    check("the reviewer can run the tests",
          "Bash(pytest *)" in rules, str(rules))
    check("the readme writer gets no shell at all",
          not any(str(r).startswith("Bash") for r in ship.README_TOOLS),
          str(ship.README_TOOLS))


def test_description() -> None:
    """What GitHub shows beside the repo name comes from the readme."""
    print("the line GitHub shows beside the repo name")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "README.md").write_text(
            "# thing\n\nA small tool that files refunds. It will not let a "
            "big one through without a person saying yes.\n\n## Install\n",
            encoding="utf-8")
        got = ship._description(d)
        check("it skips the heading and takes the first real line",
              got.startswith("A small tool"), got)
        check("and stops before the next heading", "Install" not in got, got)

        long = "word " * 200
        (d / "README.md").write_text("# t\n\n%s\n" % long, encoding="utf-8")
        got = ship._description(d)
        check("a long opening is cut at 250 characters", len(got) <= 250,
              str(len(got)))
        check("and never cut through the middle of a word",
              got.endswith("word") or got.endswith("."), repr(got[-12:]))

        (d / "README.md").unlink()
        check("no readme is an empty description, not a crash",
              ship._description(d) == "")


def _project(d: Path, test_body: str) -> None:
    (d / "tests").mkdir(parents=True, exist_ok=True)
    (d / "tests" / "test_it.py").write_text(test_body, encoding="utf-8")


def test_run_tests() -> None:
    """The tests are run here, not taken on the reviewer's word for it."""
    print("running the project's own tests")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        d = Path(t)

        r = ship.run_tests(d)
        check("a project with no tests is not held up", r["passed"], str(r))
        check("but it is honest that there were none", not r["found"], str(r))

        _project(d, "def test_ok():\n    assert 1 + 1 == 2\n")
        r = ship.run_tests(d)
        check("passing tests pass", r["passed"] and r["ran"], str(r)[:200])
        check("and it says it found them", r["found"], str(r)[:200])

        _project(d, "def test_no():\n    assert 1 + 1 == 3\n")
        r = ship.run_tests(d)
        check("a failing test blocks", not r["passed"], str(r)[:200])
        check("and says the tests fail", "fail" in r["why"], r["why"])

        # A file named like a test that holds none is not a pass. This is
        # how a project with the shape of a test suite and none of the
        # substance would otherwise sail through.
        _project(d, "x = 1\n")
        r = ship.run_tests(d)
        check("test files that collect nothing do not count as passing",
              not r["passed"], str(r)[:200])


def test_ci_helpers() -> None:
    print("reading the CI result back")
    check("a repo url becomes owner/name",
          ship._repo_slug("https://github.com/someone/a-project") == "someone/a-project",
          ship._repo_slug("https://github.com/someone/a-project"))
    check("a .git suffix is trimmed",
          ship._repo_slug("https://github.com/someone/a-project.git") == "someone/a-project")
    check("junk gives nothing rather than a wrong slug",
          ship._repo_slug("not a url") == "")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        r = ship.wait_for_ci("https://github.com/x/y", Path(t))
        check("a project with no workflow is not waited on",
              r.get("checked") is False, str(r))


def test_readme_prompt() -> None:
    print("what the readme writer is told")
    p = ship._readme_prompt({"source": "https://example.com/p/ABC?stkn=SECRET"},
                            {"summary": "it works"})
    check("the source link never reaches the prompt", "stkn=SECRET" not in p)
    check("and it is told not to credit one",
          "Do not say where the idea came from" in p)
    check("the voice rules come from the one shared copy",
          slop.voice_rules()[:40] in p)
    check("no unfilled placeholder is left in it", "%s" not in p, p[-200:])


def main() -> int:
    test_allowlist()
    test_description()
    test_run_tests()
    test_ci_helpers()
    test_readme_prompt()
    test_agent_blocked()
    test_gate()
    test_dedup()
    test_questions()
    test_selection()
    test_failure_routing()
    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
