"""The build queue waits for my say-so, and is built exactly as answered.

Builds used to start on a morning schedule without anyone being asked. Now
every sync offers the queue as one card with a rough time per project, and
only what I pick gets built. These pin the estimate, the card, the reading
of the answer, and the batches that follow it.

No agent ever starts. runner.start is replaced before anything can reach it,
and the agent list is emptied too, so the real one would refuse to launch.
Everything is written under a throwaway data folder, never the real one.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Pinned before the first kiln import. The queue, run and question folders
# are worked out from it the moment their modules load, so setting it any
# later would leave them pointing at the real data folder.
DATA = Path(tempfile.mkdtemp(prefix="kiln-queue-gate-")).resolve()
os.environ["KILN_DATA"] = str(DATA)
os.environ["KILN_WORKSPACE"] = str(DATA / "builds")

from kiln import config  # noqa: E402

if Path(config.DATA).resolve() != DATA:
    raise SystemExit("KILN_DATA did not take: kiln.config.DATA is %s, not %s"
                     % (config.DATA, DATA))

from kiln import jobs, questions, runner  # noqa: E402

for _name, _p in (("jobs.PENDING", jobs.PENDING), ("jobs.DONE", jobs.DONE),
                  ("runner.RUNS", runner.RUNS),
                  ("questions.QUESTIONS", questions.QUESTIONS),
                  ("runner.WORKSPACE", runner.WORKSPACE)):
    if not Path(_p).resolve().is_relative_to(DATA):
        raise SystemExit("%s is %s, outside the test folder %s"
                         % (_name, _p, DATA))

QID = "build-queue.queue"

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    # bool() because an `a and b` check hands back b itself, and a timestamp
    # summed into the pass count reads as a pass count.
    passed = bool(passed)
    results.append(passed)
    if passed:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail else ""))


# --- the stand-in for a build agent -----------------------------------------
started: list[str] = []
_lock = threading.Lock()
_live = {"now": 0, "most": 0}
DELAY = {"s": 0.0}


def fake_start(job_file, *, directory="", agent="", wait=False):
    """Record the build, count how many overlap, and mark the job built."""
    jid = jobs.head_of(job_file).get("job_id") or Path(job_file).stem
    with _lock:
        started.append(jid)
        _live["now"] += 1
        _live["most"] = max(_live["most"], _live["now"])
    time.sleep(DELAY["s"])
    with _lock:
        _live["now"] -= 1
    return runner._write_state(jid, state="done", agent=agent, repo=jid,
                               started=1.0, finished=61.0)


runner.start = fake_start
runner.AGENTS = []


def fresh() -> None:
    """Empty every folder the gate reads, so each test starts from nothing."""
    for d in (jobs.PENDING, jobs.DONE, runner.RUNS, questions.QUESTIONS):
        d = Path(d).resolve()
        if not d.is_relative_to(DATA):
            raise SystemExit("refusing to empty %s: it is outside %s" % (d, DATA))
        for f in d.glob("*"):
            if f.is_file():
                f.unlink()
    started.clear()
    _live.update(now=0, most=0)
    DELAY["s"] = 0.0


def queue(jid: str, item: str, one_liner: str = "A small tool that does one thing.",
          hours=8, folder: Path | None = None) -> Path:
    """Write a job the way jobs.create does, prompt and front matter both."""
    project = {"name": jid}
    if one_liner:
        project["one_liner"] = one_liner
    if hours is not None:
        project["est_hours"] = hours
    url = "https://example.com/p/" + jid
    prompt = jobs.build_prompt({"enrich": {"project": project}, "url": url})
    job = {"id": jid, "item_id": item, "repo_name": jid, "target": "local",
           "directory": "", "source_url": url, "created_at": time.time(),
           "prompt": prompt}
    path = (folder or jobs.PENDING) / f"{jid}.md"
    path.write_text(jobs._job_file(job), encoding="utf-8")
    return path


def ran(jid: str, **state) -> None:
    (runner.RUNS / f"{jid}.json").write_text(
        json.dumps({"job_id": jid, **state}), encoding="utf-8")


def cards() -> list[dict]:
    return [q for q in questions.all_questions() if q.get("kind") == "queue"]


def pending_job(jid: str) -> dict:
    return next(j for j in jobs.pending() if j.get("job_id") == jid)


# --- the question store ------------------------------------------------------
def test_ask_extra() -> None:
    print("a question can carry more than words")
    fresh()
    q = questions.ask("job-9", "queue", "a title", "first", ["all", "none"],
                      extra={"projects": [1, 2], "total_min": 5,
                             "answer": "all", "id": "forged",
                             "answered_at": 99, "picked": ["x"]})
    check("extra keys are stored at the top level",
          q.get("projects") == [1, 2] and q.get("total_min") == 5, str(q))
    check("and can never replace a key every question has",
          q["answer"] == "" and q["id"] == "job-9.queue"
          and q["answered_at"] == 0 and not q.get("picked"), str(q))
    on_disk = questions.all_questions()
    check("what is on disk is what came back",
          len(on_disk) == 1 and on_disk[0] == q, str(on_disk))

    again = questions.ask("job-9", "queue", "a title", "second",
                          extra={"projects": [3]})
    check("asking again refreshes extra along with the detail",
          again.get("projects") == [3] and "total_min" not in again
          and again["detail"] == "second", str(again))
    check("and it is still one question, now seen twice",
          len(questions.all_questions()) == 1 and again["asked_count"] == 2,
          str(questions.all_questions()))

    kept = questions.ask("job-9", "queue", "a title", "third")
    check("a repeat that brings no extra keeps what the card carried",
          kept.get("projects") == [3] and kept["options"] == ["all", "none"],
          str(kept))

    plain = questions.ask("job-8", "agent_down", "t", "d", ["wait"], "repo")
    check("a caller that passes no extra gets exactly the old shape",
          sorted(plain) == sorted(["id", "job_id", "kind", "repo", "title",
                                   "detail", "options", "asked_at",
                                   "asked_count", "answered_at", "answer",
                                   "note"]), str(sorted(plain)))


def test_answer_picked() -> None:
    print("an answer can say which ones were ticked")
    fresh()
    q = questions.ask("job-7", "queue", "t", "d", ["all", "none"])
    a = questions.answer(q["id"], "few", picked=["b", "c"])
    check("the ticked ids are stored with the answer",
          a.get("picked") == ["b", "c"] and a["answer"] == "few", str(a))
    check("and read back the same from disk",
          questions.all_questions()[0].get("picked") == ["b", "c"],
          str(questions.all_questions()))
    b = questions.answer(q["id"], "all")
    check("a plain answer stores an empty pick", b.get("picked") == [], str(b))
    c = questions.answer(q["id"], "none", "a note")
    check("the old positional call still works",
          c["answer"] == "none" and c["note"] == "a note"
          and c.get("picked") == [], str(c))


# --- estimates ---------------------------------------------------------------
def test_estimate_defaults() -> None:
    print("an estimate with nothing timed yet")
    fresh()
    queue("a-one", "i1")
    est = runner.estimate(pending_job("a-one"))
    check("it has exactly the fields the card uses",
          sorted(est) == sorted(["build_min", "ship_min", "total_min",
                                 "basis", "size_hours", "what"]),
          str(sorted(est)))
    check("build time falls back to the stated default",
          est["build_min"] == runner.DEFAULT_BUILD_MIN, str(est))
    check("publishing time falls back to its default",
          est["ship_min"] == runner.DEFAULT_SHIP_MIN, str(est))
    check("the defaults are real minutes",
          isinstance(runner.DEFAULT_BUILD_MIN, int)
          and isinstance(runner.DEFAULT_SHIP_MIN, int)
          and runner.DEFAULT_BUILD_MIN > 0 and runner.DEFAULT_SHIP_MIN > 0,
          "%r %r" % (runner.DEFAULT_BUILD_MIN, runner.DEFAULT_SHIP_MIN))
    check("the total is the two added up",
          est["total_min"] == est["build_min"] + est["ship_min"], str(est))
    check("and it says plainly that these are defaults",
          "default" in est["basis"]
          and "no build has finished yet" in est["basis"]
          and "no publish has been timed yet" in est["basis"], est["basis"])
    check("the brief's own size is read from the job file",
          est["size_hours"] == 8.0, repr(est["size_hours"]))
    check("and it says what the project is in one line",
          est["what"] == "a-one: A small tool that does one thing.",
          repr(est["what"]))


def test_estimate_history() -> None:
    print("an estimate from runs that were timed")
    fresh()
    queue("a-one", "i1")
    job = pending_job("a-one")
    ran("p-one", state="done", started=1000.0, finished=1000.0 + 30 * 60)
    ran("p-two", state="done", started=5000.0, finished=5000.0 + 50 * 60)
    # Not a finished build: none of these may count.
    ran("p-bad", state="failed", started=1.0, finished=1.0 + 5 * 60)
    ran("p-run", state="running", started=time.time(), finished=0)
    ran("p-half", state="done", started=10.0)
    est = runner.estimate(job)
    check("two past builds give their median",
          est["build_min"] == 40, str(est))
    check("and it says where the number came from",
          "median of 2 past builds" in est["basis"], est["basis"])

    ran("p-three", state="done", started=1000.0, finished=1000.0 + 90 * 60)
    ran("p-one", state="done", started=1000.0, finished=1000.0 + 10 * 60)
    ran("p-two", state="done", started=1000.0, finished=1000.0 + 20 * 60)
    est = runner.estimate(job)
    check("three builds of 10, 20 and 90 minutes give 20, not the mean",
          est["build_min"] == 20, str(est))

    # A start of 0 is a start nobody recorded. Counting it would turn the
    # finish timestamp itself into a build some fifty years long.
    ran("p-zero", state="done", started=0, finished=1790206688.9)
    est = runner.estimate(job)
    check("a run with no recorded start is not counted",
          est["build_min"] == 20 and "median of 3 past builds" in est["basis"],
          str(est))

    fresh()
    queue("a-one", "i1")
    ran("1790151785-triage-guard-agent", state="done",
        started=1790204484.936293, finished=1790206688.9040675)
    est = runner.estimate(pending_job("a-one"))
    check("the one real run on record reads as about 37 minutes",
          est["build_min"] == 37, str(est))

    ran("s-one", state="done", started=0.0, finished=60.0,
        ship_started=100.0, shipped_at=100.0 + 12 * 60, shipped=True)
    ran("s-two", state="done", started=0.0, finished=60.0,
        ship_started=100.0, shipped_at=100.0 + 16 * 60, shipped=False)
    # Started again and never finished: its end is older than its start.
    ran("s-three", state="done", started=0.0, finished=60.0,
        ship_started=9000.0, shipped_at=100.0)
    est = runner.estimate(pending_job("a-one"))
    check("publishing time is the median of the timed runs",
          est["ship_min"] == 14, str(est))
    check("and says so", "median of 2 past runs" in est["basis"], est["basis"])
    check("the total follows", est["total_min"] == est["build_min"] + 14,
          str(est))


def test_estimate_what() -> None:
    print("reading what a project is from its job file")
    fresh()
    queue("b-two", "i2", one_liner="", hours=None)
    est = runner.estimate(pending_job("b-two"))
    check("no one-liner gives the name alone, not the boilerplate after it",
          est["what"] == "b-two", repr(est["what"]))
    check("no stated size gives None", est["size_hours"] is None,
          repr(est["size_hours"]))

    queue("c-three", "i3", hours=2.5)
    est = runner.estimate(pending_job("c-three"))
    check("a fractional size is kept", est["size_hours"] == 2.5,
          repr(est["size_hours"]))

    (jobs.PENDING / "d-four.md").write_text(
        "---\r\njob_id: d-four\r\nitem_id: i4\r\nrepo_name: parser\r\n---\r\n"
        "\r\n# Build: parser\r\n\r\nReads a file and says what is in it.\r\n"
        "\r\nRough size: about 3 hours of work.\r\n", encoding="utf-8")
    est = runner.estimate(pending_job("d-four"))
    check("windows line endings are read the same way",
          est["what"] == "parser: Reads a file and says what is in it."
          and est["size_hours"] == 3.0, str(est))

    (jobs.PENDING / "e-five.md").write_text(
        "---\njob_id: e-five\nitem_id: i5\nrepo_name: hand-made\n---\n\nbody\n",
        encoding="utf-8")
    est = runner.estimate(pending_job("e-five"))
    check("a hand written job with no heading falls back to its repo name",
          est["what"] == "hand-made" and est["size_hours"] is None, str(est))

    est = runner.estimate({"file": str(DATA / "gone.md"), "job_id": "gone",
                           "repo_name": "gone-repo"})
    check("a job file that has gone does not crash the estimate",
          est["what"] == "gone-repo" and est["size_hours"] is None
          and est["build_min"] > 0, str(est))

    queue("f-six", "i6", one_liner="word " * 120)
    est = runner.estimate(pending_job("f-six"))
    check("a very long one-liner is cut to one readable line",
          len(est["what"]) <= 200 and "\n" not in est["what"],
          str(len(est["what"])))


def test_ship_is_timed() -> None:
    print("the publishing chain leaves a record of how long it took")
    fresh()
    real = runner.ship.ship
    runner.ship.ship = lambda workdir, job, public=True: {
        "ok": True, "stage": "publish",
        "publish": {"url": "https://example.invalid/x"}}
    try:
        d = {"job_id": "s-one", "directory": str(DATA / "builds" / "s-one"),
             "repo": "s-one"}
        out: list = []
        runner._ship_one(d, False, out, threading.Lock())
    finally:
        runner.ship.ship = real
    st = runner.read_state("s-one")
    check("the start of the chain is kept",
          float(st.get("ship_started") or 0) > 0, str(st))
    check("and sits before the end of it",
          float(st.get("shipped_at") or 0) >= float(st.get("ship_started") or 0),
          str(st))
    check("while the in-progress marker is still cleared",
          st.get("shipping") == 0, str(st))


# --- the card ----------------------------------------------------------------
def test_offer() -> None:
    print("the queue is offered as one card")
    fresh()
    for i, jid in enumerate(["a-one", "b-two", "c-three"]):
        queue(jid, f"item{i}")
    q = runner.offer_queue()
    check("a card is asked", isinstance(q, dict) and bool(q), repr(q))
    q = q or {}
    check("it is the queue card",
          q.get("job_id") == "build-queue" and q.get("kind") == "queue"
          and q.get("id") == QID, str(q)[:300])
    check("answered with all or none",
          q.get("options") == ["all", "none"], str(q.get("options")))
    projects = q.get("projects") or []
    check("every queued project is on it, numbered in order",
          [p.get("n") for p in projects] == [1, 2, 3]
          and [p.get("job_id") for p in projects]
          == ["a-one", "b-two", "c-three"], str(projects)[:400])
    want = runner.estimate(pending_job("a-one"))
    first = projects[0] if projects else {}
    check("each one carries its repo, what it is, and its estimate",
          first.get("repo") == "a-one" and first.get("what") == want["what"]
          and first.get("minutes") == want["total_min"]
          and first.get("size_hours") == want["size_hours"], str(first))
    check("three at once is one batch, so all of them take as long as one",
          q.get("total_min") == want["total_min"], str(q.get("total_min")))
    check("and there is exactly one card on disk",
          len(cards()) == 1 and not cards()[0].get("answered_at"),
          str(cards())[:300])

    text = questions.render()
    check("the printed card names every project with a number",
          all(s in text for s in ("[1] a-one", "[2] b-two", "[3] c-three")),
          text[:600])
    check("and gives each one a time", text.count("about ") >= 4, text[:600])

    again = runner.offer_queue() or {}
    check("offering again does not make a second card",
          len(cards()) == 1 and again.get("asked_count") == 2,
          str(cards())[:300])

    queue("d-four", "item3")
    four = runner.offer_queue() or {}
    check("a newly queued project joins the same card",
          len(cards()) == 1
          and [p.get("job_id") for p in four.get("projects") or []]
          == ["a-one", "b-two", "c-three", "d-four"], str(four)[:400])
    check("four projects three at a time is two batches",
          four.get("total_min") == 2 * want["total_min"],
          str(four.get("total_min")))
    wide = runner.offer_queue(at_once=4) or {}
    check("and all four at once would be one",
          wide.get("total_min") == want["total_min"], str(wide.get("total_min")))


def test_offer_same_rules() -> None:
    print("the card offers exactly what a build would take")
    fresh()
    for i, jid in enumerate(["a-done", "b-running", "c-failed", "d-skipped",
                             "e-twin", "f-plain", "g-blocked"]):
        queue(jid, f"item{i}")
    ran("a-done", state="done", started=0.0, finished=60.0)
    ran("b-running", state="running", started=time.time())
    ran("c-failed", state="failed", attempts=2)
    questions.ask("c-failed", "build_failed", "it keeps failing", "x")
    questions.ask("d-skipped", "build_failed", "it keeps failing", "x")
    questions.answer("d-skipped.build_failed", "skip - stop trying this one")
    queue("z-older", "item4", folder=jobs.DONE)
    ran("z-older", state="done", started=0.0, finished=60.0)
    ran("g-blocked", state="blocked")
    questions.ask("g-blocked", "agent_down", "codex was down", "x")

    q = runner.offer_queue() or {}
    offered = [p.get("job_id") for p in q.get("projects") or []]
    check("done, running, failed-and-waiting, skipped and already built "
          "projects are left off", offered == ["f-plain", "g-blocked"],
          str(offered))
    runner.run_pending(limit=10)
    check("and a build run takes exactly the same ones",
          sorted(started) == offered, str(started))


def test_offer_answered_waits() -> None:
    print("an answer nobody has read yet is not asked over")
    fresh()
    queue("a-one", "i1")
    queue("b-two", "i2")
    q = runner.offer_queue() or {}
    questions.answer(q.get("id", QID), "all")
    r = runner.offer_queue() or {}
    check("the answered card is handed back as it is",
          r.get("answer") == "all" and r.get("answered_at"), str(r)[:300])
    on_disk = cards()
    check("and the answer is still on disk, on the only card",
          len(on_disk) == 1 and on_disk[0].get("answer") == "all",
          str(on_disk)[:300])


def test_offer_empty() -> None:
    print("an empty queue takes its card down")
    fresh()
    queue("a-one", "i1")
    runner.offer_queue()
    ran("a-one", state="done", started=0.0, finished=60.0)
    r = runner.offer_queue()
    check("nothing left to build gives no card", r is None, repr(r))
    check("and the open card is cleared", cards() == [], str(cards())[:300])

    fresh()
    r = runner.offer_queue()
    check("an empty queue never asks at all", r is None and cards() == [],
          repr(r))

    fresh()
    queue("a-one", "i1")
    q = runner.offer_queue() or {}
    questions.answer(q.get("id", QID), "none")
    ran("a-one", state="done", started=0.0, finished=60.0)
    r = runner.offer_queue()
    check("an answered card is left for the next read even then",
          r is None and len(cards()) == 1
          and cards()[0].get("answer") == "none", str(cards())[:300])


# --- reading the answer ------------------------------------------------------
def _asked(*jids: str) -> dict:
    fresh()
    for i, jid in enumerate(jids):
        queue(jid, f"item{i}")
    return runner.offer_queue() or {}


def test_consent() -> None:
    print("reading what I said")
    fresh()
    nothing = {"answered": False, "choice": "", "job_ids": []}
    check("no card means no answer", runner.consented() == nothing,
          str(runner.consented()))

    _asked("a-one", "b-two", "c-three")
    check("an open card is not an answer either",
          runner.consented() == nothing and len(cards()) == 1,
          str(cards())[:200])

    questions.answer(QID, "all")
    got = runner.consented()
    check("all means every project on the card",
          got == {"answered": True, "choice": "all",
                  "job_ids": ["a-one", "b-two", "c-three"]}, str(got))
    check("the answer is consumed once read", cards() == [],
          str(cards())[:200])
    check("so reading again finds nothing", runner.consented() == nothing,
          str(runner.consented()))

    _asked("a-one", "b-two", "c-three")
    questions.answer(QID, "none")
    got = runner.consented()
    check("none means none",
          got == {"answered": True, "choice": "none", "job_ids": []}, str(got))
    check("and is consumed too", cards() == [], str(cards())[:200])

    _asked("a-one", "b-two", "c-three")
    questions.answer(QID, "one", picked=["b-two"])
    got = runner.consented()
    check("one picked project is that one",
          got["job_ids"] == ["b-two"] and got["choice"] == "one", str(got))

    _asked("a-one", "b-two", "c-three")
    questions.answer(QID, "few", picked=["c-three", "a-one"])
    got = runner.consented()
    check("a few picked come back in queue order",
          got["job_ids"] == ["a-one", "c-three"], str(got))

    _asked("a-one", "b-two", "c-three")
    ran("c-three", state="done", started=0.0, finished=60.0)
    questions.answer(QID, "few", picked=["b-two", "c-three", "no-such-job"])
    got = runner.consented()
    check("a pick that was built meanwhile, or never existed, is dropped",
          got["job_ids"] == ["b-two"], str(got))

    _asked("a-one", "b-two")
    queue("c-three", "item9")
    questions.answer(QID, "all")
    got = runner.consented()
    check("all never reaches a project queued after the card was asked",
          got["job_ids"] == ["a-one", "b-two"], str(got))

    _asked("a-one", "b-two")
    questions.answer(QID, "one")
    got = runner.consented()
    check("a pick with nothing ticked builds nothing",
          got["answered"] and got["job_ids"] == [], str(got))

    # Answering from a terminal: the numbers are the ones printed on the card.
    _asked("a-one", "b-two", "c-three")
    ticked = questions.pick_ids(QID, ["3", "[1]", "b-two"])
    check("typed card numbers and ids both become job ids",
          ticked == ["c-three", "a-one", "b-two"], str(ticked))
    questions.answer(QID, "some", picked=questions.pick_ids(QID, ["2"]))
    got = runner.consented()
    check("and some with them builds just those",
          got["job_ids"] == ["b-two"], str(got))


def test_ci_line() -> None:
    print("what CI said after a push")
    check("a red run says so", runner.ci_line(
        {"checked": True, "ok": False, "conclusion": "failure", "url": "u"})
        == "CI FAILED (failure) u")
    check("a green one too", runner.ci_line(
        {"checked": True, "ok": True, "url": "u"}, with_url=False) == "CI passed")
    check("and one that was never checked says why", runner.ci_line(
        {"checked": False, "why": "the project has no workflow"})
        == "CI not checked: the project has no workflow")


# --- building what was agreed ------------------------------------------------
def test_run_pending_only() -> None:
    print("a build run can be held to named jobs")
    fresh()
    for i, jid in enumerate(["a-one", "b-two", "c-three", "d-four"]):
        queue(jid, f"item{i}")
    runner.run_pending(limit=3, only=["b-two", "d-four"])
    check("only the named ones are built", sorted(started) == ["b-two", "d-four"],
          str(started))

    fresh()
    for i, jid in enumerate(["a-one", "b-two", "c-three", "d-four"]):
        queue(jid, f"item{i}")
    runner.run_pending(limit=3, only=[])
    check("an empty list builds nothing", started == [], str(started))

    ran("c-three", state="failed", attempts=2)
    questions.ask("c-three", "build_failed", "it keeps failing", "x")
    ran("a-one", state="done", started=0.0, finished=60.0)
    runner.run_pending(limit=3, only=["a-one", "c-three"])
    check("naming a job does not get it past a rule that skips it",
          started == [], str(started))

    fresh()
    for i, jid in enumerate(["a-one", "b-two", "c-three", "d-four"]):
        queue(jid, f"item{i}")
    runner.run_pending(limit=3)
    check("with no list it still builds the first three it may",
          sorted(started) == ["a-one", "b-two", "c-three"], str(started))

    fresh()
    queue("a-one", "i1")
    queue("one", "i2")
    runner.run_pending(limit=3, only="a-one")
    check("a single id given as text is not matched as a substring",
          started == ["a-one"], str(started))


def test_run_consented() -> None:
    print("building what was agreed, a batch at a time")
    fresh()
    ids = ["j%d" % i for i in range(1, 8)]
    for i, jid in enumerate(ids):
        queue(jid, f"item{i}")
    DELAY["s"] = 0.2
    out = runner.run_consented(ids + ["j1", "j3"], at_once=3)
    check("every agreed job is built exactly once",
          sorted(started) == sorted(ids) and len(started) == len(ids),
          str(started))
    check("and each one gives back a result",
          len(out) == len(ids) and all(r.get("state") == "done" for r in out),
          str(out)[:300])
    check("never more than three at the same time", _live["most"] <= 3,
          str(_live))
    check("and a batch really runs together", _live["most"] == 3, str(_live))

    fresh()
    ids = ["k%d" % i for i in range(1, 6)]
    for i, jid in enumerate(ids):
        queue(jid, f"item{i}")
    DELAY["s"] = 0.2
    runner.run_consented(ids, at_once=2)
    check("two at a time means two at a time",
          _live["most"] == 2 and sorted(started) == ids, str(_live))

    fresh()
    for i, jid in enumerate(["a-one", "b-two", "c-three"]):
        queue(jid, f"item{i}")
    ran("b-two", state="failed", attempts=2)
    questions.ask("b-two", "build_failed", "it keeps failing", "x")
    out = runner.run_consented(["a-one", "b-two", "c-three", "no-such-job"])
    check("a job waiting on a failed-build answer is still skipped",
          sorted(started) == ["a-one", "c-three"], str(started))
    check("and an id that is not queued is ignored", len(out) == 2,
          str(out)[:300])

    fresh()
    queue("a-one", "i1")
    done = threading.Event()

    def zero() -> None:
        runner.run_consented(["a-one"], at_once=0)
        done.set()

    threading.Thread(target=zero, daemon=True).start()
    check("a batch size of zero still finishes", done.wait(5),
          "run_consented(at_once=0) was still going after 5 seconds")


def test_wording() -> None:
    print("what a blocked build tells me")
    fresh()
    log = DATA / "blocked.log"
    log.write_text("Error: rate limit exceeded\n", encoding="utf-8")
    runner._failed("w-one", "parser", "codex", log, 1, 0)
    q = next((q for q in questions.all_questions()
              if q.get("kind") == "agent_down"), {})
    words = " ".join([q.get("detail", "")] + list(q.get("options") or []))
    check("it waits for the next sync",
          "wait - leave it queued for the next sync" in (q.get("options") or [])
          and "next sync" in q.get("detail", ""), words[:400])
    check("and no longer talks about a morning schedule",
          "9am" not in words and "morning" not in words.lower(), words[:400])
    # Every choice has to do something different. "claude cloud" built on
    # this machine like "claude", so it is gone.
    check("the choices are wait or claude here, nothing that promises a cloud",
          [o.split(" - ")[0] for o in q.get("options") or []] == ["wait", "claude"]
          and "cloud" not in words.lower(), str(q.get("options")))

    # "look" counted as retry, so the chain ran again whether or not anything
    # had been fixed. A publish that keeps failing offers skip or retry.
    real = runner.ship.ship
    runner.ship.ship = lambda workdir, job, public=True: {
        "ok": False, "stage": "review", "why": "blocking",
        "review": {"summary": "no", "blocking": ["x"]}}
    try:
        d = {"job_id": "s-one", "directory": str(DATA / "builds" / "s-one"),
             "ship_attempts": runner.FAIL_LIMIT - 1}
        Path(d["directory"]).mkdir(parents=True, exist_ok=True)
        runner._ship_one(d, True, [], threading.Lock())
    finally:
        runner.ship.ship = real
    sq = next((x for x in questions.all_questions() if x.get("kind") == "ship_failed"), {})
    check("a publish that keeps failing offers skip or retry, and no look",
          [o.split(" - ")[0] for o in sq.get("options") or []] == ["skip", "retry"]
          and "fix it" in sq.get("detail", ""), str(sq)[:300])


def test_flow() -> None:
    print("offer, answer, build, offer again")
    q = _asked("a-one", "b-two", "c-three")
    questions.answer(q.get("id", QID), "few", picked=["a-one", "c-three"])
    agreed = runner.consented()
    runner.run_consented(agreed["job_ids"], at_once=3)
    check("what was picked is what got built",
          sorted(started) == ["a-one", "c-three"], str(started))
    left = runner.offer_queue() or {}
    check("and the next offer is for whatever is left",
          [p.get("job_id") for p in left.get("projects") or []] == ["b-two"]
          and len(cards()) == 1, str(left)[:300])


def run(test) -> None:
    """One test that crashes is one failure, not the end of the whole run."""
    try:
        test()
    except Exception as e:
        check("%s ran to the end" % test.__name__, False,
              "%s: %s" % (type(e).__name__, e))


def main() -> int:
    for test in (test_ask_extra, test_answer_picked, test_estimate_defaults,
                 test_estimate_history, test_estimate_what, test_ship_is_timed,
                 test_offer, test_offer_same_rules, test_offer_answered_waits,
                 test_offer_empty, test_consent, test_ci_line, test_run_pending_only,
                 test_run_consented, test_wording, test_flow):
        run(test)
    print()
    print("%d/%d pass" % (sum(results), len(results)))
    if all(results):
        shutil.rmtree(DATA, ignore_errors=True)
    else:
        print("test data kept for a look: %s" % DATA)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
