"""Documents made for an item, kept beside it and printed when I ask.

Sometimes a note is not enough and I want the thing itself: put all of this
in a PDF. The part that does the work writes Markdown or HTML, and this is
where it lands. Each item gets a folder under data/artifacts with the files
in it and an index.json saying what each one is.

A PDF is drawn by the headless Chromium that already reads posts, with
JavaScript off and every request refused, so printing never fetches a
picture, a font or a tracking pixel from anywhere. Every link's address is
written out after its text, because on paper a link is only its address.

Only a short list of file kinds is ever kept, text is written without the
characters slop.py bans, and nothing here raises: a failure comes back as a
dict with an "error" key.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import threading
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from . import config, slop

ARTIFACTS = config.DATA / "artifacts"
DOC_SOURCES = {".md", ".html"}
KEEP = {".pdf", ".md", ".html", ".csv", ".txt", ".json"}

INDEX = "index.json"
MARGIN = {"top": "0.75in", "right": "0.75in", "bottom": "0.75in", "left": "0.75in"}
_INDEX_LOCK = threading.Lock()

# One print style for every document. System fonts only, since nothing can be
# fetched while a page is drawn. Only an address may break at any character:
# when words can, a table squeezes its narrow columns until they split. The q
# rule is there because Chromium puts curly quotes round a <q> on its own.
CSS = """
body { font-family: system-ui, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 10.5pt; line-height: 1.45; color: #111; margin: 0; overflow-wrap: break-word; }
.url { overflow-wrap: anywhere; }
h1 { font-size: 18pt; line-height: 1.2; margin: 0 0 12pt; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; }
h4, h5, h6 { font-size: 10.5pt; margin: 12pt 0 4pt; }
h1, h2, h3, h4, h5, h6 { break-after: avoid; }
p, ul, ol, pre, table, blockquote { margin: 0 0 8pt; }
li { margin: 0 0 2pt; }
table { width: 100%; border-collapse: collapse; }
th, td { border: 0.75pt solid #999; padding: 3pt 6pt; text-align: left; vertical-align: top; }
th { font-weight: 600; }
tr { break-inside: avoid; }
code, pre { font-family: Consolas, "Cascadia Mono", Menlo, "Courier New", monospace;
  font-size: 9.5pt; }
pre { white-space: pre-wrap; border: 0.75pt solid #ccc; padding: 6pt 8pt; }
blockquote { margin-left: 0; padding-left: 10pt; border-left: 2pt solid #ccc; color: #333; }
img { max-width: 100%; }
a { color: inherit; }
hr { border: 0; border-top: 0.75pt solid #bbb; margin: 12pt 0; }
q { quotes: '"' '"' "'" "'"; }
"""


def _folder(item_id: str) -> Path:
    # handoff._path's rule. A name that is only dots would be this folder or
    # its parent, so those become hyphens.
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in str(item_id))
    if not safe.strip("."):
        safe = "-" * max(len(safe), 1)
    return ARTIFACTS / safe


def item_dir(item_id: str) -> Path:
    """The folder that holds one item's documents, made on first use."""
    d = _folder(item_id)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # store() finds out when it writes, and says so
    return d


def safe_name(name: str) -> str:
    """A bare file name that reads the same on every system and in a URL.

    Lowercase letters, digits, dots, underscores and hyphens, no directory
    part, no leading dot, at most 80 characters with the suffix kept.
    """
    base = re.split(r"[\\/]", str(name or ""))[-1].lower()
    base = re.sub(r"[^a-z0-9._-]+", "-", base).lstrip(".")
    if not base:
        return "file"
    if len(base) > 80:
        suffix = Path(base).suffix
        if len(suffix) >= 80:
            suffix = ""
        base = base[:80 - len(suffix)] + suffix
    return base


def markdown(text: str) -> str:
    """Markdown as an HTML fragment for a page on screen rather than paper.

    Links stay clickable and are not spelled out. Raw HTML in the text comes
    out as text, since the text came from a model.
    """
    try:
        body, _ = _from_markdown(str(text or ""), spell_urls=False, screen=True)
    except Exception:
        body = "<p>%s</p>" % _html.escape(str(text or ""))
    return _scrub(body)


def to_html(src: Path, title: str = "") -> str:
    """One printable page for a .md or .html source, or "" if it cannot be read.

    Whatever the source, the page gets the same print style, and the title
    becomes its heading when the document has no h1 of its own.
    """
    src = Path(src)
    try:
        text = src.read_bytes().decode("utf-8-sig", errors="replace")
        if src.suffix.lower() == ".md":
            body, has_h1 = _from_markdown(text, spell_urls=True)
        elif src.suffix.lower() == ".html":
            body, has_h1 = _from_html(text)
        else:
            return ""
    except Exception:
        return ""
    title = str(title or "").strip()
    if title and not has_h1:
        body = "<h1>%s</h1>\n%s" % (_html.escape(title), body)
    return _scrub(_page(title or src.stem, body))


def _page(title: str, body: str) -> str:
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
            % (_html.escape(title), CSS, body))


def _from_markdown(text: str, spell_urls: bool,
                   screen: bool = False) -> tuple[str, bool]:
    from markdown_it import MarkdownIt
    from markdown_it.token import Token

    # Raw HTML is off so text from a model cannot become tags. Linkify stays
    # off because it needs another package, linkify-it-py. On screen a single
    # line break is kept: an answer written one fact per line otherwise runs
    # together into one paragraph, which is what the first live one did.
    md = MarkdownIt("commonmark", {"html": False, "breaks": screen}).enable("table")
    env: dict = {}
    tokens = md.parse(text, env)
    for tok in tokens:
        if tok.type == "inline" and tok.children:
            if spell_urls:
                tok.children = _mark_urls(_spell_links(tok.children, Token), Token)
            if screen:
                tok.children = _link_bare(tok.children, Token)
    has_h1 = any(t.type == "heading_open" and t.tag == "h1" for t in tokens)
    return md.renderer.render(tokens, md.options, env), has_h1


# A web address written out in the text rather than as a link. Trailing
# punctuation stays outside it, the way a reader would take the sentence.
_BARE_URL = re.compile(r"https?://[^\s<>()\[\]\"']*[^\s<>()\[\]\"'.,;:!?]")


def _link_bare(children: list, Token) -> list:
    """Make bare http and https addresses clickable, outside existing links."""
    out: list = []
    inside = 0
    for tok in children:
        if tok.type == "link_open":
            inside += 1
        elif tok.type == "link_close":
            inside -= 1
        if tok.type != "text" or inside or not _BARE_URL.search(tok.content):
            out.append(tok)
            continue
        at = 0
        for m in _BARE_URL.finditer(tok.content):
            if m.start() > at:
                out.append(Token("text", "", 0, content=tok.content[at:m.start()]))
            a = Token("link_open", "a", 1)
            a.attrSet("href", m.group(0))
            out += [a, Token("text", "", 0, content=m.group(0)), Token("link_close", "a", -1)]
            at = m.end()
        if at < len(tok.content):
            out.append(Token("text", "", 0, content=tok.content[at:]))
    return out


def _spell_links(children: list, Token) -> list:
    """Follow each link with its address, as text, unless its text already is that."""
    out: list = []
    opened: list[tuple[str, int]] = []
    for tok in children:
        out.append(tok)
        if tok.type == "link_open":
            opened.append((str(tok.attrGet("href") or ""), len(out)))
        elif tok.type == "link_close" and opened:
            href, start = opened.pop()
            shown = "".join(t.content for t in out[start:-1]
                            if t.type in ("text", "code_inline"))
            if _needs_url(shown, href):
                out.append(Token("text", "", 0, content=" (%s)" % href))
    return out


_URL = re.compile(r"https?://[^\s<>\"'()]*[^\s<>\"'().,;:!?]")
# In raw HTML an ampersand starts an entity, which a span must not cut in two.
_RAW_URL = re.compile(r"https?://(?:&#?[A-Za-z0-9]+;|[^\s<>\"'()&])*"
                      r"(?:&#?[A-Za-z0-9]+;|[^\s<>\"'().,;:!?&])")
_URL_OPEN, _URL_CLOSE = '<span class="url">', "</span>"


def _mark_urls(children: list, Token) -> list:
    """Wrap every address in the text in a span the print style lets break anywhere."""
    out: list = []
    for tok in children:
        if tok.type != "text" or "://" not in tok.content:
            out.append(tok)
            continue
        last = 0
        for m in _URL.finditer(tok.content):
            out += [Token("text", "", 0, content=tok.content[last:m.start()]),
                    Token("html_inline", "", 0, content=_URL_OPEN),
                    Token("text", "", 0, content=m.group(0)),
                    Token("html_inline", "", 0, content=_URL_CLOSE)]
            last = m.end()
        out.append(Token("text", "", 0, content=tok.content[last:]))
    return out


def _needs_url(shown: str, href: str) -> bool:
    href = href.strip()
    if not href or href.startswith("#"):
        return False  # nothing to print, or a place in this same document
    shown = " ".join(shown.split())
    same = {href, unquote(href)}
    if href.lower().startswith("mailto:"):
        same |= {href[7:], unquote(href[7:])}
    return shown not in same


class _Scan(HTMLParser):
    """Where an HTML source needs changing, found in one read.

    Nothing is rebuilt from this parse. The browser gets the original text
    with a few spans cut and a few addresses added, which trusts this parser
    far less than asking it to write the whole page back out.
    """

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.lines = [0] + [m.end() for m in re.finditer("\n", raw)]
        self.body: list = [None, None]
        self.h1: list[int] = []
        self.edits: list[tuple[int, int, str]] = []
        self.link: tuple[str, list[str]] | None = None
        self.code = False

    def _at(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        at = self._at()
        end = at + len(self.get_starttag_text() or "")
        if tag in ("script", "style"):
            self.code = True
        elif tag == "body" and self.body[0] is None:
            self.body[0] = end
        elif tag == "h1":
            self.h1.append(at)
        elif tag == "meta":
            # A refresh sends the page elsewhere once it loads and the PDF
            # comes out blank. No meta tag changes how a page looks.
            self.edits.append((at, end, ""))
        elif tag == "a":
            self.finish_link(at)
            self.link = (dict(attrs).get("href") or "", [])

    def handle_endtag(self, tag):
        at = self._at()
        if tag in ("script", "style"):
            self.code = False
        elif tag == "body":
            self.body[1] = at
        elif tag == "a":
            gt = self.raw.find(">", at)
            self.finish_link(gt + 1 if gt >= 0 else len(self.raw))

    def handle_data(self, data):
        if self.link:
            self.link[1].append(data)
        if self.code or "://" not in data:
            return
        at = self._at()
        stop = self.raw.find("<", at)
        for m in _RAW_URL.finditer(self.raw, at, stop if stop >= 0 else len(self.raw)):
            self.edits.append((m.start(), m.start(), _URL_OPEN))
            self.edits.append((m.end(), m.end(), _URL_CLOSE))

    def finish_link(self, at: int) -> None:
        if self.link:
            href, parts = self.link
            self.link = None
            if _needs_url("".join(parts), href):
                self.edits.append((at, at, " (%s%s%s)" % (_URL_OPEN, _html.escape(href),
                                                         _URL_CLOSE)))


def _from_html(raw: str) -> tuple[str, bool]:
    scan = _Scan(raw)
    scan.feed(raw)
    scan.close()
    start = scan.body[0] if scan.body[0] is not None else 0
    end = scan.body[1] if scan.body[1] is not None and scan.body[1] >= start else len(raw)
    scan.finish_link(end)
    body = raw[start:end]
    # Last first, so earlier offsets stay true. Two insertions at one spot are
    # applied in reverse, which leaves them in the order they were found.
    order = sorted(range(len(scan.edits)), key=lambda i: (scan.edits[i][0], i), reverse=True)
    for a, b, text in (scan.edits[i] for i in order):
        if start <= a and b <= end:
            body = body[:a - start] + text + body[b - start:]
    return body, any(start <= p < end for p in scan.h1)


# A browser decodes entities, so &mdash; prints an em dash from a file that is
# all ASCII. An entity standing for a banned character or an emoji is written
# out as the character, so it is replaced along with the rest.
_ENTITY = re.compile(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);"
                     r"|&(?:nbsp|middot)(?![=;A-Za-z0-9])")


def _unentity(markup: str) -> str:
    def spell(m):
        ch = _html.unescape(m.group(0))
        return ch if slop.plain(ch) != ch else m.group(0)
    return _ENTITY.sub(spell, markup)


# A plain spelling can hold a quote or an angle bracket, and those mean
# something in these formats: a curly quote inside a JSON string must not end
# the string. So the spelling is escaped for the file it lands in. CSV has no
# escape that works outside a quoted field, so its double quote goes single.
_ESCAPE = {
    ".html": _html.escape,
    ".json": lambda s: json.dumps(s)[1:-1],
    ".csv": lambda s: s.replace('"', "'"),
}


def _plain(text: str, suffix: str) -> str:
    esc = _ESCAPE.get(suffix)
    if esc:
        for ch in slop.BANNED_CHARS:
            spelled = slop.plain("x%sx" % ch)[1:-1]
            if ch in text and esc(spelled) != spelled:
                text = text.replace(ch, esc(spelled))
    return slop.plain(text)


def _scrub(markup: str) -> str:
    return _plain(_unentity(markup), ".html")


def _block(route) -> None:
    """Refuse every request that is not the page itself."""
    if route.request.url.startswith(("data:", "about:")):
        route.continue_()
    else:
        route.abort("blockedbyclient")


def render_pdf(html: str, dest: Path) -> dict:
    """Print a page to a Letter PDF with no scripts and no network.

    The PDF is written beside dest first and only moved into place once it
    reads back with a page in it, so a failed render never leaves a broken
    file where a good one is expected.
    """
    dest = Path(dest)
    out = {"ok": False, "path": str(dest), "pages": 0, "error": ""}
    if not str(html or "").strip():
        out["error"] = "nothing to render"
        return out
    part = dest.with_name(dest.name + ".part")
    try:
        from playwright.sync_api import sync_playwright
        from pypdf import PdfReader

        dest.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(java_script_enabled=False, offline=True,
                                          service_workers="block")
                ctx.route("**/*", _block)
                page = ctx.new_page()
                page.set_content(html, wait_until="load", timeout=60000)
                page.pdf(path=str(part), format="Letter", margin=MARGIN,
                         print_background=True, display_header_footer=False)
                if page.url.split("#")[0] != "about:blank":
                    raise RuntimeError("the page went to %s instead of printing" % page.url)
            finally:
                browser.close()
        pages = len(PdfReader(str(part)).pages)
        if pages < 1:
            raise RuntimeError("the PDF came out with no pages")
        os.replace(part, dest)
        out.update(ok=True, pages=pages)
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    try:
        part.unlink(missing_ok=True)
    except OSError:
        pass
    return out


def pdf_text(path: Path) -> str:
    """The text of a PDF, or "" if it is not one or cannot be read."""
    try:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    except Exception:
        return ""


def _pages(path: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:
        return 0


def store(item_id: str, src: Path, *, title: str, about: str = "",
          pdf: bool = False) -> dict:
    """Keep a copy of src with the item, and a PDF of it when asked for one.

    The record that comes back is also written to the folder's index.json,
    in place of any record for a file this one overwrote.
    """
    try:
        return _store(str(item_id), Path(src), str(title or ""), str(about or ""), pdf)
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}


def _store(item_id: str, src: Path, title: str, about: str, pdf: bool) -> dict:
    name = safe_name(src.name)
    if name == INDEX:
        name = "index-1.json"  # that name is the listing itself
    kind = Path(name).suffix
    if kind not in KEEP:
        return {"error": "not keeping %s: only %s files are kept"
                % (src.name, ", ".join(sorted(KEEP)))}
    try:
        data = src.read_bytes()
    except OSError as e:
        return {"error": "cannot read %s: %s" % (src, e)}
    if kind != ".pdf":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return {"error": "%s is not UTF-8 text; save it as UTF-8 and store it again"
                    % src.name}
        if kind == ".html":
            text = _unentity(text)
        data = _plain(text, kind).encode("utf-8")

    folder = item_dir(item_id)
    if folder.resolve().parent != ARTIFACTS.resolve():
        return {"error": "refusing to write outside %s" % ARTIFACTS}
    dest = folder / name
    try:
        dest.write_bytes(data)
    except OSError as e:
        return {"error": "cannot write %s: %s" % (dest, e)}

    rec = {"file": name, "source": name, "title": slop.plain(title),
           "about": slop.plain(about), "kind": kind[1:], "bytes": len(data),
           "pages": _pages(dest) if kind == ".pdf" else 0}
    if pdf and kind in DOC_SOURCES:
        page = to_html(dest, rec["title"])
        res = (render_pdf(page, folder / safe_name(dest.stem + ".pdf")) if page
               else {"ok": False, "error": "could not turn %s into a page" % name})
        if res.get("ok"):
            made = Path(res["path"])
            rec.update(file=made.name, kind="pdf", bytes=made.stat().st_size,
                       pages=res["pages"])
        else:
            rec["error"] = res.get("error") or "the PDF could not be made"
    problem = _remember(folder, rec)
    if problem:
        rec["error"] = problem
    return rec


def _remember(folder: Path, rec: dict) -> str:
    """Put a record in the index, dropping any whose file it overwrote."""
    names = {rec["file"], rec["source"]}
    try:
        with _INDEX_LOCK:
            recs = [r for r in _read_index(folder)
                    if not names & {r.get("file"), r.get("source")}]
            recs.append(rec)
            part = folder / (INDEX + ".part")
            part.write_text(json.dumps(recs, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(part, folder / INDEX)
    except OSError as e:
        return "kept, but index.json could not be written: %s" % e
    return ""


def _read_index(folder: Path) -> list[dict]:
    try:
        recs = json.loads((folder / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in recs if isinstance(r, dict)] if isinstance(recs, list) else []


def list_for(item_id: str) -> list[dict]:
    """What is kept for an item, read from its index.json. [] if nothing is."""
    return _read_index(_folder(item_id))
