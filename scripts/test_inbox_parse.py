"""Check the inbox parser against the real doc text."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kiln import ingest  # noqa: E402

REAL = (
    "# **links**\n\n"
    "  - **https://www.instagram.com/p/DdZQsecgKqv/?img\\_index=7\\&stkn=ZHkweDQyYWJwNXg=**  \n"
    "    2026-09-23\n"
    "  - **https://www.instagram.com/p/DddmSMCCKbq/?stkn=eXRhNnBsZ2Z0bWUw**  \n"
    "    2026-09-23\n"
    "  - **https://www.instagram.com/p/Dc6SBfvxRux/?stkn=aTRueHF0NGEzeXZw**  \n"
    "    2026-09-23 — There are links inside the image for each of these videos."
    " See if you can extract them.\n"
    "  - **https://www.youtube.com/watch?v=o126p1QN\\_RI,"
    " https://www.youtube.com/watch?v=LPZh9BOjkQs,"
    " https://www.youtube.com/watch?v=T9aRN5JkmL8,"
    " https://www.youtube.com/watch?v=viZrOnJclY0,"
    " https://www.freecodecamp.org/news/ai-agents-for-beginners/,"
    " https://www.youtube.com/watch?v=CcrC5zSv1iA,"
    " https://www.youtube.com/watch?v=gh2\\_PhgZGsM** — 2026-09-23 — make a new"
    " section called to watch with subsections for types of videos. Each type might"
    " get more videos added. Put these videos in the right types. The types can be"
    " anywhere from 1 for all to 7 for each"
)

if __name__ == "__main__":
    got = ingest.parse_doc(REAL)
    print("items parsed:", len(got))
    print()
    urls = []
    for i, p in enumerate(got, 1):
        u = p.get("url") or p.get("urls")
        print("%d. url(s): %s" % (i, u))
        if p.get("note"):
            print("   note: %s" % p["note"][:110])
        if p.get("do"):
            print("   do  : %s" % p["do"][:110])
        if p.get("saved_on"):
            print("   date: %s" % p["saved_on"])
        for k in ("url", "urls"):
            v = p.get(k)
            if isinstance(v, list):
                urls += v
            elif v:
                urls.append(v)
        print()
    print("TOTAL URLS RECOVERED:", len(urls))
    print("EXPECTED             : 10  (3 instagram + 6 youtube + 1 article)")
    missing = [u for u in ("o126p1QN_RI", "LPZh9BOjkQs", "T9aRN5JkmL8", "viZrOnJclY0",
                           "freecodecamp", "CcrC5zSv1iA", "gh2_PhgZGsM")
               if not any(u in x for x in urls)]
    print("MISSING              :", missing or "none")
    bad = [u for u in urls if "\\" in u]
    print("STILL ESCAPED        :", bad or "none")
