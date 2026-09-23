"""Fetch the media behind a link.

Instagram needs a real browser. The API is closed, instaloader and yt-dlp
both hit login walls, and scraping the HTML only gets you the first slide.
A headless browser works, needs no login, and nothing to ban.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import config

SHORTCODE_RE = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")
YT_RE = re.compile(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)")
TIKTOK_RE = re.compile(r"tiktok\.com/")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


@dataclass
class Acquired:
    url: str
    kind: str                       # instagram | youtube | tiktok | web
    shortcode: str = ""
    owner: str = ""
    posted: str = ""
    caption: str = ""
    like_count: int = 0
    comment_count: int = 0
    comments: list[dict] = field(default_factory=list)
    slides: list[str] = field(default_factory=list)   # local paths, in order
    video: str = ""
    pdf: str = ""
    title: str = ""
    body_text: str = ""
    focus_slide: int | None = None   # from ?img_index=N - the slide THEY meant
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def classify(url: str) -> str:
    if SHORTCODE_RE.search(url):
        return "instagram"
    if YT_RE.search(url):
        return "youtube"
    if TIKTOK_RE.search(url):
        return "tiktok"
    return "web"


def _media_dir(key: str) -> Path:
    d = config.MEDIA / key
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Instagram, via a real browser
# ---------------------------------------------------------------------------
_CAROUSEL_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const seen = new Map();
  const grab = () => {
    for (const i of document.querySelectorAll('img')) {
      if (i.naturalWidth < 900) continue;              // grid thumbs are 480px
      const k = i.src.split('?')[0];
      if (!seen.has(k)) seen.set(k, i.src);
    }
  };
  const nextBtn = () => document.querySelector(
    'button[aria-label="Next"], div[role="button"][aria-label="Next"]');
  const prevBtn = () => document.querySelector(
    'button[aria-label="Go back"], div[role="button"][aria-label="Go back"], ' +
    'button[aria-label="Previous"], div[role="button"][aria-label="Previous"]');

  // REWIND FIRST. A shared URL carries ?img_index=N and Instagram opens on
  // that slide, so walking only forward silently drops slides 1..N-1.
  for (let i = 0; i < 30; i++) {
    const p = prevBtn();
    if (!p) break;
    p.click();
    await sleep(750);
  }
  await sleep(600);
  // Only NOW start collecting, so Map insertion order == true slide order.
  seen.clear();
  grab();
  for (let i = 0; i < 30; i++) {
    const b = nextBtn();
    if (!b) break;
    b.click();
    await sleep(900);
    grab();
  }
  // caption + counts from the article shell
  const art = document.querySelector('article') || document.body;
  const text = art.innerText || '';
  const vids = [...document.querySelectorAll('video')].map(v => v.src || (v.querySelector('source')||{}).src).filter(Boolean);
  return { slides: [...seen.values()], text: text.slice(0, 4000), videos: vids };
}
"""

