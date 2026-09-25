"""A link that cannot be read still has to end up somewhere I will find it.

One did not. A reel came back with no media, got stored with no title, no
action and no tag, and sat at the bottom of the inbox where no filter
matched it and nothing ever pointed at it again. These pin the two ways that
can happen: nothing acquired at all, and acquired but nothing extracted.

The network is never touched. acquire and extract are both replaced.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(passed)
    print(("  ok    " if passed else "  FAIL  ") + label
          + (("\n        " + detail) if detail and not passed else ""))


def run_case(acquired, note):
    """Run one link through the pipeline against a throwaway database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        import kiln.config as config
        old_db = config.DB_PATH
        config.DB_PATH = Path(t) / "test.db"
        try:
            from kiln import pipeline, store
            from kiln import acquire as acq_mod
            from kiln import extract as extract_mod

            real_acq, real_ext = acq_mod.acquire, extract_mod.extract_item
            acq_mod.acquire = lambda url, **kw: acquired
            extract_mod.extract_item = lambda acq, **kw: note
            try:
                conn = store.connect()
                item = pipeline.process_url("https://example.com/broken",
                                            do_enrich=False, conn=conn)
                conn.close()
            finally:
                acq_mod.acquire, extract_mod.extract_item = real_acq, real_ext
            return item
        finally:
            config.DB_PATH = old_db


def test_empty_read_detection() -> None:
    """A read that got nothing must not pass for one that got something."""
    print("telling a real read from one that only looks real")
    from kiln import pipeline
    from kiln.acquire import Acquired

    carousel = Acquired(url="u", kind="instagram", slides=["a"] * 11)
    article = Acquired(url="u", kind="web", body_text="words")

    # The exact shape that shipped: no sections, no on-screen text, no links,
    # and one summary clipped mid-sentence because the window ran out.
    clipped = {"summary": "...from solar-powered compute to healthcare. The post",
               "sections": [], "onscreen_text": []}
    check("a clipped summary over eleven slides counts as empty",
          pipeline._came_back_empty(clipped, carousel), str(clipped)[:80])

    real = {"summary": "a real summary", "sections": [{"heading": "one"}],
            "onscreen_text": ["a line"]}
    check("a genuine read does not", not pipeline._came_back_empty(real, carousel))

    # An article has no pictures, so a summary alone is a legitimate read.
    check("a text page with a summary and no sections is fine",
          not pipeline._came_back_empty({"summary": "a summary"}, article))
    check("nothing at all is still empty",
          pipeline._came_back_empty({}, article))


def test_quota_classification() -> None:
    """A busy minute is not a spent day."""
    print("telling a rate limit from an exhausted quota")
    from kiln import models

    transient = [
        "HTTP 429: Resource has been exhausted (requests per minute)",
        "HTTP 429: rate limit exceeded, retry shortly",
        "HTTP 429: You exceeded your current quota",
    ]
    for err in transient:
        check("retried, not burned: %s" % err[10:48],
              not models._daily_quota_gone(err), err)

    daily = [
        "HTTP 429: quota metric generate_requests_per_model_per_day exceeded",
        "HTTP 429: GenerateRequestsPerDayPerProjectPerModel limit",
    ]
    for err in daily:
        check("burned for the day: %s" % err[10:48],
              models._daily_quota_gone(err), err)


def test_spent_day_keeps_the_try() -> None:
    """A read turned away by every model's spent day was never really tried."""
    print("a spent day does not use up one of a link's tries")
    from kiln import handoff
    from kiln.acquire import Acquired

    def exhausted(*attempts):
        return {"_error": "every model failed", "_meta": {
            "exhausted": True, "passes": [{"attempts": list(attempts)}]}}

    reel = Acquired(url="https://example.com/broken", kind="instagram", video="clip.mp4")
    real_pending = handoff.PENDING
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        # The exhausted path writes a brief; keep it out of the real data.
        handoff.PENDING = Path(t) / "handoff"
        handoff.PENDING.mkdir()
        try:
            spent = run_case(reel, exhausted(
                "gemini:gemini-3.8-flash FAIL daily free-tier budget spent",
                "gemini:gemini-3.7-flash FAIL HTTP 429 [quota: per day] {..."))
            busy = run_case(reel, exhausted(
                "gemini:gemini-3.8-flash FAIL daily free-tier budget spent",
                "gemini:gemini-3.7-flash FAIL HTTP 503 {model overloaded}"))
        finally:
            handoff.PENDING = real_pending
    check("every model's day was spent, so the try is given back",
          int(spent.get("attempts") or 0) == 0, str(spent.get("attempts")))
    check("one model really ran and failed, so it counts",
          int(busy.get("attempts") or 0) == 1, str(busy.get("attempts")))


