"""Fetch the media behind a link.

Instagram needs a real browser. The API is closed, instaloader and yt-dlp
both hit login walls, and scraping the HTML only gets you the first slide.
A headless browser works, needs no login, and nothing to ban.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.parse
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
    duration: int = 0
    error: str = ""
    # Things that went wrong without the whole acquisition failing, so
    # a half-result says what is missing instead of looking complete.
    notes: list[str] = field(default_factory=list)

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


def _full_asset(u: str) -> str:
    """The whole file, not the slice the player happened to ask for.

    Instagram streams a reel in ranges through bytestart/byteend. Fetching a
    url with those still on it returns a fragment: it starts with moof and
    carries no ftyp box, so nothing will open it. Drop them and the CDN
    hands over the complete asset.
    """
    p = urllib.parse.urlparse(u)
    q = urllib.parse.parse_qs(p.query)
    if not any(k in q for k in ("bytestart", "byteend")):
        return u
    for k in ("bytestart", "byteend"):
        q.pop(k, None)
    return urllib.parse.urlunparse(
        p._replace(query=urllib.parse.urlencode(q, doseq=True)))


def _mp4_tracks(data: bytes) -> tuple[bool, bool]:
    """(has_video, has_audio), read off the hdlr boxes.

    The handler type sits twelve bytes past the box name, so it is read from
    there rather than by looking for "vide" anywhere in the file. Twelve
    megabytes of video contains those four bytes by chance more than once.
    """
    has_v = has_a = False
    at = data.find(b"hdlr")
    while at != -1:
        kind = data[at + 12:at + 16]
        has_v = has_v or kind == b"vide"
        has_a = has_a or kind == b"soun"
        if has_v and has_a:
            break
        at = data.find(b"hdlr", at + 4)
    return has_v, has_a


def _save_video(ctx, dom_videos: list[str], seen_mp4: list[str],
                out_dir: Path, sc: str, timeout_ms: int) -> tuple[str, str]:
    """Save the reel. Returns (path, "") or ("", why it could not).

    Instagram serves the picture and the sound as separate renditions, so the
    biggest single file is usually silent. Both are kept and muxed when
    ffmpeg is around, because half of a reel is the person talking.
    """
    cands: list[str] = []
    for u in list(seen_mp4) + [v for v in dom_videos if v.startswith("http")]:
        full = _full_asset(u)
        if full not in cands:
            cands.append(full)
    if not cands:
        blobs = [v for v in dom_videos if v.startswith("blob:")]
        if blobs:
            return "", ("the player held the video in memory and the network "
                        "carried no mp4, so there was nothing to copy")
        return "", "no video on the page"

    best_v: tuple[int, bytes] = (0, b"")
    best_a: tuple[int, bytes] = (0, b"")
    refused = []
    for u in cands:
        try:
            body = ctx.request.get(u, timeout=timeout_ms).body()
        except Exception as e:
            refused.append(f"{type(e).__name__}")
            continue
        if b"ftyp" not in body[:64]:
            continue                      # a fragment, not a file
        has_v, has_a = _mp4_tracks(body)
        if has_v and len(body) > best_v[0]:
            best_v = (len(body), body)
        if has_a and not has_v and len(body) > best_a[0]:
            best_a = (len(body), body)

    if not best_v[0] and not best_a[0]:
        why = "every video url returned a fragment rather than a whole file"
        if refused:
            why = "could not fetch the video: " + ", ".join(sorted(set(refused))[:3])
        return "", why

    vid = out_dir / f"{sc}_video.mp4"
    if not best_v[0]:
        vid.write_bytes(best_a[1])
        return str(vid), "only the audio track came back, there is no picture"

    vid.write_bytes(best_v[1])
    if not best_a[0]:
        return str(vid), ""

    ff = shutil.which("ffmpeg")
    if not ff:
        return str(vid), "kept the picture without sound, ffmpeg is not installed"
    aud = out_dir / f"{sc}_audio.mp4"
    aud.write_bytes(best_a[1])
    merged = out_dir / f"{sc}_av.mp4"
    p = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(vid),
                        "-i", str(aud), "-c", "copy", "-shortest", str(merged)],
                       capture_output=True, timeout=180)
    if p.returncode == 0 and merged.exists() and merged.stat().st_size > 0:
        return str(merged), ""
    return str(vid), "kept the picture without sound, muxing failed"


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
    # Every mp4 the player fetches, in the order it asked for them. A reel's
    # <video> element carries a blob: url that nothing outside the page can
    # open, so the element is the wrong place to look. The network is the
    # right one: the real file goes past here on its way to the decoder.
    seen_mp4: list[str] = []

    def _watch(resp) -> None:
        try:
            if "video/mp4" in (resp.headers.get("content-type") or ""):
                if resp.url not in seen_mp4:
                    seen_mp4.append(resp.url)
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 1400},
                                      locale="en-US")
            page = ctx.new_page()
            page.on("response", _watch)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3500)
            _dismiss(page)

            data = page.evaluate(_CAROUSEL_JS)
            srcs: list[str] = data.get("slides", [])
            text: str = data.get("text", "")
            videos: list[str] = data.get("videos", [])

            # Metadata: OpenGraph first (reliable, login-free), then the same
            # tags off the open page, which is the only place they exist for
            # a reel, then the DOM shell.
            og = fetch_og(url)
            if not og.get("caption"):
                og = og_from_page(page) or og
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

            # A reel has no slides, so if there is a video it has to be played
            # before the network hands over anything worth keeping.
            if not srcs:
                try:
                    page.evaluate("() => { const v = document.querySelector('video');"
                                  " if (v) { v.muted = true; v.play(); } }")
                    page.wait_for_timeout(6000)
                except Exception as e:
                    res.notes.append(f"could not start the video: {type(e).__name__}")

            got, why = _save_video(ctx, videos, seen_mp4, out_dir, sc, timeout_ms)
            if got:
                res.video = got
                if why:
                    res.notes.append(why)
            elif why and not res.slides:
                # A carousel having no video is not a problem worth recording.
                res.notes.append(why)

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
        # Say which way it failed. "found no media" covered a blob url the
        # fetcher refuses, a fragment with no ftyp box, and a genuinely
        # empty page, and told them apart for nobody.
        res.error = ("could not get the media: " + "; ".join(res.notes)
                     if res.notes else
                     "browser loaded the page but found no media")
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
    return _og_fields(tags)


def og_from_page(page) -> dict:
    """The same tags, read out of the browser page that is already open.

    Instagram serves og: tags to a crawler UA for a /p/ post and serves none
    at all for a /reel/, so fetch_og comes back empty and the caption, the
    owner and the date go missing. The tags are sitting in the DOM either
    way, so read them from there rather than giving up on all three.
    """
    try:
        tags = page.evaluate(
            """() => Object.fromEntries(
                 [...document.querySelectorAll('meta[property^="og:"]')]
                   .map(m => [m.getAttribute('property').slice(3),
                              m.getAttribute('content') || '']))""")
    except Exception:
        return {}
    return _og_fields(tags or {})


def _og_fields(tags: dict) -> dict:
    """Pull the fields worth keeping out of a bag of og: tags."""
    out: dict = {}
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
            if not re.match(r"^(follow|•|\d[\d,.]*\s*(likes?|comments?))$",
                            cand, re.I) and len(cand) > len(caption):
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
    res.duration = int(info.get("duration") or 0)

    # Captions, if the video has them. A description alone makes for a thin
    # read, and auto-captions are free and instant next to transcribing.
    res.body_text = _yt_captions(info) or res.caption
    return res


def _yt_captions(info: dict) -> str:
    """Plain text from the best English caption track, or ''."""
    import urllib.request

    tracks = {}
    for bucket in ("subtitles", "automatic_captions"):
        for lang, entries in (info.get(bucket) or {}).items():
            if lang.startswith("en"):
                tracks.setdefault(lang, entries)
    if not tracks:
        return ""
    lang = next((l for l in ("en", "en-US", "en-orig") if l in tracks), sorted(tracks)[0])
    url = ""
    for want in ("vtt", "srv1", "json3"):
        for e in tracks[lang]:
            if e.get("ext") == want and e.get("url"):
                url = e["url"]
                break
        if url:
            break
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read().decode("utf-8", "replace")
    except Exception:
        return ""

    if raw.lstrip().startswith("{"):
        try:
            data = json.loads(raw)
            words = [s.get("utf8", "") for ev in data.get("events", [])
                     for s in (ev.get("segs") or [])]
            return " ".join("".join(words).split())[:40000]
        except Exception:
            return ""
    # VTT: drop timing lines and the rolling duplicates auto-captions emit
    out, prev = [], None
    for line in raw.splitlines():
        line = line.strip()
        if (not line or line == "WEBVTT" or line.isdigit()
                or "-->" in line or line.startswith(("Kind:", "Language:"))):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line != prev:
            out.append(line)
            prev = line
    return " ".join(out)[:40000]


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
