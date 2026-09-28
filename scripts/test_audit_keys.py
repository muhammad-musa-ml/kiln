"""Check 1 must still catch an exported private column.

Narrowing check 1 from a raw substring scan to a key scan is only safe if a
real leak is still caught. These run on copies of the real build; nothing
here writes to public/.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_public as A  # noqa: E402

FAILURES: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print("  ok    %s" % name)
    else:
        FAILURES.append(name)
        print("  FAIL  %s: got %r, wanted %r" % (name, got, want))


def main() -> int:
    print("json_keys")
    check("finds a top-level key",
          "a" in A.json_keys({"a": 1}), True)
    check("finds a key nested in a dict",
          "deep" in A.json_keys({"a": {"b": {"deep": 1}}}), True)
    check("finds a key nested through a list",
          "deep" in A.json_keys({"a": [{"b": [{"deep": 1}]}]}), True)
    check("does not report a string VALUE as a key",
          "pdf_path" in A.json_keys({"note": "def f(pdf_path: str)"}), False)
    check("does not report a substring of a longer key",
          "pdf_path" in A.json_keys({"my_pdf_path_x": 1}), False)

    src = A.OUT / "data" / "items.json"
    if not src.exists():
        print("\n  FAIL  no build to test against: %s" % src)
        return 1
    real = json.loads(src.read_text(encoding="utf-8"))

    print("\nthe real build")
    keys = A.json_keys(real)
    leaked = sorted(n for n in A.FORBIDDEN_KEYS if n in keys)
    check("carries no private column as a key", leaked, [])
    check("still contains the word pdf_path somewhere in its text",
          "pdf_path" in src.read_text(encoding="utf-8"), True)

    print("\na planted leak is still caught")
    records = real if isinstance(real, list) else real.get("items", [])
    if not records:
        print("  FAIL  no records to plant into")
        return 1

    for field in ("pdf_path", "user_do", "claude_json", "media_dir"):
        bad = copy.deepcopy(real)
        recs = bad if isinstance(bad, list) else bad.get("items", [])
        recs[0][field] = "anything at all"
        found = sorted(n for n in A.FORBIDDEN_KEYS if n in A.json_keys(bad))
        check("top-level %-12s is caught" % field, found, [field])

    bad = copy.deepcopy(real)
    recs = bad if isinstance(bad, list) else bad.get("items", [])
    recs[0].setdefault("note", {})
    if not isinstance(recs[0]["note"], dict):
        recs[0]["note"] = {}
    recs[0]["note"]["media_dir"] = "C:/somewhere/private"
    check("a leak nested inside note is caught",
          "media_dir" in A.json_keys(bad), True)

    bad = copy.deepcopy(real)
    recs = bad if isinstance(bad, list) else bad.get("items", [])
    recs[0]["extra"] = [{"deeper": [{"claude_state": "done"}]}]
    check("a leak nested through lists is caught",
          "claude_state" in A.json_keys(bad), True)

    print()
    if FAILURES:
        print("%d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all key-scan checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
