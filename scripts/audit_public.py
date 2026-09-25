"""Refuse to publish anything that leaks.

Greps the build for things that shouldn't be there and checks the exported
keys against the whitelist. Exits non-zero so the deploy script can stop.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import publish  # noqa: E402

OUT = ROOT / "public"

# Things that must never appear in any published byte.
FORBIDDEN_STRINGS = [
    "user_note", "user_do", "cost_usd", "media_dir", "pdf_path",
    "local_token", "secrets.json", "KILN_TOKEN=",
    "enrich_json", "note_json", "processed_at",
    "claude_json", "claude_state", "claude_attempts", "run_dir",
]
FORBIDDEN_PATTERNS = [
    (r"AIza[0-9A-Za-z_\-]{20,}", "Google API key"),
    (r"\bsk-[0-9A-Za-z_\-]{20,}", "OpenAI-style key"),
    (r"sb_secret_[0-9A-Za-z_\-]+", "Supabase secret key"),
    (r"gsk_[0-9A-Za-z]{20,}", "Groq key"),
    (r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9_.\-]+", "Windows user path"),
    (r"/(?:home|Users)/[A-Za-z0-9_.\-]+/", "POSIX home path"),
]

VENDOR_WORDS = re.compile(
    r"\b(gemini|ollama|claude|anthropic|openai|codex|opus|sonnet|haiku|gpt)\b", re.I)

failures: list[str] = []
checks = 0


def _words(text) -> list[str]:
    """Lowercase words with tags and punctuation gone, so a quote survives reflow."""
    t = re.sub(r"<[^>]+>", " ", str(text or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", t).split()


def _grams(words: list[str], n: int = 8) -> set[str]:
    # A text shorter than n words is its own run, if it is long enough to
    # mean anything on its own.
    if len(words) < n:
        return {" ".join(words)} if len(words) >= 5 else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def main() -> int:
    global checks
    if not OUT.exists():
        print("public/ not built. Run: python -m kiln.publish")
        return 2

    files = [p for p in OUT.rglob("*") if p.is_file()]
    text_files = [p for p in files
                  if p.suffix.lower() in (".json", ".html", ".js", ".css", ".txt", ".md",
                                          ".csv")]
    print(f"auditing {len(files)} files ({len(text_files)} text) in {OUT}\n")

    # 1. Private field NAMES, checked in DATA files only.
    #    index.html legitimately references field names in code paths that
    #    simply never fire when the field is absent - flagging those was a
    #    check that could not discriminate a leak from a variable name.
    #    What matters in code is VALUES, and check 2 and 3 cover those.
    data_files = [p for p in text_files if p.suffix == ".json"]
    for needle in FORBIDDEN_STRINGS:
        checks += 1
        hits = [p.name for p in data_files
                if needle in p.read_text(encoding="utf-8", errors="replace")]
        if hits:
            fail(f"private field '{needle}' present in exported data: {hits[:3]}")
    if not failures:
        ok(f"none of {len(FORBIDDEN_STRINGS)} private field names in exported data")

    # 2. key / path shapes
    for pat, label in FORBIDDEN_PATTERNS:
        checks += 1
        rx = re.compile(pat)
        for p in text_files:
            m = rx.search(p.read_text(encoding="utf-8", errors="replace"))
            if m:
                fail(f"{label} found in {p.name}: {m.group(0)[:28]}...")
                break
        else:
            ok(f"no {label}")

    # 3. live env keys must not appear anywhere
    checks += 1
    live = [v for k, v in os.environ.items()
            if ("KEY" in k.upper() or "TOKEN" in k.upper()) and len(v) >= 16]
    leaked = []
    for p in files:
        blob = p.read_bytes()
        for v in live:
            if v.encode() in blob:
                leaked.append((p.name, v[:6]))
    if leaked:
        fail(f"live credential present in output: {leaked[:2]}")
    else:
        ok(f"none of {len(live)} live credentials in environment appear in output")

    # 4. exported item keys match the whitelist exactly
    checks += 1
    data = json.loads((OUT / "data" / "items.json").read_text(encoding="utf-8"))
    allowed = set(publish.ITEM_FIELDS) | {
        "note", "enrich", "tags", "links", "gate",
        "media_id", "pdf_file", "slide_ext", "build_prompt", "followup"}
    extra: set[str] = set()
    for it in data.get("items", []):
        extra |= set(it.keys()) - allowed
    if extra:
        fail(f"item keys outside the whitelist: {sorted(extra)}")
    else:
        ok(f"all item keys within the whitelist ({len(data.get('items', []))} items)")

    # 5. nested note/enrich/followup keys are whitelisted too
    checks += 1
    n_allowed, e_allowed = set(publish.NOTE_FIELDS), set(publish.ENRICH_FIELDS)
    f_allowed, a_allowed = set(publish.FOLLOWUP_FIELDS), set(publish.ARTIFACT_FIELDS)
    g_allowed = set(publish.GATE_FIELDS)
    bad: set[str] = set()
    for it in data.get("items", []):
        bad |= set((it.get("note") or {}).keys()) - n_allowed
        bad |= set((it.get("enrich") or {}).keys()) - e_allowed
        bad |= set((it.get("gate") or {}).keys()) - g_allowed
        fu = it.get("followup") or {}
        bad |= set(fu.keys()) - f_allowed
        for a in fu.get("artifacts") or []:
            bad |= set(a.keys()) - a_allowed
    if bad:
        fail(f"nested keys outside the whitelist: {sorted(bad)}")
    else:
        ok("nested note/enrich/gate/followup keys within the whitelist")

    # 5a. a private field added to a whitelist by mistake would pass 4 and 5
    checks += 1
    lists = allowed | n_allowed | e_allowed | f_allowed | a_allowed | g_allowed
    let_in = sorted(set(publish.NEVER) & lists)
    if let_in:
        fail(f"a whitelist admits private fields: {let_in}")
    else:
        ok(f"no whitelist admits any of the {len(publish.NEVER)} private fields")

    # 5b. the text inside every published PDF. A PDF compresses its text, so
    #     the byte scan above cannot see into one; a document Claude wrote is
    #     text I did not read before it went out, so it gets read here.
    checks += 1
    from kiln import artifacts
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    pdf_texts = {p: artifacts.pdf_text(p) for p in pdfs}
    hit = ""
    for p, text in pdf_texts.items():
        for pat, label in FORBIDDEN_PATTERNS:
            if re.search(pat, text):
                hit = f"{label} inside {p.relative_to(OUT)}"
                break
        if hit:
            break
    if hit:
        fail(hit)
    else:
        ok(f"read the text of {len(pdfs)} PDF(s), "
           f"{sum(1 for t in pdf_texts.values() if t.strip())} with text; no keys or paths")

    # 5c. what I wrote next to a link never goes out, not even quoted back.
    #     The fields are never exported (check 1), but an answer written from
    #     an instruction could repeat it. Compared as runs of eight words over
    #     the text a reader would see: JSON is parsed first, because in the
    #     raw file a quote inside the instruction is stored as \" and a
    #     straight text search walks right past it.
    #     A note of five to seven words is looked for whole, as a run of
    #     words; as a single short run it could never equal an eight-word
    #     one. Under five words is not checked, because that few words turn
    #     up in ordinary text.
    checks += 1
    from kiln import store
    conn = store.connect()
    asks: set[str] = set()
    short: set[str] = set()
    for r in conn.execute("SELECT user_do, user_note FROM items"):
        for t in (r["user_do"], r["user_note"]):
            w = _words(t)
            if len(w) >= 8:
                asks |= _grams(w)
            elif len(w) >= 5:
                short.add(" ".join(w))
    conn.close()
    shown: set[str] = set()
    streams: list[str] = []
    for p in text_files:
        raw = p.read_text(encoding="utf-8", errors="replace")
        if p.suffix == ".json":
            try:
                raw = " ".join(_strings(json.loads(raw)))
            except ValueError:
                pass
        words = _words(raw)
        shown |= _grams(words)
        streams.append(" %s " % " ".join(words))
    for text in pdf_texts.values():
        words = _words(text)
        shown |= _grams(words)
        streams.append(" %s " % " ".join(words))
    leaked_ask = sorted(asks & shown) + sorted(
        s for s in short if any(" %s " % s in st for st in streams))
    if leaked_ask:
        fail(f"{len(leaked_ask)} run(s) of words from a private instruction "
             f"appear in the build, e.g. '{leaked_ask[0]}'")
    else:
        ok(f"none of {len(asks)} eight-word runs and {len(short)} short notes "
           f"from my instructions appear in the build")

    # 5d. the only page on the site is the site. Any other HTML file, like a
    #     document a model wrote, would run its scripts on the site's origin.
    checks += 1
    pages = [p.relative_to(OUT).as_posix() for p in files
             if p.suffix.lower() in (".html", ".htm", ".svg", ".xhtml")
             and p != OUT / "index.html"]
    if pages:
        fail(f"{len(pages)} page(s) besides index.html in the build: {pages[:3]}")
    else:
        ok("index.html is the only page in the build")

    # 6. every built file is actually committable.
    #    A broad ignore rule (data/ matches at any depth) silently dropped
    #    public/data once, which ships a site with no content at all.
    checks += 1
    import subprocess
    ignored = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        r = subprocess.run(["git", "check-ignore", rel], cwd=ROOT,
                           capture_output=True, text=True)
        if r.returncode == 0:
            ignored.append(rel)
    if ignored:
        fail(f"git ignores {len(ignored)} built file(s), the deploy would be "
             f"incomplete: {ignored[:3]}")
    else:
        ok(f"all {len(files)} built files are committable")

    # 7. the site has content
    checks += 1
    need = [OUT / "index.html", OUT / "data" / "items.json", OUT / "data" / "facets.json"]
    missing = [p.name for p in need if not p.exists()]
    if missing:
        fail(f"build is missing {missing}")
    else:
        ok("index.html, items.json and facets.json all present")

    # 8. no write surface shipped
    checks += 1
    html = (OUT / "index.html").read_text(encoding="utf-8", errors="replace")
    if "window.KILN_STATIC=true" not in html.replace(" ", ""):
        fail("index.html is not marked static - it may try to call a server")
    else:
        ok("index.html is in static read-only mode")

    # 9. the published page is the local page, byte for byte.
    #    public/index.html has been hand edited before. That is how the site
    #    and the app end up describing the same button two different ways,
    #    and nothing catches it, because both files look fine on their own.
    checks += 1
    local_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8",
                                                         errors="replace")
    stripped = re.sub(
        r'<script>window\.KILN_STATIC=true;window\.KILN_BUILT="[^"]*";</script>',
        "", html, count=1)
    if stripped != local_html:
        fail("public/index.html is not a copy of web/index.html. Rebuild with "
             "python -m kiln.publish rather than editing the published copy")
    else:
        ok("published page matches the local page exactly")

    # 10. the page itself names no AI vendor or model. The items may: a post
    #     can be about one. The page is the owner's, and says "the follow-up".
    checks += 1
    named = sorted(set(m.lower() for m in VENDOR_WORDS.findall(html)))
    if named:
        fail(f"the published page names {named}; it should name no vendor")
    else:
        ok("the published page names no AI vendor or model")

    print()
    if failures:
        print(f"AUDIT FAILED - {len(failures)} finding(s) across {checks} checks.")
        print("Do not deploy.")
        return 1
    print(f"AUDIT PASSED - {checks} checks, no findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
