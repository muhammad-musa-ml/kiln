"""A document I asked for has to come out as something I can keep and print.

The artifact writer takes the Markdown or HTML a model wrote, files it under
the item it belongs to, and turns it into a PDF. These pin what that promises:
every link's address is on the paper, no banned character survives into the
file or the PDF, drawing the page never reaches the network, and nothing but
the kinds of file it is meant to keep ever gets copied.

Everything runs against a throwaway data folder. The real data/ is never
opened: KILN_DATA is pinned before any kiln import, and the run stops if the
pin did not take.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="kiln-artifacts-")).resolve()
DATA = TMP / "data"
os.environ["KILN_DATA"] = str(DATA)
os.environ.pop("KILN_DB", None)

import kiln.config as config  # noqa: E402

if config.DATA.resolve() != DATA:
    raise SystemExit("KILN_DATA did not take: config.DATA is %s, not %s. Stopping "
                     "before anything can touch the real data folder."
                     % (config.DATA, DATA))

from kiln import artifacts, slop  # noqa: E402

if not artifacts.ARTIFACTS.resolve().is_relative_to(TMP):
    raise SystemExit("artifacts.ARTIFACTS is %s, outside the temp folder" % artifacts.ARTIFACTS)

EM = chr(0x2014)
EN = chr(0x2013)
LSQ, RSQ, LDQ, RDQ = chr(0x2018), chr(0x2019), chr(0x201C), chr(0x201D)
ELLIPSIS = chr(0x2026)
NBSP = chr(0x00A0)
RIGHT, LEFT, IMPLIES = chr(0x2192), chr(0x2190), chr(0x21D2)
CHECK, CROSS = chr(0x2713), chr(0x2717)
HEAVY_CHECK, RED_CROSS = chr(0x2714), chr(0x274C)
ROBOT, ROCKET = chr(0x1F916), chr(0x1F680)

WORK = TMP / "work"
WORK.mkdir(parents=True, exist_ok=True)
PDFS: list[Path] = []
results: list[bool] = []


def check(label: str, passed, detail: str = "") -> None:
    results.append(bool(passed))
    print(("  ok    " if passed else "  FAIL  ") + label
          + (("\n        " + detail) if detail and not passed else ""))


def write(name: str, text: str) -> Path:
    p = WORK / name
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


def dirty(text: str) -> list[str]:
    """Which banned characters, or emoji, a text still holds."""
    found = ["U+%04X" % ord(c) for c in slop.BANNED_CHARS if c in text]
    if slop.EMOJI.search(text):
        found.append("emoji")
    return found


def stored(item: str, rec: dict) -> Path:
    return artifacts.item_dir(item) / str(rec.get("source") or "missing")


def made(item: str, rec: dict) -> Path:
    return artifacts.item_dir(item) / str(rec.get("file") or "missing")


class Listener:
    """A local port that counts every connection made to it.

    It counts TCP connections, not HTTP requests, so a preconnect or a
    request that never finished still shows up.
    """

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.hits: list[bytes] = []
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self) -> None:
        while not self._stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                continue
            c.settimeout(1)
            try:
                self.hits.append(c.recv(200).split(b"\r\n")[0])
                c.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                self.hits.append(b"(connected, no request)")
            c.close()

    def close(self) -> list[bytes]:
        time.sleep(0.5)
        self._stop = True
        self._t.join()
        self.sock.close()
        return self.hits


class Attrs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_plain() -> None:
    print("slop.plain spells every banned character in ASCII")
    for ch, kind in slop.BANNED_CHARS.items():
        out = slop.plain("a%sb" % ch)
        check("U+%04X (%s) has a plain spelling" % (ord(ch), kind),
              ch not in out and out != "ab" and out.isascii(), repr(out))

    pairs = [("a%sb" % EM, "a - b"), ("a %s b" % EM, "a - b"), ("a  %s b" % EM, "a - b"),
             ("    %s indented" % EM, "    - indented"),
             ("2020%s2024" % EN, "2020-2024"), ("a %s b" % RIGHT, "a -> b"),
             ("a %s b" % LEFT, "a <- b"), ("a %s b" % IMPLIES, "a => b"),
             ("%sq%s and %sit%ss%s" % (LDQ, RDQ, LSQ, RSQ, RSQ), "\"q\" and 'it's'"),
             ("wait%s" % ELLIPSIS, "wait..."), ("a%sb" % NBSP, "a b"),
             ("tests %s, lint %s" % (CHECK, CROSS), "tests yes, lint no"),
             ("done %s now %s" % (ROBOT, ROCKET), "done now"),
             ("%s launch" % ROCKET, "launch"),
             ("| %s | %s |" % (HEAVY_CHECK, RED_CROSS), "| yes | no |")]
    for raw, want in pairs:
        got = slop.plain(raw)
        check("plain(%s) == %r" % (ascii(raw), want), got == want, repr(got))

    same = "    x = 1  \nline with a hard break  \nIt works, but not always.\n"
    check("ordinary text, indentation and trailing spaces are left alone",
          slop.plain(same) == same, repr(slop.plain(same)))
    messy = "a %s b%s %sq%s %s %s" % (EM, ELLIPSIS, LDQ, RDQ, ROBOT, CHECK)
    check("plain is idempotent", slop.plain(slop.plain(messy)) == slop.plain(messy))


def test_safe_name() -> None:
    print("safe_name keeps a bare, portable file name")
    n = artifacts.safe_name("../../etc/passwd")
    check("'../../etc/passwd' is a bare name with no separators",
          n == "passwd" and "/" not in n and "\\" not in n, repr(n))
    n = artifacts.safe_name("..\\..\\Windows\\win.ini")
    check("so is a Windows path", n == "win.ini", repr(n))
    n = artifacts.safe_name("Companies & Links.MD")
    check("'Companies & Links.MD' gives 'companies-links.md'", n == "companies-links.md", repr(n))
    check("'' gives 'file'", artifacts.safe_name("") == "file", repr(artifacts.safe_name("")))
    check("a name of only dots gives 'file'", artifacts.safe_name("....") == "file",
          repr(artifacts.safe_name("....")))
    n = artifacts.safe_name(".env.md")
    check("no leading dot", n == "env.md", repr(n))
    n = artifacts.safe_name("Caf%s %s menu!.TXT" % (chr(0xE9), CHECK))
    check("only [a-z0-9._-] survive, suffix kept",
          re.fullmatch(r"[a-z0-9._-]+", n) is not None and n.endswith(".txt"), repr(n))
    long = "x" * 196 + ".pdf"
    n = artifacts.safe_name(long)
    check("a 200-character name is cut to 80 or fewer and keeps its suffix",
          len(long) == 200 and len(n) <= 80 and n.endswith(".pdf"), "%d %r" % (len(n), n[-12:]))


def test_item_dir() -> None:
    print("item_dir never leaves the artifacts folder")
    root = artifacts.ARTIFACTS.resolve()
    for iid in ("..", ".", "", "a/../../b", "x\\..\\..\\y"):
        d = artifacts.item_dir(iid).resolve()
        check("item id %r gets a folder of its own inside it" % iid,
              d != root and d.is_relative_to(root) and d.parent == root and d.is_dir(), str(d))
    d = artifacts.item_dir("3f2a9c01d4e5b6a7")
    check("a real item id is used as it is", d.name == "3f2a9c01d4e5b6a7" and d.is_dir(), str(d))


def test_refuses() -> None:
    print("store keeps only the kinds of file it is meant to")
    for name in ("setup.exe", "tool.py", "notes.md.exe"):
        rec = artifacts.store("refused", write(name, "MZ not a document"), title="x")
        check("%s is refused with an error" % name, bool(rec.get("error")) and "file" not in rec,
              json.dumps(rec))
    rec = artifacts.store("refused", WORK / "not-there.md", title="x")
    check("a missing source is an error, not an exception", bool(rec.get("error")), json.dumps(rec))
    folder = artifacts.ARTIFACTS / "refused"
    check("and nothing was copied", not folder.exists() or not any(folder.iterdir()),
          str(list(folder.iterdir())) if folder.exists() else "")


def test_records() -> None:
    print("the index holds one record per file")
    src = write("a.md", "# A\n\nfirst\n")
    artifacts.store("rec", src, title="A doc", about="first version")
    write("a.md", "# A\n\nsecond\n")
    rec = artifacts.store("rec", src, title="A doc", about="second version")
    recs = artifacts.list_for("rec")
    check("storing the same name twice leaves one record, the newer one",
          len(recs) == 1 and recs[0].get("about") == "second version", json.dumps(recs))
    check("a record has the promised keys",
          set(rec) == {"file", "source", "title", "about", "kind", "bytes", "pages"}, str(sorted(rec)))
    check("kind is the suffix without its dot, and a non-PDF has 0 pages",
          rec.get("kind") == "md" and rec.get("pages") == 0, json.dumps(rec))
    check("bytes is the size of the stored file",
          rec.get("bytes") == stored("rec", rec).stat().st_size and "second" in stored("rec", rec).read_text(encoding="utf-8"),
          json.dumps(rec))
    artifacts.store("rec", write("b.txt", "plain words\n"), title="B")
    recs = artifacts.list_for("rec")
    check("two different files leave two records",
          sorted(r.get("file") for r in recs) == ["a.md", "b.txt"], json.dumps(recs))

    check("an item never stored lists nothing and gets no folder",
          artifacts.list_for("never-stored") == [] and not (artifacts.ARTIFACTS / "never-stored").exists())
    (artifacts.item_dir("broken-index") / "index.json").write_text("{not json", encoding="utf-8")
    check("an unreadable index reads as empty", artifacts.list_for("broken-index") == [])

    rec = artifacts.store("rec", write("index.json", "[1, 2, 3]"), title="named like the index")
    recs = artifacts.list_for("rec")
    check("a file called index.json cannot overwrite the index",
          rec.get("source") not in (None, "index.json") and len(recs) == 3
          and json.loads(stored("rec", rec).read_text(encoding="utf-8")) == [1, 2, 3],
          json.dumps(rec) + " " + json.dumps(recs))


def test_plain_on_disk() -> None:
    print("no banned character reaches a stored file or a PDF")
    md = ("# Notes %s first draft\n\nIt%ss %sfine%s %s really %s\n\n- %s shipped\n- next %s later\n"
          % (EM, RSQ, LDQ, RDQ, EM, ROBOT, CHECK, RIGHT))
    rec = artifacts.store("plain", write("notes.md", md), title="Notes %s draft %s" % (EM, ROCKET),
                          pdf=True)
    text = stored("plain", rec).read_text(encoding="utf-8")
    check("the stored Markdown has no banned character and no emoji", not dirty(text), str(dirty(text)))
    check("and still says what it said",
          "It's \"fine\" - really" in text and "- yes shipped" in text and "next -> later" in text,
          repr(text))
    check("the record's title is plain too", not dirty(rec.get("title", "")), repr(rec.get("title")))
    pdf = made("plain", rec)
    check("the PDF was made", rec.get("kind") == "pdf" and pdf.is_file() and not rec.get("error"),
          json.dumps(rec))
    body = artifacts.pdf_text(pdf)
    check("and its text has none either", body and not dirty(body), str(dirty(body)) or repr(body[:80]))
    PDFS.append(pdf)

    page = ("<p>Ready &mdash; set&nbsp;go &rarr; now &#x1F680; and &#8220;done&#8221;</p>\n"
            "<p>A <q>quoted</q> word.</p>\n")
    rec = artifacts.store("plain", write("entities.html", page), title="Entities", pdf=True)
    body = artifacts.pdf_text(made("plain", rec))
    check("entities that spell banned characters are replaced before printing",
          rec.get("kind") == "pdf" and "Ready - set go -> now" in body and not dirty(body),
          str(dirty(body)) + " " + repr(body[:120]))
    PDFS.append(made("plain", rec))


def test_formats_survive() -> None:
    print("replacing quotes does not break the file around them")
    rec = artifacts.store("fmt", write("data.json", json.dumps(
        {"quote": "he said %shi%s %s ok" % (LDQ, RDQ, EM), "k%sey" % RSQ: 1}, ensure_ascii=False)),
        title="data")
    try:
        data = json.loads(stored("fmt", rec).read_text(encoding="utf-8"))
        ok = data.get("quote") == 'he said "hi" - ok' and data.get("k'ey") == 1
    except ValueError as e:
        data, ok = str(e), False
    check("a curly quote inside a JSON string leaves valid JSON", ok, repr(data))

    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(
        [["name", "note"], ["Acme", "said %sgo%s, then %s left" % (LDQ, RDQ, EM)],
         ["%sBeta%s" % (LDQ, RDQ), "plain"]])
    rec = artifacts.store("fmt", write("people.csv", buf.getvalue()), title="people")
    text = stored("fmt", rec).read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    check("a curly quote inside a CSV field leaves the same rows and columns",
          [len(r) for r in rows] == [2, 2, 2] and rows[1][0] == "Acme" and not dirty(text),
          repr(rows))

    rec = artifacts.store("fmt", write("page.html",
                          '<p><img src="x.png" alt="the %sPro%s plan"> It%ss here %s ok</p>\n'
                          % (LDQ, RDQ, RSQ, RIGHT)), title="page")
    text = stored("fmt", rec).read_text(encoding="utf-8")
    p = Attrs()
    p.feed(text)
    alts = [a.get("alt") for t, a in p.tags if t == "img"]
    check("a curly quote inside an HTML attribute leaves the attribute whole",
          alts == ['the "Pro" plan'] and "It's here -> ok" in "".join(p.text) and not dirty(text),
          repr(alts) + " " + repr(text))


def test_markdown_pdf() -> None:
    print("a Markdown document with a table and links becomes a PDF")
    md = ("# Companies worth a look\n\n"
          "| Company | Stage |\n|---|---|\n| Acme Robotics | Series A |\n| Beta Labs | Seed |\n\n"
          "- Apply through [the posting](https://jobs.example.com/p/123)\n"
          "- Read [their docs](https://docs.example.org/start) first\n"
          "- Or go straight to <https://example.net/raw>\n")
    rec = artifacts.store("md", write("Companies & Links.md", md), title="Companies", pdf=True)
    pdf = made("md", rec)
    check("it is stored and rendered",
          rec.get("kind") == "pdf" and pdf.suffix == ".pdf" and pdf.is_file() and not rec.get("error"),
          json.dumps(rec))
    check("under a safe name, with the source kept beside it",
          rec.get("source") == "companies-links.md" and rec.get("file") == "companies-links.pdf"
          and stored("md", rec).is_file(), json.dumps(rec))
    check("pages is at least 1 and bytes is the PDF's size",
          rec.get("pages", 0) >= 1 and pdf.is_file() and rec.get("bytes") == pdf.stat().st_size,
          json.dumps(rec))
    text = artifacts.pdf_text(pdf)
    check("a table cell's text is in the PDF", "Acme Robotics" in text, repr(text[:300]))
    for url in ("https://jobs.example.com/p/123", "https://docs.example.org/start",
                "https://example.net/raw"):
        check("%s is printed" % url, url in text, repr(text[-300:]))
    check("an address that is already the link text is printed once",
          text.count("https://example.net/raw") == 1, repr(text[-200:]))
    check("the document's own h1 is kept and the title is not added on top",
          text.count("Companies") == 1, repr(text[:120]))
    PDFS.append(pdf)

    page = artifacts.to_html(write("inject.md", "Hi <script>alert(1)</script> <b>x</b> "
                                   "<img src=x onerror=alert(1)>\n"))
    check("raw HTML in Markdown comes out as text, not tags",
          "<script" not in page.lower() and "<b>x</b>" not in page and "<img src=x" not in page
          and "&lt;script&gt;" in page, page[-300:])
    page = artifacts.to_html(write("footer.md", "# Plain\n\nbody\n"), title="Plain")
    check("the page has no footer, no credit and no script",
          "<footer" not in page.lower() and "<script" not in page.lower()
          and not re.search(r"generated|powered by|made with", page, re.IGNORECASE), page[-300:])


def test_table_layout() -> None:
    print("a table with long addresses keeps its short words whole")
    long = ("https://jobs.betalabs.example.org/interns/applications/2027/summer"
            "?team=ml&season=summer-2027&ref=kiln")
    md = ("| Company | Stage | Remote | Headquarters | Apply |\n|---|---|---|---|---|\n"
          "| Acme Robotics | Series A | yes | Pittsburgh | [careers](https://acme.example.com/careers) |\n"
          "| Beta Labs | Seed | no | Montreal | [jobs page](%s) |\n"
          "| Gamma AI | Series B | yes | Singapore | %s |\n" % (long, long))
    rec = artifacts.store("table", write("table.md", md), title="Where to apply", pdf=True)
    text = artifacts.pdf_text(made("table", rec))
    words = ["Company", "Remote", "Headquarters", "Robotics", "Pittsburgh", "Montreal", "Singapore"]
    check("no short word is split across lines",
          rec.get("kind") == "pdf" and all(w in text for w in words),
          str([w for w in words if w not in text]) + " " + repr(text[:400]))
    check("and each long address is printed in full, wrapped rather than cut off",
          text.replace("\n", "").count(long) == 2, repr(text[-500:]))
    page = artifacts.to_html(stored("table", rec))
    check("an address in a cell is marked as one that may break anywhere",
          page.count('<span class="url">') == 3, page[-600:])
    # Text read back from a PDF includes text drawn off the edge of the page,
    # so only measuring the layout can show that the table fits.
    width = widest_table(page)
    check("the table fits inside the printed width of a Letter page",
          0 < width <= PRINT_WIDTH, "table right edge %s px, page %s px" % (width, PRINT_WIDTH))
    PDFS.append(made("table", rec))


# Letter is 8.5in wide and the margins are 0.75in each side: 7in at 96 px/in.
PRINT_WIDTH = 672


def widest_table(page_html: str) -> float:
    """Where the rightmost table edge lands when the page is laid out for print."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": PRINT_WIDTH, "height": 1000})
        ctx.route("**/*", lambda route: route.abort())
        tab = ctx.new_page()
        tab.emulate_media(media="print")
        tab.set_content(page_html)
        right = tab.evaluate("() => Math.max(0, ...Array.from(document.querySelectorAll('table'),"
                             " t => t.getBoundingClientRect().right))")
        browser.close()
    return right


