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

from kiln import jobs, questions, runner, ship  # noqa: E402

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
    print("questions the morning run cannot answer on its own")
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


# --- which jobs the morning run actually picks ---------------------------
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


def main() -> int:
    test_allowlist()
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
