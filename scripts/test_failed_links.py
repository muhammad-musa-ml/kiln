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

    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
