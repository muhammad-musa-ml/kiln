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
]
FORBIDDEN_PATTERNS = [
    (r"AIza[0-9A-Za-z_\-]{20,}", "Google API key"),
    (r"\bsk-[0-9A-Za-z_\-]{20,}", "OpenAI-style key"),
    (r"sb_secret_[0-9A-Za-z_\-]+", "Supabase secret key"),
    (r"gsk_[0-9A-Za-z]{20,}", "Groq key"),
    (r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9_.\-]+", "Windows user path"),
    (r"/(?:home|Users)/[A-Za-z0-9_.\-]+/", "POSIX home path"),
]

failures: list[str] = []
checks = 0


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
                  if p.suffix.lower() in (".json", ".html", ".js", ".css", ".txt", ".md")]
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
        "media_id", "pdf_file", "slide_ext"}
    extra: set[str] = set()
    for it in data.get("items", []):
        extra |= set(it.keys()) - allowed
    if extra:
        fail(f"item keys outside the whitelist: {sorted(extra)}")
    else:
        ok(f"all item keys within the whitelist ({len(data.get('items', []))} items)")

    # 5. nested note/enrich keys are whitelisted too
    checks += 1
    n_allowed, e_allowed = set(publish.NOTE_FIELDS), set(publish.ENRICH_FIELDS)
    bad: set[str] = set()
    for it in data.get("items", []):
        bad |= set((it.get("note") or {}).keys()) - n_allowed
        bad |= set((it.get("enrich") or {}).keys()) - e_allowed
    if bad:
        fail(f"nested keys outside the whitelist: {sorted(bad)}")
    else:
        ok("nested note/enrich keys within the whitelist")

    # 6. no write surface shipped
    checks += 1
    html = (OUT / "index.html").read_text(encoding="utf-8", errors="replace")
    if "window.KILN_STATIC=true" not in html.replace(" ", ""):
        fail("index.html is not marked static - it may try to call a server")
    else:
        ok("index.html is in static read-only mode")

    print()
    if failures:
        print(f"AUDIT FAILED - {len(failures)} finding(s) across {checks} checks.")
        print("Do not deploy.")
        return 1
    print(f"AUDIT PASSED - {checks} checks, no findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