_COMMENTS_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // open the thread
  for (const el of document.querySelectorAll('a,span,button,div[role="button"]')) {
    const t = (el.innerText || '').toLowerCase();
    if (t.startsWith('view all') && t.includes('comment')) { el.click(); break; }
  }
  await sleep(2000);
  // load more a few times
  for (let i = 0; i < 6; i++) {
    const more = [...document.querySelectorAll('button,div[role="button"]')]
      .find(b => /load more|view more|more comments/i.test(b.innerText || ''));
    if (!more) break;
    more.click();
    await sleep(1400);
  }
  const out = [];
  for (const li of document.querySelectorAll('ul li, div[role="listitem"]')) {
    const txt = (li.innerText || '').trim();
    if (!txt || txt.length < 3 || txt.length > 1200) continue;
    const a = li.querySelector('a[href^="/"]');
    out.push({ who: a ? a.getAttribute('href').replace(/\//g, '') : '', text: txt.slice(0, 600) });
    if (out.length > 300) break;
  }
  return out;
}
"""


def acquire_instagram(url: str, *, want_comments: bool = True,
                      headless: bool = True, timeout_ms: int = 45000) -> Acquired:
    m = SHORTCODE_RE.search(url)
    if not m:
        return Acquired(url=url, kind="instagram", error="no shortcode in URL")
    sc = m.group(1)
    res = Acquired(url=url, kind="instagram", shortcode=sc)

    fi = re.search(r"img_index=(\d+)", url)
    if fi:
        res.focus_slide = int(fi.group(1))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        res.error = "playwright not installed (pip install playwright && playwright install chromium)"
        return res

    out_dir = _media_dir(sc)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 1400},
                                      locale="en-US")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3500)
            _dismiss(page)

            data = page.evaluate(_CAROUSEL_JS)
            srcs: list[str] = data.get("slides", [])
            text: str = data.get("text", "")
            videos: list[str] = data.get("videos", [])

            # Metadata: OpenGraph first (reliable, login-free), DOM as fallback.
            og = fetch_og(url)
            if og.get("caption"):
                res.caption = og["caption"]
                res.owner = og.get("owner", "")
                res.posted = og.get("posted", "")
                res.like_count = og.get("like_count", 0)
                res.comment_count = og.get("comment_count", 0)
            else:
                res.caption, res.owner, res.like_count, res.comment_count = _parse_shell(text)
            if res.owner.lower() in ("log in", "sign up", ""):
                res.owner = og.get("owner", "") or ""

            # download slides through the SAME browser context so the CDN sees
            # the same session/referer that was issued the signed URL
            for i, src in enumerate(srcs, 1):
                ext = ".webp" if ".webp" in src.split("?")[0] else ".jpg"
                dest = out_dir / f"{sc}_{i:02d}{ext}"
                if dest.exists() and dest.stat().st_size > 0:
                    res.slides.append(str(dest))
                    continue
                try:
                    buf = ctx.request.get(src, timeout=timeout_ms).body()
                    dest.write_bytes(buf)
                    res.slides.append(str(dest))
                except Exception:
                    pass

            for j, v in enumerate(videos[:1], 1):
                try:
                    dest = out_dir / f"{sc}_video{j}.mp4"
                    dest.write_bytes(ctx.request.get(v, timeout=timeout_ms).body())
                    res.video = str(dest)
                except Exception:
                    pass

            if want_comments:
                try:
                    raw = page.evaluate(_COMMENTS_JS)
                    res.comments = _clean_comments(raw, res.caption, res.owner)
                except Exception:
                    pass

            ctx.close()
            browser.close()
    except Exception as e:
        res.error = f"{type(e).__name__}: {str(e)[:250]}"

    if res.slides:
        res.pdf = build_pdf(res.slides, out_dir / f"{sc}.pdf")
    if not res.slides and not res.video and not res.error:
        res.error = "browser loaded the page but found no media"
    return res


_OG_UA = "facebookexternalhit/1.1"
_OG_RE = re.compile(r'<meta property="og:([a-z_:]+)" content="(.*?)"\s*/?>')
# og:description looks like:
#   985 likes, 810 comments - techyy_bandaa on September 17, 2026: "caption"
_OG_DESC_RE = re.compile(
    r"([\d,]+)\s+likes?,\s*([\d,]+)\s+comments?\s*[--]\s*([\w.]+)\s+on\s+(.+?):\s*(.*)",
    re.S,
)


def fetch_og(url: str) -> dict:
    """Metadata via OpenGraph.

    Measured: Instagram serves full og: tags to a crawler UA with no login,
    while a headless browser gets the logged-out shell whose innerText is
    nav chrome ("Log In" / "Sign Up"). So metadata comes from here and only
    the pixels come from the browser.
    """
    import html as _html
    import urllib.request
    out: dict = {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _OG_UA,
                                                   "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=40) as r:
            doc = r.read().decode("utf-8", "replace")
    except Exception:
        return out
    tags = {m.group(1): _html.unescape(m.group(2)) for m in _OG_RE.finditer(doc)}
    desc = tags.get("description", "")
    m = _OG_DESC_RE.search(desc)
    if m:
        out["like_count"] = int(m.group(1).replace(",", ""))
        out["comment_count"] = int(m.group(2).replace(",", ""))
        out["owner"] = m.group(3)
        out["posted"] = m.group(4).strip()
        out["caption"] = m.group(5).strip().strip('"').strip()
    if not out.get("caption"):
        t = tags.get("title", "")
        mt = re.search(r'on Instagram:\s*["""](.*)["""]\s*$', t, re.S)
        if mt:
            out["caption"] = mt.group(1).strip()
    if not out.get("owner"):
        mo = re.search(r"instagram\.com/([\w.]+)/p/", tags.get("url", ""))
        if mo:
            out["owner"] = mo.group(1)
    return out


def _dismiss(page) -> None:
    """Close the cookie banner / login nag that covers the carousel arrows."""
    for sel in ('button:has-text("Allow all cookies")',
                'button:has-text("Decline optional cookies")',
                'button:has-text("Not Now")',
                'div[role="dialog"] button[aria-label="Close"]',
                'svg[aria-label="Close"]'):
        try:
            el = page.query_selector(sel)
            if el:
                el.click(timeout=2500)
                page.wait_for_timeout(700)
        except Exception:
            pass


_COUNT_RE = re.compile(r"([\d,.]+)\s*(likes?|comments?)", re.I)


def _parse_shell(text: str) -> tuple[str, str, int, int]:
    """Pull caption/owner/counts out of the article's innerText."""
    owner = ""
    likes = comments = 0
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        owner = lines[0].lstrip("@")
    for m in _COUNT_RE.finditer(text):
        n = int(re.sub(r"[^\d]", "", m.group(1)) or 0)
        if m.group(2).lower().startswith("like"):
            likes = max(likes, n)
        else:
            comments = max(comments, n)
    caption = ""
    for i, l in enumerate(lines):
        if l.lstrip("@") == owner and i + 1 < len(lines):
            cand = lines[i + 1]
            if not re.match(r"^(follow|*|\d[\d,.]*\s*(likes?|comments?))$", cand, re.I) and len(cand) > len(caption):
                caption = cand
    return caption, owner, likes, comments


_NOISE = re.compile(r"^(reply|see translation|follow|verified|\d+[wdhm]|like[sd]?)$", re.I)


def _clean_comments(raw: list[dict], caption: str, owner: str) -> list[dict]:
    out, seen = [], set()
    for c in raw or []:
        t = " ".join((c.get("text") or "").split())
        if not t or t in seen or _NOISE.match(t):
            continue
        if caption and caption[:40] and caption[:40] in t:
            continue          # the caption re-rendered inside the thread
        seen.add(t)
        out.append({"who": c.get("who", ""), "text": t[:600]})
    return out[:200]


# ---------------------------------------------------------------------------
# Carousel -> single PDF
# ---------------------------------------------------------------------------
def build_pdf(image_paths: list[str], dest: Path) -> str:
    """Bind carousel slides into one PDF, in order. Returns '' on failure."""
    try:
        from PIL import Image
    except ImportError:
        return ""
    pages = []
    for p in image_paths:
        try:
            im = Image.open(p)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")
            pages.append(im)
        except Exception:
            continue
    if not pages:
        return ""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        pages[0].save(dest, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)
        return str(dest)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# YouTube / TikTok / web
# ---------------------------------------------------------------------------
def acquire_youtube(url: str) -> Acquired:
    res = Acquired(url=url, kind="youtube")
    try:
        import yt_dlp
    except ImportError:
        res.error = "yt-dlp not installed"
        return res
    try:
        with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True}) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        res.error = f"{type(e).__name__}: {str(e)[:200]}"
        return res
    res.shortcode = info.get("id", "")
    res.title = info.get("title", "")
    res.owner = info.get("uploader", "")
    res.posted = str(info.get("upload_date", ""))
    res.caption = (info.get("description") or "")[:8000]
    res.comment_count = info.get("comment_count") or 0
    res.body_text = res.caption
    return res


def acquire_web(url: str) -> Acquired:
    res = Acquired(url=url, kind="web")
    try:
        import trafilatura
        raw = trafilatura.fetch_url(url)
        if not raw:
            res.error = "could not fetch"
            return res
        res.body_text = trafilatura.extract(raw, include_comments=False) or ""
        md = trafilatura.extract_metadata(raw)
        if md:
            res.title = md.title or ""
            res.owner = md.author or ""
            res.posted = md.date or ""
    except ImportError:
        res.error = "trafilatura not installed"
    except Exception as e:
        res.error = f"{type(e).__name__}: {str(e)[:200]}"
    return res


def acquire(url: str, **kw) -> Acquired:
    kind = classify(url)
    if kind == "instagram":
        return acquire_instagram(url, **kw)
    if kind in ("youtube", "tiktok"):
        return acquire_youtube(url)
    return acquire_web(url)


if __name__ == "__main__":
    import sys
    r = acquire(sys.argv[1], headless=("--show" not in sys.argv))
    d = r.to_dict()
    d["comments"] = d["comments"][:5]
    print(json.dumps(d, indent=2, ensure_ascii=False)[:4000])
