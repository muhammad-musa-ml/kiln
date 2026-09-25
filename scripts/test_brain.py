"""Claude's follow-up does what the plan says, and only what the rules allow.

Claude is never called. claude_cli.run is replaced by a stub that answers
as the planner, a worker, a reader or the final step, depending on which
shape it was asked for, and records every call so the order and the models
can be checked. Everything else is real: the database, the artifact writer,
the sections, the playbook and the search index, all in a temp folder.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="kiln-brain-")
os.environ["KILN_DATA"] = TMP
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import config  # noqa: E402

if str(config.DATA) != TMP:
    raise SystemExit("data dir pin did not take: %s" % config.DATA)

from kiln import brain, claude_cli, handoff, questions, store  # noqa: E402

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(bool(passed))
    print(("  ok    " if passed else "  FAIL  ") + label
          + (("\n        " + detail) if detail and not passed else ""))


# ---------------------------------------------------------------------------
# A stand-in for Claude
# ---------------------------------------------------------------------------
class Stub:
    def __init__(self):
        self.calls: list[dict] = []
        self.plans: list[dict] = []
        self.final: dict | None = None
        self.worker = {}          # task goal keyword -> callable(cwd) -> data
        self.block_at = ""        # "planner" | "worker" | "final"
        self.fail_goal = ""

    def __call__(self, prompt, *, model, effort, cwd, kits=(), schema=None, timeout=0):
        cwd = Path(cwd)
        who = {id(brain.PLAN_SCHEMA): "planner", id(brain.WORKER_SCHEMA): "worker",
               id(brain.READ_SCHEMA): "reader", id(brain.FINAL_SCHEMA): "final"}.get(id(schema), "?")
        # Its own entry, not calls[-1]: tasks run in threads, and the last
        # entry by the time this one finishes can be another task's.
        entry = {"who": who, "model": model, "effort": effort, "kits": kits,
                 "cwd": str(cwd), "prompt": prompt, "t": time.time(),
                 "inputs": sorted(p.relative_to(cwd).as_posix()
                                  for p in (cwd / "inputs").rglob("*") if p.is_file())
                 if (cwd / "inputs").exists() else [],
                 "media": sorted(p.name for p in (cwd / "media").glob("*"))
                 if (cwd / "media").exists() else [],
                 "input_text": " ".join(p.read_text(encoding="utf-8")
                                        for p in (cwd / "inputs").glob("*/result.json"))
                 if (cwd / "inputs").exists() else ""}
        self.calls.append(entry)
        claude_cli.check_model(model, effort)     # the real rule, so a Fable call fails loudly
        r = self._answer(who, prompt, model, effort, cwd)
        entry["t_end"] = time.time()
        return r

    def _answer(self, who, prompt, model, effort, cwd):
        # A little time per call, so a task started before another ended shows up.
        time.sleep(0.05)
        r = claude_cli.Result(ok=True, model=model, effort=effort, seconds=0.01)
        if self.block_at == who:
            return claude_cli.Result(ok=False, model=model, effort=effort,
                                     blocked="usage limit reached", error="usage limit")
        if who == "planner":
            r.data = self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]
        elif who == "worker":
            goal = prompt.split("YOUR TASK", 1)[1].splitlines()[1]
            if self.fail_goal and self.fail_goal in goal:
                return claude_cli.Result(ok=False, model=model, effort=effort,
                                         error="the worker broke")
            fn = next((f for k, f in self.worker.items() if k in goal), None)
            r.data = fn(cwd) if fn else {"done": "fully", "summary": "did it",
                                         "findings": "found things", "sources": [],
                                         "files": [], "could_not": []}
        elif who == "reader":
            r.data = {"title": "Five AI startups hiring now", "hook": "who is hiring",
                      "kind": "job", "summary": "A reel naming five companies.",
                      "sections": [{"heading": "Acme", "detail": "hiring interns"}],
                      "onscreen_text": ["Acme", "Globex"], "links": [], "entities": [],
                      "spoken_transcript": "", "code_snippets": [], "action_hint": "apply",
                      "topics": ["jobs"], "open_questions": [],
                      "could_not": ["no audio"]}
        elif who == "final":
            r.data = self.final(cwd) if callable(self.final) else self.final
        return r


STUB = Stub()
claude_cli.run = STUB
brain.claude_cli.run = STUB

# No network anywhere in this file: every link handed to the link checker
# comes back alive, without a request being made.
from kiln import enrich as _enrich  # noqa: E402
_enrich.resolve_links = lambda links, **kw: [dict(l, alive=True, status=200) for l in links]


def jpg(path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (200, 80, 20)).save(path, "JPEG")


def make_item(conn, iid, *, do="", note=True, group="", media=0, processed=True,
              kind="listicle", topics=("jobs",)):
    mdir = Path(TMP) / "media" / iid
    for n in range(media):
        jpg(mdir / ("%s_%02d.jpg" % (iid, n + 1)))
    rec = {"id": iid, "url": "https://example.com/p/%s" % iid, "title": "11 AI Startup Jobs",
           "hook": "", "summary": "a post", "kind": kind, "user_do": do,
           "status": "triage", "action": "reference",
           "media_dir": str(mdir) if media else "",
           "slide_count": media, "created_at": time.time(),
           "processed_at": time.time() if processed else None,
           "note_json": json.dumps({"title": "11 AI Startup Jobs", "summary": "a post",
                                    "sections": [{"heading": "one", "detail": "Acme"}],
                                    "_caption": "caption naming Acme and Globex"}
                                   if note else {}),
           "enrich_json": json.dumps({"_enricher": "generic", "answered": "partly",
                                      "followups": [{"do": "make the PDF", "why": "asked",
                                                     "blocked_by": "cannot write files"}]})}
    store.upsert_item(conn, rec)
    store.set_tags(conn, iid, "topic", list(topics))
    if group:
        store.set_tags(conn, iid, "user", ["group:" + group])
    return rec


def reset_db():
    p = Path(config.DB_PATH)
    for suffix in ("", "-wal", "-shm"):
        q = Path(str(p) + suffix)
        if q.exists():
            q.unlink()
    for f in handoff.PENDING.glob("*.json"):
        f.unlink()
    for f in questions.QUESTIONS.glob("*.json"):
        f.unlink()
    STUB.__init__()


def good_plan(ids, **kw):
    plan = {"verdict": "work", "why": "the PDF he asked for does not exist yet",
            "tasks": [
                {"id": "t1", "kind": "work", "goal": "research the companies",
                 "items": [ids[0]], "model": "claude-sonnet-5", "effort": "medium",
                 "tools": ["web"], "depends_on": [], "brief": "find each company's site"},
                {"id": "t2", "kind": "work", "goal": "write the document",
                 "items": [], "model": "claude-haiku-4-5-20251001", "effort": "low",
                 "tools": ["write"], "depends_on": ["t1"],
                 "brief": "write out/companies.md from t1"}],
            "final": {"model": "claude-opus-5-5", "effort": "high",
                      "brief": "answer and deliver the PDF"},
            "new_sections": [{"path": ["to watch", "Job leads"], "about": "companies hiring"}],
            "filing": [{"item": ids[0], "sections": [["to watch", "Job leads"]]}]}
    plan.update(kw)
    return plan


WRONG = "https://www.youtube.com/watch?v=T9arN5JKmL8"
RIGHT = "https://www.youtube.com/watch?v=T9aRN5JkmL8"


def final_for(ids, artifact="inputs/t2/out/companies.md"):
    def build(cwd: Path):
        items = []
        for i in ids:
            first = i == ids[0]
            items.append({"id": i, "answer": "Acme hires interns. Globex is closed. zebraword",
                          "answered": "fully", "missing": "", "retry_later": False,
                          "title": "Eleven AI startups and where to apply" if first else "",
                          "hook": "", "summary": "",
                          "artifacts": ([{"file": artifact, "title": "Companies",
                                          "about": "sites and links", "pdf": True}]
                                        if first and artifact else []),
                          "sources": [{"url": "https://acme.example/careers", "title": "Acme"},
                                      {"url": "not a url", "title": "junk"}],
                          "extra_sections": [],
                          "extra_links": [{"url": RIGHT, "label": "the real video"}] if first else [],
                          "drop_links": [{"url": WRONG, "why": "misread id"}] if first else [],
                          "next_action": "apply to Acme"})
        return {"items": items,
                "lessons": [{"kind": "listicle", "topics": ["jobs"],
                             "lesson": "For hiring carousels, search each company by name with careers."},
                            {"kind": "listicle", "topics": [], "lesson": "check acme.com first"}]}
    return build


def test_check_plan():
    print("a plan is checked before anything runs")
    ids = ["a", "b"]
    ok = good_plan(ids)
    check("a sound plan has no problems", brain.check_plan(ok, ids, set(), set()) == [],
          str(brain.check_plan(ok, ids, set(), set())))

    def probs(**kw):
        p = json.loads(json.dumps(ok))
        for k, v in kw.items():
            if k.startswith("t1_"):
                p["tasks"][0][k[3:]] = v
            else:
                p[k] = v
        return brain.check_plan(p, ids, set(), set())

    check("a Fable model is refused", any("Fable" in x for x in probs(t1_model="claude-fable-5-1")))
    check("an unknown model is refused", any("not an allowed model" in x
                                             for x in probs(t1_model="gpt-5")))
    check("an unknown effort is refused", any("effort" in x for x in probs(t1_effort="huge")))
    check("an unknown item is refused", any("unknown items" in x for x in probs(t1_items=["zzz"])))
    check("a task cannot depend on itself", any("depends on" in x
                                                for x in probs(t1_depends_on=["t1"])))
    cyc = json.loads(json.dumps(ok))
    cyc["tasks"][0]["depends_on"] = ["t2"]
    check("a circle of dependencies is refused",
          any("circle" in x for x in brain.check_plan(cyc, ids, set(), set())))
    many = json.loads(json.dumps(ok))
    many["tasks"] = [dict(ok["tasks"][0], id="t%d" % i) for i in range(brain.MAX_TASKS + 1)]
    check("more tasks than the cap is refused",
          any("limit" in x for x in brain.check_plan(many, ids, set(), set())))
    check("a Fable final step is refused",
          any("final step" in x for x in probs(final={"model": "claude-fable-5", "effort": "max",
                                                      "brief": "x"})))
    check("filing into a section that does not exist is refused",
          any("filing path" in x for x in probs(new_sections=[])))
    check("an unread item with no read task is refused",
          any("need a task of kind read" in x for x in brain.check_plan(ok, ids, {"a"}, set())))
    rd = json.loads(json.dumps(ok))
    rd["tasks"][0]["kind"] = "read"
    check("a read of an item that already has one is refused",
          any("is a read" in x for x in brain.check_plan(rd, ids, set(), set())))
    nothing = {"verdict": "nothing_to_do", "why": "fine", "tasks": [],
               "final": {"model": "claude-haiku-4-5-20251001", "effort": "low", "brief": ""},
               "new_sections": [], "filing": []}
    check("nothing to do is a valid plan", brain.check_plan(nothing, ids, set(), set()) == [])


def test_check_final():
    print("the last step's answer is checked before anything is kept")
    fdir = Path(tempfile.mkdtemp(prefix="final-"))
    (fdir / "out").mkdir()
    (fdir / "out" / "ok.md").write_text("# ok\n", encoding="utf-8")
    (fdir / "out" / "run.exe").write_text("x", encoding="utf-8")
    outside = fdir.parent / ("secret-%s.md" % fdir.name)
    outside.write_text("private\n", encoding="utf-8")

    def entry(i, *files):
        return {"id": i, "answer": "", "answered": "fully", "missing": "",
                "retry_later": False, "title": "", "hook": "", "summary": "",
                "artifacts": [{"file": f, "title": "t", "about": "", "pdf": True}
                              for f in files],
                "sources": [], "extra_sections": [], "extra_links": [], "next_action": ""}
    ok = brain.check_final({"items": [entry("a", "out/ok.md")], "lessons": []}, ["a"], fdir)
    check("a file inside the folder is accepted", ok == [], str(ok))
    esc = brain.check_final({"items": [entry("a", "../" + outside.name)], "lessons": []},
                            ["a"], fdir)
    check("a path that climbs out of the folder is refused",
          any("not a path inside" in x for x in esc), str(esc))
    absolute = brain.check_final({"items": [entry("a", str(outside))], "lessons": []},
                                 ["a"], fdir)
    check("an absolute path elsewhere is refused",
          any("not a path inside" in x for x in absolute), str(absolute))
    gone = brain.check_final({"items": [entry("a", "out/nope.md")], "lessons": []}, ["a"], fdir)
    check("a file that does not exist is refused", any("does not exist" in x for x in gone))
    exe = brain.check_final({"items": [entry("a", "out/run.exe")], "lessons": []}, ["a"], fdir)
    check("a file of a kind that is never kept is refused",
          any("can be kept" in x for x in exe), str(exe))
    short = brain.check_final({"items": [entry("a")], "lessons": []}, ["a", "b"], fdir)
    check("an item with no entry is refused", any("no entry for items" in x for x in short))
    quiet = dict(entry("a"), answered="not asked")
    check("'not asked' is refused when he did ask",
          any("not asked" in x for x in brain.check_final(
              {"items": [quiet], "lessons": []}, ["a"], fdir, asked=True)))
    check("and allowed when he did not",
          brain.check_final({"items": [quiet], "lessons": []}, ["a"], fdir, asked=False) == [])
    odd = dict(entry("a"), action="redo")
    check("an action tag outside the list is refused, redo included",
          any("action" in x for x in brain.check_final(
              {"items": [odd], "lessons": []}, ["a"], fdir)))
    bare = dict(entry("a"), set_aside=True, set_aside_why=" ")
    check("setting research aside needs a reason",
          any("set_aside_why" in x for x in brain.check_final(
              {"items": [bare], "lessons": []}, ["a"], fdir)))
    fine = dict(entry("a"), action="learn", set_aside=True,
                set_aside_why="it took a setup guide for a job posting")
    check("and with a reason and a real tag it passes",
          brain.check_final({"items": [fine], "lessons": []}, ["a"], fdir) == [])


def test_set_aside_wrong_research():
    print("research that answered the wrong question comes off the page")
    from kiln import pipeline as pipeline_mod, publish
    reset_db()
    conn = store.connect()
    make_item(conn, "j", kind="tutorial")
    conn.execute("UPDATE items SET action='apply', enrich_json=?, note_json=? WHERE id='j'", (
        json.dumps({
            "_enricher": "job", "_subject": "Jarvis", "_meta": {"model": "m"},
            "role": "Senior Infrastructure Engineer", "company": "TypeSafe AI",
            "posting_urls": [{"url": "https://jobs.example/1"},
                             {"url": "https://post.example/a"}],
            "answer": "a job", "followups": [],
            "_install_preview": {"command": "pip install jobthing", "runnable": True},
            "_citations": [{"url": "https://jobs.example/1"}],
            "_link_health": [{"url": "https://jobs.example/1", "alive": True}]}),
        json.dumps({"title": "Jarvis", "summary": "a setup guide",
                    "sections": [{"heading": "one", "detail": "steps"}],
                    "links": [{"url": "https://post.example/a"}]})))
    store.set_tags(conn, "j", "action", ["apply"])
    store.set_links(conn, "j", [{"url": "https://post.example/a", "alive": True},
                                {"url": "https://jobs.example/1", "alive": True}])
    pipeline_mod.index(conn, "j")
    conn.commit()
    check("before: search finds the item by the wrong research",
          [i["id"] for i in store.list_items(conn, q="TypeSafe")] == ["j"])
    run_dir = Path(config.DATA) / "brain" / "setaside"
    fdir = run_dir / "final"
    (fdir / "out").mkdir(parents=True, exist_ok=True)
    final = {"items": [{"id": "j", "answer": "The setup, step by step.", "answered": "not asked",
                        "missing": "", "retry_later": False, "title": "", "hook": "",
                        "summary": "", "artifacts": [], "sources": [], "extra_sections": [],
                        "extra_links": [], "drop_links": [], "next_action": "",
                        "action": "learn", "set_aside": True,
                        "set_aside_why": "it took a setup guide for a job posting"}],
             "lessons": []}
    brain._store_final(conn, [store.get_item(conn, "j")], {"why": "wrong research"}, final,
                       {}, {}, run_dir, fdir, "u1")
    it = store.get_item(conn, "j")
    enr = it.get("enrich") or {}
    check("the job fields are off the item",
          not any(k in enr for k in ("role", "company", "posting_urls", "answer")), str(enr)[:200])
    check("but kept on it, whole, with the reason",
          (enr.get("_set_aside") or {}).get("fields", {}).get("company") == "TypeSafe AI"
          and "job posting" in (enr.get("_set_aside") or {}).get("why", ""), str(enr)[:300])
    check("and how it was made stays", enr.get("_enricher") == "job"
          and enr.get("_meta") == {"model": "m"})
    check("its install preview, citations and link checks go with it",
          not any(k in enr for k in ("_install_preview", "_citations", "_link_health"))
          and "_install_preview" in (enr.get("_set_aside") or {}).get("fields", {}),
          str(sorted(enr)))
    links = sorted(l["url"] for l in it.get("links") or [])
    check("the research's links come off, the post's own stays",
          links == ["https://post.example/a"], str(links))
    check("and search no longer finds it by the wrong research",
          store.list_items(conn, q="TypeSafe") == [], "still found")
    check("the action tag is corrected, in both places",
          it.get("action") == "learn" and (it.get("tags") or {}).get("action") == ["learn"],
          "%s %s" % (it.get("action"), (it.get("tags") or {}).get("action")))
    check("and the old one is on record", (it.get("claude") or {}).get("action_was") == "apply")
    pub = publish.public_item(it)
    check("the published copy has no trace of the job research",
          not any(k in (pub.get("enrich") or {}) for k in ("role", "company", "posting_urls"))
          and "TypeSafe" not in json.dumps(pub), json.dumps(pub)[:300])
    brain._store_final(conn, [store.get_item(conn, "j")], {"why": "again"}, final,
                       {}, {}, run_dir, fdir, "u2")
    again = (store.get_item(conn, "j").get("enrich") or {}).get("_set_aside") or {}
    check("a second set-aside keeps what the first one kept",
          (again.get("fields") or {}).get("company") == "TypeSafe AI", str(again)[:200])
    conn.close()


def test_command_line():
    print("the command line Claude is started with")
    cmd = claude_cli.command("claude", model="claude-sonnet-5", effort="medium", kits=("web",))
    check("safe mode and restricted mode are always on",
          "--safe-mode" in cmd and "--restricted" in cmd, " ".join(cmd))
    check("model and effort are passed through",
          cmd[cmd.index("--model") + 1] == "claude-sonnet-5"
          and cmd[cmd.index("--effort") + 1] == "medium")
    tools = cmd[cmd.index("--tools") + 1].split(",")
    check("the web kit adds search and fetch, and they are allowed up front",
          {"WebSearch", "WebFetch"} <= set(tools) and "--allowedTools" in cmd, str(tools))
    check("no shell of any kind", not ({"Bash", "PowerShell"} & set(tools)), str(tools))
    plain = claude_cli.command("claude", model="claude-haiku-4-5-20251001", effort="low")
    check("without the web kit nothing is allowed up front", "--allowedTools" not in plain)
    none = claude_cli.command("claude", model="claude-opus-5", effort="max", kits=None)
    check("the planner gets no tools at all", none[none.index("--tools") + 1] == "")
    try:
        claude_cli.command("claude", model="claude-fable-5-1", effort="max")
        check("a Fable model is refused at the command line", False)
    except claude_cli.Refused:
        check("a Fable model is refused at the command line", True)
    check("a usage limit reads as blocked, not broken",
          claude_cli.blocked_reason("Claude AI usage limit reached|1790000000") == "usage limit reached")
    check("an ordinary error does not", claude_cli.blocked_reason("bad JSON") == "")


def test_end_to_end():
    print("a unit is planned, worked, assembled and stored")
    reset_db()
    conn = store.connect()
    make_item(conn, "a", do="find their websites and put it all in a PDF", group="g1", media=2)
    make_item(conn, "b", do="find their websites and put it all in a PDF", group="g1")
    store.set_links(conn, "a", [{"url": WRONG, "label": "misread", "alive": True, "status": 200},
                                {"url": "https://example.com/keep", "label": "fine",
                                 "alive": True, "status": 200}])
    ids = ["a", "b"]
    STUB.plans = [good_plan(ids)]

    def writer(cwd: Path):
        (cwd / "out").mkdir(exist_ok=True)
        (cwd / "out" / "companies.md").write_text(
            "# Companies\n\n| Name | Site |\n|---|---|\n| Acme | https://acme.example |\n",
            encoding="utf-8")
        return {"done": "fully", "summary": "wrote it", "findings": "the table",
                "sources": [], "files": ["out/companies.md"], "could_not": []}
    STUB.worker = {"write the document": writer}
    STUB.final = final_for(ids)

    units = brain.needs_follow_up(conn)
    check("the two linked items are one unit", sorted(map(sorted, units)) == [["a", "b"]],
          str(units))
    out = brain.follow_up(units[0], conn=conn)
    check("the unit finished", out.get("state") == "done", json.dumps(out)[:400])
    printed = brain.render({"units": [out], "reads": [], "waiting": 1})
    check("the sync prints every item of the unit and the files by name",
          all(i in printed for i in out.get("items") or ["?"])
          and "companies" in printed and out.get("files"), printed)

    who = [c["who"] for c in STUB.calls]
    check("planner, two workers, then the final step",
          who == ["planner", "worker", "worker", "final"], str(who))
    check("the planner is Opus 5 at max effort",
          (STUB.calls[0]["model"], STUB.calls[0]["effort"]) == claude_cli.PLANNER)
    research = next(c for c in STUB.calls if "research the companies" in c["prompt"]
                    and c["who"] == "worker")
    writing = next(c for c in STUB.calls if "write the document" in c["prompt"]
                   and c["who"] == "worker")
    check("each worker ran on the model the plan named",
          (research["model"], writing["model"])
          == ("claude-sonnet-5", "claude-haiku-4-5-20251001"))
    check("no call used a Fable model", not any("fable" in c["model"] for c in STUB.calls))
    check("the writer started only after the research finished",
          writing["t"] >= research["t_end"],
          "writer began %.3f, research ended %.3f" % (writing["t"], research["t_end"]))
    check("and was handed the research as input",
          "inputs/t1/result.json" in writing["inputs"]
          and "found things" in writing["input_text"], writing["input_text"][:200])
    check("the research task was given the item's pictures",
          research["media"] == ["a-01.jpg", "a-02.jpg"], str(research["media"]))
    check("the owner's instruction reached the planner",
          "put it all in a PDF" in STUB.calls[0]["prompt"])

    a = store.get_item(conn, "a")
    b = store.get_item(conn, "b")
    c = a.get("claude") or {}
    check("both items are marked done", a["claude_state"] == "done" and b["claude_state"] == "done")
    check("the answer is stored", "Acme hires interns" in (c.get("answer") or ""))
    from kiln import publish
    page = publish.followup(a)
    check("and rendered for the page from what is stored",
          "<p>" in (page.get("answer_html") or "") and "answer_html" not in c,
          (page.get("answer_html") or "")[:80])
    arts = c.get("artifacts") or []
    check("the document was kept and turned into a PDF",
          len(arts) == 1 and arts[0].get("kind") == "pdf" and not arts[0].get("error"),
          json.dumps(arts)[:300])
    from kiln import artifacts
    pdf = artifacts.item_dir("a") / (arts[0]["file"] if arts else "missing.pdf")
    check("the PDF is on disk and says what the table said",
          pdf.is_file() and "acme.example" in artifacts.pdf_text(pdf).lower(), str(pdf))
    check("a source that is not a link was dropped",
          [s["url"] for s in c.get("sources") or []] == ["https://acme.example/careers"])
    check("the clickbait title was replaced", a["title"] == "Eleven AI startups and where to apply",
          a["title"])
    check("an empty correction keeps the old title", b["title"] == "11 AI Startup Jobs", b["title"])
    check("what was run is recorded on the item",
          [t["id"] for t in c.get("tasks") or []] == ["t1", "t2"]
          and c.get("planner") and c.get("final"))
    tree = {s["id"]: s for s in store.sections(conn)}
    check("the section he asked for exists, with its subsection",
          "to-watch" in tree and "to-watch/job-leads" in tree, str(list(tree)))
    check("and the item is filed in it",
          "to-watch/job-leads" in (a.get("tags") or {}).get("section", []))
    check("the instruction that made the section is kept privately",
          (conn.execute("SELECT asked FROM sections WHERE id='to-watch/job-leads'").fetchone()[0]
           or "").startswith("do:"))
    lessons = [l["lesson"] for l in store.lessons_for(conn, kinds=["listicle"], topics=["jobs"])]
    check("the lesson was learned", any("careers" in l for l in lessons), str(lessons))
    check("a lesson carrying a link was not", not any("acme.com" in l for l in lessons))
    found = [i["id"] for i in store.list_items(conn, q="zebraword")]
    check("search finds words that only appear in the answer", "a" in found, str(found))
    urls = [l["url"] for l in store.get_item(conn, "a")["links"]]
    check("a link shown to be wrong comes off the item", WRONG not in urls, str(urls))
    check("its correction, differing only in letter case, goes on", RIGHT in urls, str(urls))
    check("and the other links stay", "https://example.com/keep" in urls, str(urls))
    check("the dropped link is on record with its reason",
          (c.get("dropped_links") or [{}])[0].get("why") == "misread id")
    check("nothing is left needing a follow-up", brain.needs_follow_up(conn) == [])
    conn.close()


def test_refused_then_fixed():
    print("a refused plan is sent back with the reasons")
    reset_db()
    conn = store.connect()
    make_item(conn, "c", do="compare them")
    bad = good_plan(["c"])
    bad["tasks"][0]["model"] = "claude-fable-5-1"
    STUB.plans = [bad, good_plan(["c"])]
    STUB.final = final_for(["c"], artifact="inputs/t2/out/x.md")

    def writer(cwd: Path):
        (cwd / "out").mkdir(exist_ok=True)
        (cwd / "out" / "x.md").write_text("# X\n\ntext\n", encoding="utf-8")
        return {"done": "fully", "summary": "", "findings": "", "sources": [],
                "files": ["out/x.md"], "could_not": []}
    STUB.worker = {"write the document": writer}
    out = brain.follow_up(["c"], conn=conn)
    planners = [x for x in STUB.calls if x["who"] == "planner"]
    check("the planner was asked twice", len(planners) == 2, str(len(planners)))
    check("the second time it was told why", "REFUSED" in planners[1]["prompt"]
          and "Fable" in planners[1]["prompt"])
    check("the Fable task never ran", not any("fable" in x["model"] for x in STUB.calls
                                              if x["who"] != "planner"))
    check("and the fixed plan did", out.get("state") == "done", json.dumps(out)[:300])
    conn.close()


def test_blocked_and_failed():
    print("running out of Claude is not the same as breaking")
    reset_db()
    conn = store.connect()
    make_item(conn, "d", do="find the posting")
    STUB.plans = [good_plan(["d"])]
    STUB.block_at = "planner"
    out = brain.follow_up(["d"], conn=conn)
    d = store.get_item(conn, "d")
    check("a usage limit leaves the unit blocked", out.get("state") == "blocked"
          and d["claude_state"] == "blocked", json.dumps(out)[:200])
    check("and does not count as an attempt", int(d.get("claude_attempts") or 0) == 0)
    check("it is picked up again next time", ["d"] in brain.needs_follow_up(conn))

    STUB.block_at = "worker"
    out = brain.follow_up(["d"], conn=conn)
    check("a limit hit part way stops before the final step",
          out.get("state") == "blocked" and not any(c["who"] == "final" for c in STUB.calls),
          str([c["who"] for c in STUB.calls]))

    STUB.__init__()
    STUB.plans = [{"verdict": "work", "why": "x", "tasks": [], "final": good_plan(["d"])["final"],
                   "new_sections": [], "filing": []}]
    out = brain.follow_up(["d"], conn=conn)
    d = store.get_item(conn, "d")
    check("a plan that stays broken is a failure", out.get("state") == "failed"
          and d["claude_state"] == "failed", json.dumps(out)[:200])
    check("which counts as an attempt", int(d.get("claude_attempts") or 0) == 1)
    conn.execute("UPDATE items SET claude_attempts=? WHERE id='d'", (brain.FAIL_LIMIT,))
    conn.commit()
    check("after the limit it stops being retried", ["d"] not in brain.needs_follow_up(conn))

    STUB.__init__()
    STUB.plans = [good_plan(["d"])]
    STUB.fail_goal = "research"
    STUB.final = final_for(["d"], artifact="inputs/t2/out/y.md")

    def writer(cwd: Path):
        (cwd / "out").mkdir(exist_ok=True)
        (cwd / "out" / "y.md").write_text("# Y\n", encoding="utf-8")
        return {"done": "partly", "summary": "", "findings": "", "sources": [],
                "files": ["out/y.md"], "could_not": ["no research came through"]}
    STUB.worker = {"write the document": writer}
    out = brain.follow_up(["d"], conn=conn)
    who = [c["who"] for c in STUB.calls]
    check("a broken task does not stop the ones after it",
          who == ["planner", "worker", "worker", "final"] and out.get("state") == "done",
          "%s %s" % (who, json.dumps(out)[:200]))
    check("and the final step is told it broke",
          "did not run" in next(c["prompt"] for c in STUB.calls if c["who"] == "final"))
    conn.close()


def test_nothing_to_do_and_selection():
    print("nothing to do, and deciding what needs a follow-up")
    reset_db()
    conn = store.connect()
    make_item(conn, "e", topics=("rag",))
    STUB.plans = [{"verdict": "nothing_to_do", "why": "the read covers it", "tasks": [],
                   "final": {"model": "claude-haiku-4-5-20251001", "effort": "low", "brief": ""},
                   "new_sections": [{"path": ["to watch", "RAG"], "about": "retrieval videos"}],
                   "filing": [{"item": "e", "sections": [["to watch", "RAG"]]}]}]
    out = brain.follow_up(["e"], conn=conn)
    e = store.get_item(conn, "e")
    check("nothing to do is recorded as done", out.get("state") == "done"
          and (e.get("claude") or {}).get("verdict") == "nothing_to_do")
    check("with nothing asked, the answer is 'not asked'",
          (e.get("claude") or {}).get("answered") == "not asked")
    check("only the planner ran", [c["who"] for c in STUB.calls] == ["planner"])
    check("filing still happened", "to-watch/rag" in (e.get("tags") or {}).get("section", []))

    now = time.time()
    make_item(conn, "new-plain")
    make_item(conn, "new-asked", do="is this free")
    make_item(conn, "redo", note=False)
    conn.execute("UPDATE items SET action='redo' WHERE id='redo'")
    make_item(conn, "working")
    conn.execute("UPDATE items SET claude_state='working', claude_at=? WHERE id='working'", (now,))
    make_item(conn, "stale")
    conn.execute("UPDATE items SET claude_state='working', claude_at=? WHERE id='stale'",
                 (now - brain.STALE_AFTER - 60,))
    make_item(conn, "refired")
    conn.execute("UPDATE items SET claude_state='done', claude_at=?, processed_at=? "
                 "WHERE id='refired'", (now - 100, now))
    make_item(conn, "partial")
    conn.execute("UPDATE items SET claude_state='done', claude_at=?, processed_at=?, "
                 "claude_json=? WHERE id='partial'",
                 (now - brain.RETRY_AFTER - 60, now - brain.RETRY_AFTER - 120,
                  json.dumps({"answered": "partly", "retry_later": True})))
    make_item(conn, "partial-final")
    conn.execute("UPDATE items SET claude_state='done', claude_at=?, processed_at=?, "
                 "claude_json=? WHERE id='partial-final'",
                 (now - brain.RETRY_AFTER - 60, now - brain.RETRY_AFTER - 120,
                  json.dumps({"answered": "partly", "retry_later": False})))
    conn.commit()
    want = [u[0] for u in brain.needs_follow_up(conn, now=now)]
    check("an item with an instruction goes first", want and want[0] == "new-asked", str(want))
    check("new, stale, re-read and retry-later items are picked",
          {"new-plain", "stale", "refired", "partial"} <= set(want), str(want))
    check("done, running, redo and final partial ones are not",
          not ({"e", "working", "redo", "partial-final"} & set(want)), str(want))
    conn.close()


def test_unread_asks_first():
    print("an item no free model could read waits for a yes")
    reset_db()
    conn = store.connect()
    make_item(conn, "r", do="list the companies", note=False, media=3, kind="instagram")
    # What the pipeline really stores for a read that failed: action redo.
    conn.execute("UPDATE items SET summary='', action='redo' WHERE id='r'")
    store.set_tags(conn, "r", "action", ["redo"])
    conn.commit()
    handoff.write("r", url="https://example.com/p/r", stage="extract",
                  why="every rung out of quota", media=[], instruction="list the companies",
                  context="caption: Acme is hiring")
    out = brain.sweep(conn=conn)
    check("the first sync asks rather than reads", out.get("asked") and not STUB.calls,
          json.dumps(out)[:300])
    q = [x for x in questions.open_questions() if x.get("job_id") == brain.READ_ASK]
    check("as one question card with the choices", len(q) == 1 and len(q[0]["options"]) == 2,
          json.dumps(q)[:300])

    # "wait" first: the free models get fresh tries, and Claude reads nothing.
    conn.execute("UPDATE items SET attempts=3 WHERE id='r'")
    conn.commit()
    questions.answer(q[0]["id"], q[0]["options"][1])
    brain.sweep(conn=conn)
    check("wait gives the free models their tries back, and Claude reads nothing",
          int(store.get_item(conn, "r").get("attempts") or 0) == 0 and not STUB.calls)
    brain.sweep(conn=conn)
    q = [x for x in questions.open_questions() if x.get("job_id") == brain.READ_ASK]
    check("and the next sync asks again while the item is still unread",
          len(q) == 1 and not STUB.calls, json.dumps(q)[:200])

    questions.answer(q[0]["id"], q[0]["options"][0])
    plan = good_plan(["r"])
    plan["tasks"] = [{"id": "t1", "kind": "read", "goal": "read the reel", "items": ["r"],
                      "model": "claude-sonnet-5", "effort": "high", "tools": [],
                      "depends_on": [], "brief": "read every frame"}]
    plan["filing"] = []
    plan["new_sections"] = []
    STUB.plans = [plan]
    STUB.final = final_for(["r"], artifact="")
    STUB.final = (lambda cwd: {"items": [{"id": "r", "answer": "Acme, Globex",
                                          "answered": "fully", "missing": "",
                                          "retry_later": False, "title": "", "hook": "",
                                          "summary": "", "artifacts": [], "sources": [],
                                          "extra_sections": [], "extra_links": [],
                                          "next_action": ""}], "lessons": []})
    out = brain.sweep(conn=conn)
    who = [c["who"] for c in STUB.calls]
    check("after a yes, Claude reads it", who == ["planner", "reader", "final"], str(who))
    check("the planner was told it has no read", '"unread": true' in STUB.calls[0]["prompt"])
    check("the reader got the item's pictures", len(STUB.calls[1]["media"]) == 3,
          str(STUB.calls[1]["media"]))
    r = store.get_item(conn, "r")
    check("the read is stored as the item's note",
          (r.get("note") or {}).get("title") == "Five AI startups hiring now")
    check("marked as done by Claude", ((r.get("note") or {}).get("_meta") or {}).get("by") == "claude")
    check("and the follow-up finished", r["claude_state"] == "done"
          and (r.get("claude") or {}).get("answer") == "Acme, Globex")
    check("the question is gone", not [x for x in questions.open_questions()
                                       if x.get("job_id") == brain.READ_ASK])
    check("the brief no longer waits", not handoff.pending())
    check("and the item is no longer marked redo", r.get("action") != "redo"
          and (r.get("tags") or {}).get("action") != ["redo"], str(r.get("action")))
    conn.execute("UPDATE items SET claude_state='blocked' WHERE id='r'")
    conn.commit()
    check("so a later follow-up can still pick it up",
          ["r"] in brain.needs_follow_up(conn))
    conn.close()


def test_gate_keyword():
    print("the word to comment is the word, not the sentence around it")
    from kiln import extract
    cases = [("Comment PDF below and I will send the list", "PDF"),
             ("Comment 'AI TOOLS' below", "AI TOOLS"),
             ("DM me GUIDE to get it", "GUIDE"),
             ("Comment GUIDE and I'll send it", "GUIDE")]
    for caption, word in cases:
        g = extract.detect_gate(caption)
        check("%r -> %s" % (caption[:34], word), g.get("keyword") == word, str(g))
    check("a bare 'comment below' is not a gate",
          not extract.detect_gate("comment below and tell me").get("gated"))


def test_claude_read_stored_in_full():
    print("a read Claude did is stored the way a model's read is")
    reset_db()
    conn = store.connect()
    make_item(conn, "f", note=False, media=1, kind="instagram")
    conn.execute("UPDATE items SET note_json=? WHERE id='f'",
                 (json.dumps({"_caption": "Comment PDF below and I will send the list"}),))
    conn.commit()
    conn.close()
    handoff.write("f", url="https://example.com/p/f", stage="extract", why="out of quota")
    out = handoff.fill("f", {"title": "Where Acme is hiring", "summary": "Acme hires.",
                             "kind": "job", "action_hint": "apply", "topics": ["jobs"],
                             "sections": [{"heading": "Acme", "detail": "hiring"}],
                             "onscreen_text": ["Acme careers"],
                             "links": [{"url": "https://acme.example/careers",
                                        "where": "onscreen", "label": "careers"}]})
    conn = store.connect()
    it = store.get_item(conn, "f") or {}
    check("the read is stored", out.get("ok") and it.get("title") == "Where Acme is hiring",
          str(out))
    check("with the links it found, checked",
          [l["url"] for l in it.get("links") or []] == ["https://acme.example/careers"]
          and all(l.get("alive") for l in it.get("links") or []), str(it.get("links")))
    check("the comment gate is found from the caption the failed read kept",
          (it.get("gate") or {}).get("keyword") == "PDF", str(it.get("gate")))
    check("and search finds it by what the read found",
          [i["id"] for i in store.list_items(conn, q="Acme")] == ["f"])
    conn.close()


def test_one_yes_covers_the_list():
    print("one yes covers every item on the card, over as many passes as it takes")
    reset_db()
    conn = store.connect()
    ids = ["ra", "rb", "rc"]
    raw = 'HTTP 503 {\n  "error": {\n    "code": 503,\n    "message": "overloaded"}}'
    for iid in ids:
        make_item(conn, iid, note=False, media=1, kind="instagram")
        conn.execute("UPDATE items SET summary='', action='redo' WHERE id=?", (iid,))
        store.set_tags(conn, iid, "action", ["redo"])
        handoff.write(iid, url="https://example.com/p/" + iid, stage="extract",
                      why=raw, media=[],
                      tried=["gemini:gemini-3.8-flash FAIL HTTP 429 {quota}", "gemini:x FAIL " + raw])
    conn.commit()
    brain.sweep(conn=conn, limit=2)
    q = [x for x in questions.open_questions() if x.get("job_id") == brain.READ_ASK]
    check("the card lists all three and says how many a sync reads",
          len(q) == 1 and sorted(q[0].get("items") or []) == ids
          and "reads up to" in q[0].get("detail", ""), json.dumps(q)[:300])
    detail = (q[0].get("detail") if q else "") or ""
    check("each item's reason is one plain line, not the raw error",
          "free models were out of quota for the day, or were overloaded" in detail
          and '"error"' not in detail and "{" not in detail, detail[:400])

    def read_plan(iid):
        plan = good_plan([iid], filing=[], new_sections=[])
        plan["tasks"] = [{"id": "t1", "kind": "read", "goal": "read the reel",
                          "items": [iid], "model": "claude-sonnet-5", "effort": "high",
                          "tools": [], "depends_on": [], "brief": "read every frame"}]
        return plan

    def final_read(cwd):
        views = json.loads((Path(cwd) / "items.json").read_text(encoding="utf-8"))
        return {"items": [{"id": v["id"], "answer": "", "answered": "not asked",
                           "missing": "", "retry_later": False, "title": "", "hook": "",
                           "summary": "", "artifacts": [], "sources": [],
                           "extra_sections": [], "extra_links": [], "next_action": ""}
                          for v in views], "lessons": []}

    STUB.plans = [read_plan(i) for i in ids]
    STUB.final = final_read
    questions.answer(q[0]["id"], q[0]["options"][0])
    out = brain.sweep(conn=conn, limit=2)
    first = [r.get("items") for r in out.get("reads", [])]
    check("a yes reads as many as the pass has room for",
          first == [["ra"], ["rb"]], json.dumps(out)[:300])
    check("says the rest wait, and asks nothing new",
          "1 read(s) you said yes to wait" in brain.render(out) and not out.get("asked"),
          brain.render(out))
    out = brain.sweep(conn=conn, limit=2)
    second = [r.get("items") for r in out.get("reads", [])]
    check("the next pass reads the rest without a new card",
          second == [["rc"]] and not out.get("asked")
          and not [x for x in questions.open_questions() if x.get("job_id") == brain.READ_ASK],
          json.dumps(out)[:300])
    check("and forgets the yes once every item on it is read",
          brain._read_ok() == set(), str(brain._read_ok()))

    # By hand: no card, no yes on file. Typing the command is the yes.
    make_item(conn, "rh", note=False, media=1, kind="instagram")
    conn.execute("UPDATE items SET summary='', action='redo' WHERE id='rh'")
    store.set_tags(conn, "rh", "action", ["redo"])
    conn.commit()
    handoff.write("rh", url="https://example.com/p/rh", stage="extract",
                  why="every rung out of quota", media=[])
    STUB.plans = [read_plan("rh")]
    out = brain.run_by_hand(["rh"])
    check("running it by hand reads an item no free model could",
          out.get("state") == "done" and (store.get_item(conn, "rh").get("note") or {}).get("title"),
          json.dumps(out)[:300])
    conn.close()


def test_inbox_changes():
    print("a line that changes after it was read")
    reset_db()
    conn = store.connect()
    from kiln import acquire as acq_mod, extract as ex_mod, ingest
    from kiln.acquire import Acquired
    real = acq_mod.acquire, ex_mod.extract_item, _enrich.enrich_note
    acq_mod.acquire = lambda url, **kw: Acquired(url=url, kind="web", title="T", body_text="b")
    ex_mod.extract_item = lambda acq, **kw: {"kind": "news", "summary": "s",
                                             "sections": [{"heading": "h", "detail": "d"}]}
    _enrich.enrich_note = lambda *a, **kw: {"_meta": {"ok": True}}
    try:
        one = "https://example.com/one"
        two = "https://example.com/two"
        ingest.ingest_text(one + "\n", conn=conn)
        check("the first read happens", store.get_item(conn, store.item_id(one)) is not None)
        check("reading the same doc again finds nothing new",
              ingest.new_items(one + "\n", conn) == [])
        ingest.ingest_text(one + " " + two + "\n", conn=conn)
        check("a link added to the line later is read",
              store.get_item(conn, store.item_id(two)) is not None)
        got = store.get_item(conn, store.item_id(one))
        check("without the first one being read again", int(got.get("attempts") or 0) == 1,
              str(got.get("attempts")))
        tags = [(store.get_item(conn, store.item_id(u)).get("tags") or {}).get("user")
                for u in (one, two)]
        check("and the two now share a group, the first one included",
              tags[0] and tags[0] == tags[1] and tags[0][0].startswith("group:"), str(tags))
        conn.execute("UPDATE items SET claude_state='done' WHERE id=?", (store.item_id(one),))
        conn.commit()
        out = ingest.ingest_text(one + " " + two + " | put both in a PDF\n", conn=conn)
        got = store.get_item(conn, store.item_id(one))
        check("an instruction written under the links later reaches them",
              got.get("user_do") == "put both in a PDF"
              and any(r.get("status") == "instruction added" for r in out), str(out)[:200])
        check("and puts them back in line for the follow-up", got.get("claude_state") == "")
        conn.execute("UPDATE items SET user_do='my own words' WHERE id=?", (store.item_id(one),))
        conn.commit()
        ingest.ingest_text(one + " | something else\n", conn=conn)
        check("but never overwrites an instruction the item already has",
              store.get_item(conn, store.item_id(one)).get("user_do") == "my own words")
    finally:
        acq_mod.acquire, ex_mod.extract_item, _enrich.enrich_note = real
        conn.close()


def test_health_cards_listen():
    print("a health card remembers ignore, and asks again after looked")
    reset_db()
    from kiln import health
    f2 = [health._finding("ask", "2 item(s) stuck in the inbox for over a week",
                          key="stuck-inbox")]
    f3 = [health._finding("ask", "3 item(s) stuck in the inbox for over a week",
                          key="stuck-inbox")]
    health.raise_questions(f2)
    q = [x for x in questions.open_questions() if x.get("kind") == "health"]
    check("the finding becomes one card", len(q) == 1, json.dumps(q)[:200])
    questions.answer(q[0]["id"], q[0]["options"][1])        # ignore
    health.raise_questions(f3)
    check("ignore holds even after the count changes",
          not [x for x in questions.open_questions() if x.get("kind") == "health"])
    for f in questions.QUESTIONS.glob("*.json"):
        f.unlink()
    health.raise_questions(f2)
    q = [x for x in questions.open_questions() if x.get("kind") == "health"]
    questions.answer(q[0]["id"], q[0]["options"][0])        # looked
    health.raise_questions(f3)
    check("looked is asked again when the problem comes back",
          len([x for x in questions.open_questions() if x.get("kind") == "health"]) == 1)


def test_sweep_stops_and_survives():
    print("a sweep stops at the first wall, and never takes the sync down with it")
    reset_db()
    conn = store.connect()
    for iid in ("u1", "u2"):
        make_item(conn, iid, do="list them", note=False, media=1, kind="instagram")
        conn.execute("UPDATE items SET summary='' WHERE id=?", (iid,))
        handoff.write(iid, url="https://example.com/p/" + iid, stage="extract",
                      why="out of quota", media=[], instruction="list them")
    make_item(conn, "fine")
    conn.commit()
    brain.ask_to_read(brain.unread(conn))
    q = [x for x in questions.open_questions() if x.get("job_id") == brain.READ_ASK][0]
    questions.answer(q["id"], q["options"][0])
    STUB.block_at = "planner"
    out = brain.sweep(conn=conn)
    planners = [c for c in STUB.calls if c["who"] == "planner"]
    check("out of usage on the first read, nothing else is started",
          len(planners) == 1 and not out["units"], "%d planner calls, %d units"
          % (len(planners), len(out["units"])))

    STUB.__init__()
    real = brain.needs_follow_up
    brain.needs_follow_up = lambda conn, now=None: 1 / 0
    try:
        out = brain.sweep(conn=conn)
        check("an error inside the sweep comes back instead of raising",
              "ZeroDivisionError" in out.get("error", ""), json.dumps(out)[:200])
        check("and is printed", "stopped early" in brain.render(out))
    except Exception as e:
        check("an error inside the sweep comes back instead of raising", False,
              "%s: %s" % (type(e).__name__, e))
    finally:
        brain.needs_follow_up = real
    conn.close()


def test_first_pass_reports_and_lessons():
    print("the free models say what they could not do, and read the playbook")
    from kiln import enrich, extract, models, pipeline, search
    seen: list[str] = []

    def fake_generate(task, prompt, media=None, **kw):
        seen.append(prompt)
        n = len(seen)
        return models.ModelResult(ok=True, data={"queries": ["acme careers"]},
                                  provider="gemini", model="stub",
                                  tokens_in=100 * n, tokens_out=10 * n)
    real_gen, real_research = models.generate, search.research
    models.generate = fake_generate
    enrich.models.generate = fake_generate
    search.research = lambda qs: ("", [])
    try:
        enr = enrich.enrich_note({"title": "t", "kind": "listicle", "entities": []}, None,
                                 user_note="", lessons=["search each company with careers"])
    finally:
        models.generate = real_gen
        enrich.models.generate = real_gen
        search.research = real_research
    check("with lessons, queries are written even with nothing asked",
          any("search each company with careers" in p and "queries" in p for p in seen),
          str([p[:60] for p in seen]))
    final = seen[-1] if seen else ""
    check("every enrichment asks for followups and could_not",
          '"followups"' in final and '"could_not"' in final, final[-300:])
    check("and carries the lessons", "search each company with careers" in final)
    em = enr.get("_meta") or {}
    check("both calls record their tokens",
          (em.get("tokens_in"), em.get("tokens_out")) == (200, 20)
          and ((em.get("queries_call") or {}).get("tokens_in"),
               (em.get("queries_call") or {}).get("tokens_out")) == (100, 10), str(em))
    check("no sources fetched is said, not papered over",
          "No live sources could be fetched" in final
          and "Search the live web" not in final)
    check("the read asks what could not be made out", '"could_not"' in extract.PROMPT)
    merged = extract._union({"could_not": ["slide 3 blurred"]}, {"could_not": ["slide 9 cut"]})
    check("two reads keep both lists of what they missed",
          merged.get("could_not") == ["slide 3 blurred", "slide 9 cut"], str(merged))
    blank = models.ModelResult(ok=True, data={"title": "t", "summary": "s"})
    spoken = models.ModelResult(ok=True, data={"summary": "s", "spoken_transcript": "hi all"})
    check("one picture is held to the floor too", bool(extract._floor_for(1)(blank)))
    check("so is a reel, which can pass on its speech",
          bool(extract._floor_for(1, video=True)(blank))
          and not extract._floor_for(1, video=True)(spoken))
    check("a page with no media has no floor", extract._floor_for(0) is None)
    from kiln.acquire import Acquired
    many = Acquired(url="u", kind="instagram", slides=["s%d.jpg" % i for i in range(23)])
    ctx = extract._context_block(many)
    check("a carousel longer than a read holds is told which slides it got",
          len(extract._media_for(many)) == 20 and "first 20" in ctx and "last 3" in ctx,
          ctx[:200])
    eighteen = Acquired(url="u", kind="instagram", slides=["s%d.jpg" % i for i in range(18)])
    check("and an eighteen-slide one is sent all eighteen",
          len(extract._media_for(eighteen)) == 18
          and "Cover every slide." in extract._context_block(eighteen))

    print("re-firing and retrying")
    reset_db()
    conn = store.connect()
    # Real ids: process_url keys an item by a hash of its url.
    ug, uh, uk = ("https://example.com/p/%s" % x for x in "ghk")
    gid, hid, kid = store.item_id(ug), store.item_id(uh), store.item_id(uk)
    store.upsert_item(conn, {"id": gid, "url": ug, "title": "G",
                             "processed_at": time.time()})
    store.set_tags(conn, gid, "user", ["group:gg"])
    from kiln import acquire as acq_mod, extract as ex_mod
    from kiln.acquire import Acquired
    real_acq, real_ext = acq_mod.acquire, ex_mod.extract_item
    real_enrich = enrich.enrich_note
    acq_mod.acquire = lambda url, **kw: Acquired(url=url, kind="web", title="T", body_text="b")
    ex_mod.extract_item = lambda acq, **kw: {"kind": "news", "summary": "s",
                                             "sections": [{"heading": "h", "detail": "d"}]}
    # No network: a retry runs the whole pipeline, research included.
    enrich.enrich_note = lambda *a, **kw: {"_meta": {"ok": True}}
    try:
        pipeline.process_url(ug, conn=conn, force=True, do_enrich=False)
        g = store.get_item(conn, gid)
        check("a re-fire keeps the group tag that ties it to its line",
              "group:gg" in (g.get("tags") or {}).get("user", []), str(g.get("tags")))

        store.upsert_item(conn, {"id": hid, "url": uh, "error": "found no media",
                                 "attempts": 1, "processed_at": time.time()})
        store.upsert_item(conn, {"id": kid, "url": uk, "error": "found no media",
                                 "attempts": 3, "processed_at": time.time()})
        early = pipeline.retry_failed(conn)
        check("a read that failed a moment ago waits before its retry",
              not early, str([d.get("url") for d in early]))
        conn.execute("UPDATE items SET updated_at=? WHERE id IN (?,?)",
                     (time.time() - 7 * 3600, hid, kid))
        conn.commit()
        done = pipeline.retry_failed(conn)
        urls = [d.get("url") for d in done]
        check("a failed read is tried again on a later sync", uh in urls, str(urls))
        check("and the retry that worked cleared the error",
              not (store.get_item(conn, hid) or {}).get("error"))
        check("but a link is not retried once it has had its three tries",
              uk not in urls, str(urls))
        again = pipeline.retry_failed(conn)
        check("and nothing is retried twice in a row", not again,
              str([d.get("url") for d in again]))
    finally:
        acq_mod.acquire, ex_mod.extract_item = real_acq, real_ext
        enrich.enrich_note = real_enrich
        conn.close()


def test_frames_cover_the_video():
    print("a video's frames reach its end")
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg")
    if not ff or not shutil.which("ffprobe"):
        check("ffmpeg and ffprobe are here to make a test video", False,
              "install ffmpeg; the follow-up needs it for reels too")
        return
    from PIL import Image
    d = Path(TMP) / "frames"
    d.mkdir(exist_ok=True)
    video = d / "clip.mp4"
    # Red for 50 seconds, then blue. Frames every three seconds, capped at
    # 16, never got past second 48 and so never saw blue.
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=red:s=64x64:d=50:r=5",
                    "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=10:r=5",
                    "-filter_complex", "[0][1]concat=n=2:v=1:a=0",
                    "-pix_fmt", "yuv420p", str(video)], capture_output=True, timeout=120)
    names = brain._frames(video, d, "vid")
    check("a minute of video gives 16 frames", len(names) == 16, str(names))
    if names:
        r, g, b = Image.open(d / names[-1]).convert("RGB").getpixel((32, 32))
        check("and the last one is from the end", b > 150 and r < 100, str((r, g, b)))

    # A reel as it is downloaded: the picture, the sound, and the two
    # together. The sound alone sorts first and has no frames.
    reel = Path(TMP) / "reelmedia"
    reel.mkdir(exist_ok=True)
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=3", "-c:a", "aac",
                    str(reel / "abc_audio.mp4")], capture_output=True, timeout=120)
    shutil.copy2(video, reel / "abc_video.mp4")
    staged = brain._stage_media([{"id": "rl", "media_dir": str(reel)}], d / "staged")
    check("a reel's frames come from the picture, not the sound",
          len(staged.get("rl") or []) == 16, str(staged.get("rl"))[:120])


def test_site_check_reads_the_push():
    print("the site check looks at what was pushed, not only what was built")
    from kiln import health
    root = Path(TMP) / "siteroot"
    (root / "public" / "data").mkdir(parents=True, exist_ok=True)
    (root / "public" / "data" / "items.json").write_text(
        json.dumps({"items": [{"id": "a"}]}), encoding="utf-8")
    conn = store.connect()
    real_root, real_pushed = config.ROOT, health._pushed_items
    try:
        config.ROOT = root
        health._pushed_items = lambda: ([{"id": "a"}], "")
        same = [f["what"] for f in health.check_site_matches_db(conn)]
        health._pushed_items = lambda: ([], "")
        stopped = [f["what"] for f in health.check_site_matches_db(conn)]
        health._pushed_items = real_pushed
        nogit = [f["what"] for f in health.check_site_matches_db(conn)]
    finally:
        config.ROOT, health._pushed_items = real_root, real_pushed
        conn.close()
    gone = "the live site does not have this build"
    check("a build that was pushed raises nothing about the live site",
          gone not in same, str(same))
    check("a build that never reached the site is said", gone in stopped, str(stopped))
    check("and a folder with no pushed copy says it could not look",
          "could not read the pushed copy of the site" in nogit, str(nogit))


def main() -> int:
    test_site_check_reads_the_push()
    test_frames_cover_the_video()
    test_first_pass_reports_and_lessons()
    test_check_plan()
    test_check_final()
    test_set_aside_wrong_research()
    test_command_line()
    test_end_to_end()
    test_refused_then_fixed()
    test_blocked_and_failed()
    test_nothing_to_do_and_selection()
    test_unread_asks_first()
    test_gate_keyword()
    test_claude_read_stored_in_full()
    test_one_yes_covers_the_list()
    test_sweep_stops_and_survives()
    test_health_cards_listen()
    test_inbox_changes()
    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