def test_daily_quota_seen_in_full() -> None:
    """Google says which quota a 429 is about only near the end of its body.

    The body used to be cut to 400 characters before anything looked at it,
    so a spent day was never recognised: every item then waited through the
    retries on every model, all day. Run against a throwaway ledger, with
    the network replaced, so nothing real is touched.
    """
    print("a spent day is recognised from the whole 429 body")
    import io
    import json as _json
    import urllib.error
    from kiln import config, models

    def body_for(quota_id: str) -> str:
        return _json.dumps({"error": {
            "code": 429, "status": "RESOURCE_EXHAUSTED",
            "message": "You exceeded your current quota, please check your plan. "
                       + "x" * 400,
            "details": [{"quotaId": quota_id, "quotaValue": "20"}]}})

    sent: list[int] = []
    slept: list[float] = []
    reply = {"body": body_for("GenerateRequestsPerDayPerProjectPerModel-FreeTier")}

    def refuse(req, timeout=0):
        sent.append(1)
        raise urllib.error.HTTPError("https://example.invalid", 429, "Too Many Requests",
                                     None, io.BytesIO(reply["body"].encode("utf-8")))

    saved = (models.urllib.request.urlopen, models.time.sleep, models._LEDGER_PATH,
             config.GEMINI_API_KEY)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        models._LEDGER_PATH = Path(t) / "quota.json"
        models.urllib.request.urlopen = refuse
        models.time.sleep = slept.append
        config.GEMINI_API_KEY = config.GEMINI_API_KEY or "test-key-not-real"
        try:
            check("the per-day marker is past what the log keeps",
                  reply["body"].find("PerDay") > 400)
            out, err = models._post("https://example.invalid", {}, 5)
            check("the error still says the day is over",
                  out is None and models._daily_quota_gone(err), err[:120])
            check("while keeping only the start of the body", len(err) < 500,
                  str(len(err)))
            sent.clear()
            r = models._call_gemini("gemini-3.8-flash", "hi", [], grounded=False,
                                    thinking=0, want_json=True, timeout=5)
            check("a spent day costs one request and no waiting",
                  not r.ok and len(sent) == 1 and not slept,
                  "sent %d, slept %s" % (len(sent), slept))
            left = {m["model"]: m["left"] for m in models.quota_snapshot()["models"]}
            check("and marks the model out for the day",
                  left.get("gemini-3.8-flash") == 0, str(left))

            reply["body"] = body_for("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
            sent.clear()
            slept.clear()
            r = models._call_gemini("gemini-3.7-flash", "hi", [], grounded=False,
                                    thinking=0, want_json=True, timeout=5)
            left = {m["model"]: m["left"] for m in models.quota_snapshot()["models"]}
            check("a busy minute still gets its retries, and burns nothing",
                  len(sent) == 4 and len(slept) == 3 and left.get("gemini-3.7-flash", 0) > 0,
                  "sent %d, slept %s, left %s" % (len(sent), slept, left))
        finally:
            (models.urllib.request.urlopen, models.time.sleep, models._LEDGER_PATH,
             config.GEMINI_API_KEY) = saved

    class At(models.datetime):
        moment = None

        @classmethod
        def now(cls, tz=None):
            return cls.moment

    real = models.datetime
    models.datetime = At
    try:
        At.moment = real(2026, 9, 26, 7, 59, tzinfo=models.timezone.utc)
        before = models._quota_day()
        At.moment = real(2026, 9, 26, 8, 0, tzinfo=models.timezone.utc)
        after = models._quota_day()
    finally:
        models.datetime = real
    check("the ledger's day turns over when Google's does, at midnight Pacific",
          (before, after) == ("2026-09-25", "2026-09-26"), str((before, after)))


def main() -> int:
    from kiln.acquire import Acquired
    from kiln.pipeline import REDO

    print("nothing could be acquired")
    item = run_case(
        Acquired(url="https://example.com/broken", kind="instagram",
                 error="browser loaded the page but found no media"),
        {})
    actions = (item.get("tags") or {}).get("action") or []
    check("it is kept rather than dropped", bool(item), str(item)[:120])
    check("tagged redo", actions == [REDO], str(actions))
    check("the link is still there", item.get("url", "").endswith("broken"),
          item.get("url", ""))
    check("it has a title instead of a blank row", bool(item.get("title")),
          repr(item.get("title")))
    check("and says why it failed",
          "found no media" in (item.get("error") or "")
          or "found no media" in (item.get("summary") or ""),
          repr(item.get("error")))
    check("it sits in the inbox, not filed as done",
          item.get("status") == "inbox", str(item.get("status")))

    print("acquired, but the read came back empty")
    item = run_case(
        Acquired(url="https://example.com/broken", kind="web",
                 title="A Page", body_text="something"),
        {"kind": "tutorial", "action_hint": "learn"})
    actions = (item.get("tags") or {}).get("action") or []
    check("tagged redo rather than a guessed bucket", actions == [REDO],
          str(actions))
    check("it sits in the inbox", item.get("status") == "inbox",
          str(item.get("status")))
    check("and says what to do about it",
          "re-fire" in (item.get("error") or ""), repr(item.get("error")))

    print("a link that worked is untouched")
    item = run_case(
        Acquired(url="https://example.com/broken", kind="youtube",
                 title="A Video", body_text="x"),
        {"kind": "course", "action_hint": "learn", "summary": "a real summary",
         "sections": [{"heading": "one"}]})
    actions = (item.get("tags") or {}).get("action") or []
    check("keeps its real action", actions and actions[0] != REDO, str(actions))
    check("and is not parked in the inbox", item.get("status") != "inbox",
          str(item.get("status")))

    test_empty_read_detection()
    test_quota_classification()
    test_daily_quota_seen_in_full()
    test_spent_day_keeps_the_try()

    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