def test_html_pdf() -> None:
    print("an HTML document renders too")
    page = ("<!doctype html>\n<html><head><title>Head title</title>\n"
            "<style>body { background: #0a0b0c; color: #fff; }</style>\n</head>\n<body>\n"
            "<h2>Quarterly notes</h2>\n"
            "<p>The report is <a href=\"https://example.com/report\">here</a> and the list\n"
            "is at <a href=\"https://example.com/list\">https://example.com/list</a>.</p>\n"
            "<table><tr><th>Name</th><th>Role</th></tr><tr><td>Dana Kim</td><td>Lead</td></tr></table>\n"
            "</body></html>\n")
    rec = artifacts.store("html", write("notes.html", page), title="Team notes", pdf=True)
    pdf = made("html", rec)
    text = artifacts.pdf_text(pdf)
    check("it is rendered", rec.get("kind") == "pdf" and rec.get("pages", 0) >= 1
          and not rec.get("error"), json.dumps(rec))
    check("its body is printed", "Quarterly notes" in text and "Dana Kim" in text, repr(text[:200]))
    check("its link's address is printed after the text",
          re.search(r"here\s*\(https://example\.com/report\)", text) is not None, repr(text[:300]))
    check("an address that is already the link text is printed once",
          text.count("https://example.com/list") == 1, repr(text[:300]))
    check("with no h1 of its own, the title leads the page",
          text.lstrip().startswith("Team notes"), repr(text[:80]))
    check("its head is left out, style and all",
          "Head title" not in text and "#0a0b0c" not in artifacts.to_html(stored("html", rec)),
          repr(text[:200]))
    page = artifacts.to_html(stored("html", rec))
    check("addresses in an HTML source are marked as ones that may break anywhere",
          '(<span class="url">https://example.com/report</span>)' in page
          and '<span class="url">https://example.com/list</span>' in page, page[-500:])
    PDFS.append(pdf)

    page = artifacts.to_html(write("styled.html",
                             "<style>.x { background: url(https://example.com/bg.png) }</style>\n"
                             "<p>see https://example.com/a?x=1&amp;y=2 and https://example.com/b&amp;"
                             " too</p>\n"))
    check("an address inside a style block is left exactly as it was",
          "url(https://example.com/bg.png)" in page
          and '<span class="url">https://example.com/a?x=1&amp;y=2</span>' in page, page[-400:])
    check("and a span never cuts an entity in two",
          '<span class="url">https://example.com/b&amp;</span>' in page, page[-400:])

    rec = artifacts.store("html", write("refresh.html",
                          '<p>Before</p>\n<meta http-equiv="refresh" content="0;url=https://example.com/away">\n'
                          "<p>Still here</p>\n"), title="Refresh", pdf=True)
    text = artifacts.pdf_text(made("html", rec))
    check("a page that asks to go elsewhere still prints itself",
          rec.get("kind") == "pdf" and "Still here" in text, json.dumps(rec) + " " + repr(text[:80]))
    # The print usually beats the refresh, so the PDF alone cannot show the
    # tag was removed. The page handed to the browser can.
    page = artifacts.to_html(stored("html", rec))
    check("the refresh tag never reaches the browser",
          "http-equiv" not in page.lower() and "Still here" in page, page[-300:])
    PDFS.append(made("html", rec))


