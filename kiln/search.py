"""Search and fetch, so enrichment doesn't depend on anyone's quota.

Gemini's grounded search has its own tiny quota that ran out immediately,
so this does its own retrieval instead. No key, no account, no limit.
"""
from __future__ import annotations

import concurrent.futures as cf
import html as _html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

_DDG_HTML = "https://html.duckduckgo.com/html/?q="
_DDG_LITE = "https://lite.duckduckgo.com/lite/?q="

_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.S)
_LITE_RE = re.compile(r'<a[^>]+class="result-link"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.S)
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Hit:
    url: str
    title: str
    snippet: str = ""
    text: str = ""

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title,
                "snippet": self.snippet, "chars": len(self.text)}


def _clean(s: str) -> str:
    return " ".join(_html.unescape(_TAG_RE.sub("", s or "")).split())


def _unwrap(href: str) -> str:
    """DDG wraps results as /l/?uddg=<encoded>."""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        q = urllib.parse.urlparse(href).query
        got = urllib.parse.parse_qs(q).get("uddg")
        if got:
            return urllib.parse.unquote(got[0])
    return href


def _get(url: str, timeout: int = 20, data: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def search(query: str, n: int = 6, timeout: int = 20) -> list[Hit]:
    """Search the open web. Returns up to n hits; never raises."""
    q = urllib.parse.quote_plus(query)
    hits: list[Hit] = []
    seen: set[str] = set()

    for base, rx in ((_DDG_HTML, _RESULT_RE), (_DDG_LITE, _LITE_RE)):
        if len(hits) >= n:
            break
        try:
            doc = _get(base + q, timeout)
        except Exception:
            continue
        snippets = [_clean(s) for s in _SNIPPET_RE.findall(doc)]
        for i, m in enumerate(rx.finditer(doc)):
            url = _unwrap(m.group("href"))
            if not url.startswith("http"):
                continue
            key = url.split("#")[0].rstrip("/")
            if key in seen or "duckduckgo.com" in key:
                continue
            seen.add(key)
            hits.append(Hit(url=url, title=_clean(m.group("title")),
                            snippet=snippets[i] if i < len(snippets) else ""))
            if len(hits) >= n:
                break
    return hits


def fetch_text(url: str, max_chars: int = 6000, timeout: int = 20) -> str:
    """Readable text of a page. Prefers trafilatura, falls back to tag strip."""
    try:
        import trafilatura
        raw = trafilatura.fetch_url(url)
        if raw:
            t = trafilatura.extract(raw, include_comments=False, include_tables=True)
            if t:
                return t[:max_chars]
    except Exception:
        pass
    try:
        doc = _get(url, timeout)
        doc = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", doc, flags=re.S | re.I)
        return _clean(doc)[:max_chars]
    except Exception:
        return ""


def research(queries: list[str], per_query: int = 4, fetch: int = 5,
             max_chars: int = 5000) -> tuple[str, list[dict]]:
    """Search several queries, fetch the best pages, return (context, sources).

    `context` is ready to paste into a prompt; `sources` is the citation list.
    """
    hits: list[Hit] = []
    seen: set[str] = set()
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(lambda q: search(q, per_query), queries):
            for h in res:
                k = h.url.split("#")[0].rstrip("/")
                if k not in seen:
                    seen.add(k)
                    hits.append(h)

    # Prefer primary sources: official docs, GitHub, PyPI over listicles.
    def rank(h: Hit) -> int:
        u = h.url.lower()
        for i, pat in enumerate((
            "docs.", "/docs", "readthedocs", "github.com", "pypi.org",
            "npmjs.com", ".dev/", ".io/", "blog.",
        )):
            if pat in u:
                return i
        return 50

    hits.sort(key=rank)
    chosen = hits[:fetch]

    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        texts = list(ex.map(lambda h: fetch_text(h.url, max_chars), chosen))
    for h, t in zip(chosen, texts):
        h.text = t

    blocks, sources = [], []
    for i, h in enumerate(chosen, 1):
        if not (h.text or h.snippet):
            continue
        blocks.append(f"[{i}] {h.title}\nURL: {h.url}\n{(h.text or h.snippet)[:max_chars]}")
        sources.append({"n": i, "url": h.url, "title": h.title})
    for h in hits[fetch:fetch + 6]:
        sources.append({"n": None, "url": h.url, "title": h.title})
    return "\n\n---\n\n".join(blocks), sources


if __name__ == "__main__":
    import sys
    ctx, src = research(sys.argv[1:] or ["LangGraph latest version"])
    print("SOURCES:")
    for s in src:
        print("  ", s["n"], s["url"][:90])
    print("\nCONTEXT chars:", len(ctx))
    print(ctx[:1200])
