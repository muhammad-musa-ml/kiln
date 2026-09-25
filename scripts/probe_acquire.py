"""Probe the routes to a public Instagram carousel, with a saved session if one exists.

Run:  python scripts/probe_acquire.py <url>
"""
import json, re, sys, pathlib, urllib.request, html

UA_BOT = "facebookexternalhit/1.1"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def fetch(url, ua):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def og_tags(doc):
    out = {}
    for m in re.finditer(r'<meta property="og:([a-z_:]+)" content="(.*?)"\s*/?>', doc):
        out[m.group(1)] = html.unescape(m.group(2))
    return out


def mine_images(doc):
    """Every distinct CDN media URL in the page, in document order."""
    seen, urls = set(), []
    pat = re.compile(r'https://[a-z0-9\-]*\.?(?:cdninstagram\.com|fbcdn\.net)/[^"\\\s<>]+')
    for m in pat.finditer(doc):
        u = html.unescape(m.group(0)).replace("\\u0026", "&").replace("\\/", "/")
        if not re.search(r"\.(jpg|jpeg|webp|png|mp4)", u):
            continue
        key = re.sub(r"[?&](oh|oe|_nc_gid|_nc_ohc)=[^&]*", "", u)
        key = key.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        urls.append(u)
    return urls


def try_instaloader(shortcode):
    try:
        import instaloader
    except ImportError:
        return "instaloader not installed"
    sess = pathlib.Path.home() / "AppData/Local/Instaloader/session-muhammedmw"
    L = instaloader.Instaloader(quiet=True, download_comments=False)
    used = "anonymous"
    if sess.exists():
        try:
            L.load_session_from_file("muhammedmw", str(sess))
            used = "session-muhammedmw"
        except Exception as e:
            return f"session load failed: {type(e).__name__}: {str(e)[:120]}"
    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        n = post.mediacount if post.typename == "GraphSidecar" else 1
        return {
            "auth": used,
            "owner": post.owner_username,
            "date": str(post.date_utc),
            "typename": post.typename,
            "slides": n,
            "comments": post.comments,
            "likes": post.likes,
            "caption_head": " ".join((post.caption or "").split())[:160],
        }
    except Exception as e:
        return f"{used}: {type(e).__name__}: {str(e)[:200]}"


if __name__ == "__main__":
    url = sys.argv[1]
    sc = re.search(r"instagram\.com/(?:reel|p|tv)/([A-Za-z0-9_-]+)", url).group(1)
    print("shortcode:", sc)

    print("\n--- A) instaloader (saved session) ---")
    print(json.dumps(try_instaloader(sc), indent=2) if isinstance(try_instaloader.__call__, object) else "")
    r = try_instaloader(sc)
    print(json.dumps(r, indent=2) if isinstance(r, dict) else r)

    for name, ua in (("bot UA", UA_BOT), ("browser UA", UA_BROWSER)):
        print(f"\n--- B) raw HTML via {name} ---")
        try:
            doc = fetch(url, ua)
        except Exception as e:
            print("  fetch failed:", e); continue
        og = og_tags(doc)
        print("  bytes:", len(doc))
        for k in ("title", "description", "url"):
            if og.get(k):
                print(f"  og:{k}: {og[k][:150]}")
        imgs = mine_images(doc)
        print("  distinct media URLs found:", len(imgs))
        for u in imgs[:12]:
            print("    ", u.split("?")[0][-70:])
