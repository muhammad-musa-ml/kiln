"""The leak audit catches what it is there to catch.

Each case builds a small site in a throwaway folder, plants one kind of
leak in it, and runs the real audit script against it. A clean site has to
pass too, so an audit that fails everything cannot hide in here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TMP = Path(tempfile.mkdtemp(prefix="kiln-audit-")).resolve()

results: list[bool] = []

# Writes the notes into the throwaway store the audit reads, through the
# real store module so the schema is the real one.
SEED = chr(10).join([
    "import sys, time",
    "sys.path.insert(0, sys.argv[1])",
    "from kiln import store",
    "c = store.connect()",
    "for i, n in enumerate(sys.argv[2:]):",
    "    store.upsert_item(c, {'id': 'n%d' % i, 'url': 'https://example.com/n%d' % i,",
    "                          'user_note': n, 'created_at': time.time()})",
    "c.close()",
])


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(bool(passed))
    print(("  ok    " if passed else "  FAIL  ") + label
          + (("\n        " + detail) if detail and not passed else ""))


def audit(name: str, items: list[dict], notes: list[str],
          patch: tuple[str, str] | None = None, page_extra: str = "") -> tuple[int, str]:
    """Build the site, seed the notes, run the audit. Returns exit code and output."""
    root = TMP / name
    shutil.copytree(REPO / "kiln", root / "kiln",
                    ignore=shutil.ignore_patterns("__pycache__"))
    if patch:
        p = root / "kiln" / "publish.py"
        src = p.read_text(encoding="utf-8")
        if src.count(patch[0]) != 1:
            raise SystemExit("patch anchor not found once in publish.py: %r" % patch[0])
        p.write_text(src.replace(patch[0], patch[1]), encoding="utf-8")
    (root / "scripts").mkdir()
    shutil.copy2(HERE / "audit_public.py", root / "scripts" / "audit_public.py")
    (root / "web").mkdir()
    # page_extra goes into both copies, so it is the page that says it and
    # not a published copy that drifted from the local one.
    page = (REPO / "web" / "index.html").read_text(encoding="utf-8") + page_extra
    (root / "web" / "index.html").write_text(page, encoding="utf-8")
    pub = root / "public" / "data"
    pub.mkdir(parents=True)
    (pub / "items.json").write_text(json.dumps({"items": items, "built": "25 Sep 2026"}),
                                    encoding="utf-8")
    (pub / "facets.json").write_text(json.dumps({"total": len(items)}), encoding="utf-8")
    (root / "public" / "index.html").write_text(
        '<script>window.KILN_STATIC=true;window.KILN_BUILT="25 Sep 2026";</script>' + page,
        encoding="utf-8")

    env = dict(os.environ, KILN_DATA=str(root / "data"), PYTHONIOENCODING="utf-8")
    env.pop("KILN_DB", None)
    subprocess.run([sys.executable, "-c", SEED, str(root), *notes], env=env,
                   check=True, capture_output=True)
    p = subprocess.run([sys.executable, str(root / "scripts" / "audit_public.py")],
                       cwd=root, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def item(**kw) -> dict:
    d = {"id": "a", "url": "https://example.com/a", "title": "A post",
         "summary": "Nothing private here at all."}
    d.update(kw)
    return d


LONG = "find the real job posting for this role please"
SHORT = "is this worth installing on windows"
TINY = "list the companies"


def main() -> int:
    print("the audit passes a clean site")
    code, out = audit("clean", [item()], [LONG, SHORT, TINY])
    check("a site with nothing private in it passes",
          code == 0 and "AUDIT PASSED" in out, out[-600:])
    # Nine words make two runs of eight; the six-word note is one short one.
    check("and it really did look at the notes",
          "none of 2 eight-word runs and 1 short notes" in out, out[-600:])

    print("what I wrote next to a link")
    code, out = audit("long", [item(summary="They said: find the real job posting "
                                            "for this role, then left.")], [LONG])
    check("eight words of a long note in the build fail it",
          code == 1 and "from a private instruction" in out, out[-400:])
    code, out = audit("short", [item(summary="Is this worth installing on Windows? "
                                             "Probably.")], [SHORT])
    check("a note of six words is caught whole",
          code == 1 and "from a private instruction" in out, out[-400:])
    code, out = audit("tiny", [item(summary="Here I list the companies.")], [TINY])
    check("a note under five words is not checked, as the audit says",
          code == 0, out[-400:])

    print("fields that must never go out")
    code, out = audit("field", [item(user_note="call me back")], [])
    check("a private field name in the data fails it",
          code == 1 and "private field 'user_note'" in out, out[-400:])
    code, out = audit("gate", [item(gate={"gated": True, "how": "comment",
                                          "keyword": "PDF", "note": "mine"})], [])
    check("a gate key outside the whitelist fails it",
          code == 1 and "nested keys outside the whitelist: ['note']" in out, out[-400:])
    code, out = audit("admit", [item()], [],
                      patch=('NOTE_FIELDS = ("sections",',
                             'NOTE_FIELDS = ("user_note", "sections",'))
    check("a whitelist that admits a private field fails it",
          code == 1 and "a whitelist admits private fields: ['user_note']" in out,
          out[-400:])

    print("the page names no vendor")
    code, out = audit("vendor", [item()], [],
                      page_extra="<!-- read by Gemini, followed up by Claude -->\n")
    check("a vendor named in the page itself fails it",
          code == 1 and "names ['claude', 'gemini']" in out, out[-400:])
    code, out = audit("vendor-item", [item(title="Claude Code in ten minutes")], [])
    check("while an item about one is fine", code == 0, out[-400:])

    print()
    print("%d/%d pass" % (sum(results), len(results)))
    if all(results):
        shutil.rmtree(TMP, ignore_errors=True)
    else:
        print("test sites kept for a look: %s" % TMP)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
