"""The leak audit catches what it is there to catch.

Each case builds a small site in a throwaway folder, plants one kind of
leak in it, and runs the real audit script against it. A clean site has to
pass too, so an audit that fails everything cannot hide in here.

The share-token cases also run the real publish step, in a throwaway data
folder, so the strip and the check on it are tested together: what publish
lets out has to pass, and the same links planted raw have to fail.
"""
from __future__ import annotations

import base64
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
          patch: tuple[str, str] | None = None, page_extra: str = "",
          files: dict[str, bytes] | None = None) -> tuple[int, str]:
    """Build the site, seed the notes, run the audit. Returns exit code and output.

    files are extra published files, by their path under public/.
    """
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
    for rel, data in (files or {}).items():
        f = root / "public" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)

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

# A made-up share token, the same shape as a real one. A real one never goes
# in a file that is published.
TOKEN = base64.b64encode(b"faketoken01").decode()
POST = "https://www.instagram.com/p/AbC123/"

# Runs the real publish step on the cases it is given, with a throwaway data
# folder, so the document it prints and the store it reads are not mine.
STRIP = chr(10).join([
    "import hashlib, json, sys",
    "from pathlib import Path",
    "sys.path.insert(0, sys.argv[1])",
    "from kiln import artifacts, publish",
    "cases = json.loads(sys.stdin.read())",
    "out = {'clean': [publish.clean_urls(t) for t in cases['texts']]}",
    "out['twice'] = [publish.clean_urls(t) for t in out['clean']]",
    "out['item'] = publish.public_item(cases['item'])",
    "src = Path(sys.argv[2]) / 'notes.md'",
    "src.write_text(cases['doc'], encoding='utf-8')",
    "rec = artifacts.store('doc1', src, title='Notes', pdf=True)",
    "mine = artifacts.item_dir('doc1') / rec.get('file', 'none')",
    "before = hashlib.md5(mine.read_bytes()).hexdigest()",
    "public = Path(sys.argv[2]) / 'public-notes.pdf'",
    "out['pages'] = publish._publish_document('doc1', mine, public)",
    "out['mine'], out['public'] = str(mine), str(public)",
    "out['mine_kept'] = hashlib.md5(mine.read_bytes()).hexdigest() == before",
    "out['mine_text'] = artifacts.pdf_text(mine)",
    "out['public_text'] = artifacts.pdf_text(public) if public.exists() else ''",
    "print(json.dumps(out))",
])


def strip(cases: dict) -> dict:
    """What the real publish step makes of the cases."""
    data = TMP / "strip-data"
    data.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, KILN_DATA=str(data), PYTHONIOENCODING="utf-8")
    env.pop("KILN_DB", None)
    p = subprocess.run([sys.executable, "-c", STRIP, str(REPO), str(data)],
                       input=json.dumps(cases), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit("the publish step failed on the cases:\n" + p.stderr[-2000:])
    return json.loads(p.stdout)


def pdf_of(lines: list[str]) -> bytes:
    """A one-page PDF with these lines of text, uncompressed and built by hand.

    Each is its own line on the page, so a link split across two of them is
    split the way a printed PDF splits a long address.
    """
    ops = ["BT", "/F1 10 Tf", "72 720 Td"]
    for i, line in enumerate(lines):
        ops += (["0 -14 Td"] if i else []) + ["(%s) Tj" % line]
    stream = chr(10).join(ops + ["ET"]).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    pdf, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, xref)
    return pdf