def control_listener_sees_chrome() -> bool:
    """Without the block, Chromium does reach the listener. Proves the probe works."""
    from playwright.sync_api import sync_playwright
    listener = Listener()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('<img src="http://127.0.0.1:%d/control.png">' % listener.port,
                         wait_until="load")
        browser.close()
    return bool(listener.close())


def test_no_network() -> None:
    print("drawing a page never reaches the network")
    check("control: an unblocked Chromium does reach the local listener",
          control_listener_sees_chrome())
    listener = Listener()
    md = ("# Pictures\n\n![chart](https://example.com/x.png)\n\n"
          "![local](http://127.0.0.1:%d/y.png)\n\nText after the pictures.\n" % listener.port)
    seen: list[str] = []
    calls: list[str] = []
    real = artifacts._block

    class Spy:
        """Stands in for the route so the test sees what the handler did with it."""

        def __init__(self, route) -> None:
            self.route, self.request = route, route.request

        def abort(self, *a, **k):
            calls.append("abort")
            self.route.abort(*a, **k)

        def continue_(self, *a, **k):
            calls.append("continue")
            self.route.continue_(*a, **k)

    def counting(route):
        seen.append(route.request.url)
        real(Spy(route))

    artifacts._block = counting
    try:
        rec = artifacts.store("net", write("pictures.md", md), title="Pictures", pdf=True)
    finally:
        artifacts._block = real
    hits = listener.close()
    text = artifacts.pdf_text(made("net", rec))
    check("a document with remote pictures still renders",
          rec.get("kind") == "pdf" and "Text after the pictures" in text, json.dumps(rec))
    check("the remote picture was stopped at the route",
          "https://example.com/x.png" in seen, str(seen))
    check("every request the page made was aborted, none let through",
          len(calls) == len(seen) >= 2 and set(calls) == {"abort"}, "%r for %r" % (calls, seen))
    check("and the local one never reached the listener", hits == [] and len(seen) >= 2,
          "hits %r, routed %r" % (hits, seen))
    PDFS.append(made("net", rec))