# What publish does to a link: the share and tracking parameters go, and
# whatever says which post, video, slide or page it is stays, byte for byte.
T = TOKEN
CLEAN_CASES = [
    (POST + "?stkn=" + T, POST),
    (POST + "?img_index=7&stkn=" + T, POST + "?img_index=7"),
    (POST + "?stkn=" + T + "&img_index=2", POST + "?img_index=2"),
    (POST + "?igsh=" + T, POST),
    (POST + "?igshid=" + T, POST),
    # Instagram keeps only the slide, so the token's next name cannot slip out.
    (POST + "?ighash=" + T, POST),
    ("https://WWW.Instagram.com/p/AbC123/?STKN=" + T, "https://WWW.Instagram.com/p/AbC123/"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1&si=" + T,
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1"),
    ("https://youtu.be/dQw4w9WgXcQ?si=" + T, "https://youtu.be/dQw4w9WgXcQ"),
    ("https://example.com/a?utm_source=ig&utm_medium=social&id=5", "https://example.com/a?id=5"),
    # si is a share id on YouTube only; elsewhere it may be what the page is.
    ("https://example.com/a?id=5&si=2", "https://example.com/a?id=5&si=2"),
    ("See [the post](" + POST + "?stkn=" + T + ").", "See [the post](" + POST + ")."),
    ("Watch https://youtu.be/dQw4w9WgXcQ?si=" + T + ".", "Watch https://youtu.be/dQw4w9WgXcQ."),
    ('<a href="' + POST + "?img_index=2&amp;stkn=" + T + '">post</a>',
     '<a href="' + POST + '?img_index=2">post</a>'),
    ('<a href="https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=abc&amp;'
     'format=json">check</a>',
     '<a href="https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=abc&amp;'
     'format=json">check</a>'),
    ("https://www.youtube.com/oembed?url=" + POST + "?stkn=" + T + "&format=json",
     "https://www.youtube.com/oembed?url=" + POST + "&format=json"),
    ("https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.instagram.com%2Fp%2FAbC123%2F"
     "%3Fstkn%3D" + T + "&format=json",
     "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.instagram.com%2Fp%2FAbC123%2F"
     "&format=json"),
    ("instagram.com/p/AbC123/?igsh=" + T, "instagram.com/p/AbC123/"),
    ('fetch(base + "?utm_source=kiln&page=2")', 'fetch(base + "?page=2")'),
    ("https://example.com/a?utm_source=x#part", "https://example.com/a#part"),
    ("https://l.instagram.com/?u=https%3A%2F%2Fexample.com%2F&e=AT0",
     "https://l.instagram.com/?u=https%3A%2F%2Fexample.com%2F&e=AT0"),
    ("Is this worth it? Maybe. Q&A at 5?", "Is this worth it? Maybe. Q&A at 5?"),
]


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

    print("share tokens in links")
    full = {"id": "tok", "url": POST + "?img_index=2&stkn=" + T, "title": "A post",
            "summary": "Nothing private here at all.", "kind": "listicle",
            "note": {"sections": [{"heading": "Links",
                                   "detail": "https://example.com/guide?utm_source=ig&id=4"}]},
            "enrich": {"useful_links": [{"url": "https://youtu.be/dQw4w9WgXcQ?si=" + T,
                                         "title": "video"}]},
            "claude": {"answer": "Read [the post](" + POST + "?stkn=" + T + ").",
                       "answered": "fully",
                       "sources": [{"url": "https://www.instagram.com/reel/XyZ/?igsh=" + T,
                                    "title": "reel"}]},
            "links": [{"url": "https://www.instagram.com/p/Other/?stkn=" + T,
                       "label": "other", "alive": True, "page_title": "Other"}],
            "tags": {"action": ["reference"]}}
    doc = ("# Notes\n\nThe post: [on Instagram](%s?stkn=%s).\n\nA long one, broken "
           "across lines on paper: %s%s/?img_index=2&stkn=%s\n" % (POST, T, POST, "x" * 150, T))
    got = strip({"texts": [c[0] for c in CLEAN_CASES], "item": full, "doc": doc})
    wrong = [(c[0], g, c[1]) for c, g in zip(CLEAN_CASES, got["clean"]) if g != c[1]]
    check("publish takes the share and tracking parameters off every kind of link, "
          "and leaves the rest byte for byte (%d cases)" % len(CLEAN_CASES),
          not wrong, "\n        ".join("%r -> %r, wanted %r" % w for w in wrong[:4]))
    check("and a second pass changes nothing", got["twice"] == got["clean"])
    pub = got["item"]
    check("an item goes out with no token in any field, its links included",
          T not in json.dumps(pub), json.dumps(pub)[:600])
    check("and keeps which slide the link opens on", pub.get("url") == POST + "?img_index=2",
          str(pub.get("url")))
    check("the answer still links to the post", 'href="%s"' % POST in
          (pub.get("followup") or {}).get("answer_html", ""),
          (pub.get("followup") or {}).get("answer_html", "")[:300])
    code, out = audit("stripped", [pub], [])
    check("what publish lets out passes the audit", code == 0, out[-600:])

    code, out = audit("raw", [item(url=POST + "?stkn=" + T)], [])
    check("a share token in an item's link fails it",
          code == 1 and "share or tracking parameter(s) in links" in out and "'stkn'" in out,
          out[-400:])
    check("and the audit never prints the token itself", T not in out, out[-400:])
    code, out = audit("raw-many", [item(links=full["links"], followup={
        "answer_html": '<a href="' + POST + '?img_index=2&amp;igsh=' + T + '">post</a>',
        "sources": [{"url": "https://youtu.be/dQw4w9WgXcQ?si=" + T, "title": "v"},
                    {"url": "https://example.com/guide?id=4&utm_source=ig", "title": "g"}]})], [])
    check("in a link, as &amp; in an answer, YouTube's si and utm_ all fail it",
          code == 1 and all("'%s'" % n in out for n in ("stkn", "igsh", "si", "utm_source")),
          out[-500:])
    code, out = audit("raw-nested", [item(followup={"sources": [{
        "url": "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.instagram.com%2Fp%2F"
               "AbC123%2F%3Fstkn%3D" + T + "&format=json", "title": "check"}]})], [])
    check("a token percent-encoded inside another link fails it",
          code == 1 and "'stkn'" in out, out[-400:])
    code, out = audit("content", [item(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1",
        links=[{"url": POST + "?img_index=3", "label": "", "alive": True, "page_title": ""}])],
        [])
    check("while a link's own parameters (v=, list=, img_index=) are fine", code == 0,
          out[-400:])

    print("share tokens in a published document")
    check("the document was printed with the token in it, as a stand-in for mine",
          got["mine"].endswith(".pdf") and T in got["mine_text"].replace("\n", ""),
          got["mine"])
    check("publish printed a clean copy for the site",
          got["pages"] and got["public_text"] and T not in got["public_text"].replace("\n", ""),
          "pages=%r text=%r" % (got["pages"], got["public_text"][:200]))
    check("which still names the post", POST in got["public_text"].replace("\n", ""),
          got["public_text"][:300])
    check("and my own copy is left as it was", got["mine_kept"])
    code, out = audit("pdf-token", [item()], [], files={
        "media/a/files/notes.pdf": Path(got["mine"]).read_bytes()})
    check("a PDF with a token in its text fails it",
          code == 1 and "notes.pdf" in out and "'stkn'" in out, out[-500:])
    code, out = audit("pdf-clean", [item()], [], files={
        "media/a/files/notes.pdf": Path(got["public"]).read_bytes()})
    check("and the copy publish printed passes", code == 0, out[-500:])
    split = pdf_of(["See " + POST + "?st", "kn=" + T + " for the post."])
    code, out = audit("pdf-split", [item()], [], files={"media/a/files/split.pdf": split})
    check("a token broken across two lines of a PDF is still caught",
          code == 1 and "split.pdf" in out and "'stkn'" in out, out[-500:])

    print()
    print("%d/%d pass" % (sum(results), len(results)))
    if all(results):
        shutil.rmtree(TMP, ignore_errors=True)
    else:
        print("test sites kept for a look: %s" % TMP)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