def test_failures() -> None:
    print("failures come back as errors, never exceptions")
    res = artifacts.render_pdf("", TMP / "empty.pdf")
    check("render_pdf with nothing to draw says so",
          res.get("ok") is False and res.get("error") and set(res) == {"ok", "path", "pages", "error"},
          json.dumps(res))
    blocker = write("a-file", "x")
    res = artifacts.render_pdf("<p>x</p>", blocker / "under-a-file.pdf")
    check("render_pdf into a folder that cannot exist says so",
          res.get("ok") is False and bool(res.get("error")), json.dumps(res))

    real = artifacts.render_pdf
    artifacts.render_pdf = lambda html, dest: {"ok": False, "path": str(dest), "pages": 0,
                                               "error": "the renderer broke"}
    try:
        rec = artifacts.store("fail", write("broken.md", "# Broken\n"), title="Broken", pdf=True)
    finally:
        artifacts.render_pdf = real
    check("a failed render returns the record with the error, pointing at the source",
          rec.get("error") == "the renderer broke" and rec.get("file") == "broken.md"
          and rec.get("source") == "broken.md" and rec.get("kind") == "md", json.dumps(rec))
    check("and the source is still kept and listed",
          stored("fail", rec).is_file() and [r.get("file") for r in artifacts.list_for("fail")] == ["broken.md"],
          json.dumps(artifacts.list_for("fail")))

    pdfs = [p for p in PDFS if p.is_file()]
    if pdfs:
        rec = artifacts.store("copy", pdfs[0], title="A PDF kept as it is")
        check("a PDF stored as a source keeps its pages",
              rec.get("kind") == "pdf" and rec.get("pages", 0) >= 1 and rec.get("file") == rec.get("source"),
              json.dumps(rec))
    else:
        check("a PDF stored as a source keeps its pages", False, "no PDF was made to store")

    check("pdf_text of a Markdown file is empty", artifacts.pdf_text(write("x.md", "# x\n")) == "")
    fake = WORK / "fake.pdf"
    fake.write_bytes(b"%PDF-1.4\nnot really a pdf\n")
    check("pdf_text of a file that only claims to be a PDF is empty", artifacts.pdf_text(fake) == "")
    check("pdf_text of a missing file is empty", artifacts.pdf_text(WORK / "nope.pdf") == "")


def test_no_credit() -> None:
    print("no PDF carries a credit line")
    from pypdf import PdfReader
    credit = re.compile(r"\b(generated|created|made|produced|built|powered|written)\s+(by|with|using)\b",
                        re.IGNORECASE)
    pdfs = [p for p in PDFS if p.is_file()]
    check("there are PDFs to look at", len(pdfs) >= 4, str(PDFS))
    for pdf in pdfs:
        text = artifacts.pdf_text(pdf)
        meta = " ".join(str(v) for v in (PdfReader(str(pdf)).metadata or {}).values())
        hits = [m.group(0) for m in credit.finditer(text)]
        hits += [name for rx, name in slop.ATTRIBUTION if re.search(rx, text + " " + meta, re.IGNORECASE)]
        hits += [rx for rx in slop.TOOL_NAMES if re.search(rx, (text + " " + meta).lower())]
        check("%s/%s has no credit in its text or metadata" % (pdf.parent.name, pdf.name),
              not hits, str(hits))


def test_markdown_fragment() -> None:
    print("markdown() gives a fragment for the page")
    frag = artifacts.markdown("Hello **there**, see [x](https://example.com).\n\n"
                              "<script>alert(1)</script> %s done\n" % EM)
    check("with a paragraph and no page around it", "<p>" in frag and "<html" not in frag, frag)
    check("raw HTML shown as text", "<script" not in frag.lower(), frag)
    check("and no banned character", not dirty(frag), str(dirty(frag)))

    # The shape of the first live answer: one fact per line, bare addresses.
    lines = artifacts.markdown("1. RAG crash course\nhttps://www.youtube.com/watch?v=o126p1QN_RI\n"
                               "Krish Naik, about 2 hours.")
    check("a single line break is kept on screen", "<br" in lines, lines)
    check("a bare address becomes a link, trailing full stop left outside it",
          '<a href="https://www.youtube.com/watch?v=o126p1QN_RI">' in lines, lines)
    linked = artifacts.markdown("see [the video](https://example.com/v) and https://example.com/v.")
    check("an address already inside a link is not linked twice",
          linked.count('href="https://example.com/v"') == 2 and "</a></a>" not in linked, linked)
    odd = artifacts.markdown("javascript:alert(1) and ftp://example.com/x")
    check("only web addresses are linked", "<a " not in odd, odd)


TESTS = [test_plain, test_safe_name, test_item_dir, test_refuses, test_records,
         test_plain_on_disk, test_formats_survive, test_markdown_pdf, test_table_layout,
         test_html_pdf,
         test_no_network, test_failures, test_no_credit, test_markdown_fragment]


def main() -> int:
    try:
        for test in TESTS:
            try:
                test()
            except Exception as e:
                check("%s ran to the end" % test.__name__, False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
