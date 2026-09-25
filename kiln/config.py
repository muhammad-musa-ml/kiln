"""Kiln configuration.

Single source of truth for paths, model routing policy and feature flags.
Everything is overridable by environment variable so nothing is hardcoded
into the pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("KILN_DATA", ROOT / "data"))
MEDIA = DATA / "media"
CACHE = DATA / "cache"
LOGS = DATA / "logs"
DB_PATH = Path(os.environ.get("KILN_DB", DATA / "kiln.db"))
WEB = ROOT / "web"

for _d in (DATA, MEDIA, CACHE, LOGS):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST = os.environ.get("KILN_HOST", "127.0.0.1")
PORT = int(os.environ.get("KILN_PORT", "7878"))

# Local mode gates anything touching a secret, a browser or a shell.
IS_LOCAL = os.environ.get("KILN_LOCAL", "1") == "1"


def _local_token() -> str:
    """Bearer token for write routes. Loopback alone isn't auth."""
    import secrets as _secrets

    p = DATA / "local_token.txt"
    try:
        tok = p.read_text(encoding="utf-8").strip()
        if len(tok) >= 32:
            return tok
    except Exception:
        pass
    tok = _secrets.token_urlsafe(32)
    try:
        p.write_text(tok, encoding="utf-8")
    except Exception:
        pass
    return tok


LOCAL_TOKEN = _local_token()

# ---------------------------------------------------------------------------
# Model providers
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

def _find_ollama() -> str:
    """Pick whichever Ollama port actually has models loaded."""
    import json as _json
    import urllib.request as _u

    explicit = os.environ.get("KILN_OLLAMA_HOST")
    candidates = [explicit] if explicit else []
    candidates += ["http://127.0.0.1:11434", "http://127.0.0.1:11435"]
    best, best_n = candidates[-1], -1
    for host in candidates:
        if not host:
            continue
        try:
            with _u.urlopen(host + "/api/tags", timeout=3) as r:
                n = len(_json.loads(r.read().decode()).get("models", []))
            if n > best_n:
                best, best_n = host, n
            if explicit and host == explicit:
                return host
        except Exception:
            continue
    return best


OLLAMA_HOST = _find_ollama()
OLLAMA_MODELS_DIR = os.environ.get(
    "KILN_OLLAMA_MODELS", str(Path.home() / ".ollama" / "models")
)

# ---------------------------------------------------------------------------
# Routing policy
# ---------------------------------------------------------------------------
# Cloud first, local as the always-available fallback. Local VLMs can't read
# video at all and run much slower, so they're a backstop, not the default.
POLICY = os.environ.get("KILN_POLICY", "free_first")  # free_first | local_only | quality_first

# Task -> ordered ladder of (provider, model). Best first, and every rung
# has to be good enough to do the job properly.
#
# This used to start at the cheapest rung and only climb when something
# tripped a trigger. The result was that the best model never ran once: 13
# items, 0 escalations, and every thin entry came off a "lite" model. A
# fallback that produces a worse answer is not a fallback, it is a quiet
# downgrade, so the weak rungs are gone rather than demoted. Running out of
# models is an acceptable outcome. Claude picks those up (see MIN_STANDARD).
LADDERS: dict[str, list[tuple[str, str]]] = {
    # Reading a post: slides, video, on-screen text. Vision work, best first.
    "extract": [
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.7-flash"),
        ("gemini", "gemini-3.6-flash"),
        ("gemini", "gemini-3.5-flash"),
    ],
    # The same, with room to think. Used when an instruction is attached, the
    # item is urgent, or the first pass came back thin.
    "extract_deep": [
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.1-pro-preview"),
        ("gemini", "gemini-3.7-flash"),
        ("gemini", "gemini-3.6-flash"),
    ],
    # Structured text work: tagging, normalising, dedupe decisions.
    "classify": [
        ("gemini", "gemini-3.5-flash"),
        ("gemini", "gemini-3.6-flash"),
        ("gemini", "gemini-3.7-flash"),
    ],
    # Research that needs live web grounding.
    "research": [
        ("gemini_grounded", "gemini-3.8-flash"),
        ("gemini_grounded", "gemini-3.7-flash"),
        ("gemini_grounded", "gemini-3.5-flash"),
    ],
    # Hard reasoning and judgement calls.
    "reason": [
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.1-pro-preview"),
        ("gemini", "gemini-3.7-flash"),
        ("gemini", "gemini-3.6-flash"),
    ],
}

# What every rung has to manage before it is allowed in a ladder above.
# Written down so the reason a model was dropped is on the record rather
# than in somebody's memory.
MIN_STANDARD = """A model belongs in a ladder only if it can:
  - read a carousel of 10 or more slides and return one section per slide
  - transcribe on-screen text verbatim rather than describing it
  - return the links that appear in an image
  - follow an instruction attached to the item, not just summarise the item
  - answer in valid JSON matching a given schema
Dropped for failing this, with the evidence:
  ollama:qwen3-vl-nothink   returned 0 sections, 0 on-screen text and 0 links
                            on an 11 slide carousel (2026-09-24)
  ollama:qwen3-vl:4b        smaller sibling of the above
  ollama_cloud:qwen3-vl:235b-cloud   retired upstream, answers HTTP 410
  gemini *-flash-lite       every thin entry in the 2026-09-24 run came off
                            a lite rung
  ollama:qwen3:4b, llama3.2:3b, kimi-k2.5, gpt-oss:120b
                            text-only, never measured against the standard
When no rung is left, the item is handed to Claude rather than filed thin."""

# Thinking budget per task. Off for extraction - it reasons instead of
# transcribing and you get less text for more money.
THINKING_BUDGET: dict[str, int] = {
    "extract": 0,
    "extract_deep": 0,
    "classify": 0,
    "research": 1024,
    "reason": 4096,
}

# Any of these bumps extract -> extract_deep. Data so the UI can show why.
ESCALATE_WHEN = {
    "urgent": "you marked it urgent",
    "job": "job applications are high-stakes",
    "all_links_dead": "every link from the first pass failed to resolve",
    "empty_extraction": "the first pass found almost nothing",
    "user_requested": "you asked for a deeper look",
}

# These get a second pass, merged with the first. Reads vary run to run.
DOUBLE_PASS_KINDS = {"job", "tool", "repo"}

# "local_only" used to strip every ladder down to the ollama rungs. Those
# rungs are gone, because none of them cleared MIN_STANDARD, so the policy
# would leave every ladder empty and every item unread. It is refused rather
# than silently producing that.
if POLICY == "local_only":
    raise SystemExit(
        "KILN_POLICY=local_only is no longer supported: no local model "
        "cleared the minimum standard, so there is nothing to fall back to. "
        "Unset it, or see MIN_STANDARD in kiln/config.py.")

# Daily free-tier budget. Deliberately low so we drop a rung before a 429.
# Only models that are actually in a ladder belong here.
FREE_TIER_RPD: dict[str, int] = {
    "gemini-3.8-flash": 18,
    "gemini-3.7-flash": 18,
    "gemini-3.6-flash": 18,
    "gemini-3.5-flash": 18,
    "gemini-3.1-pro-preview": 18,
}

# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------
KEEP_MEDIA = os.environ.get("KILN_KEEP_MEDIA", "1") == "1"
IG_USERNAME = os.environ.get("KILN_IG_USERNAME", "")
MAX_VIDEO_SECONDS = int(os.environ.get("KILN_MAX_VIDEO_SECONDS", "600"))

# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
# Google Doc inbox. Kiln only ever READS this - it never edits the doc, and
# tracks what it has already seen by content hash.
GDOC_INBOX_ID = os.environ.get("KILN_GDOC_INBOX_ID", "")
INBOX_DIR = Path(os.environ.get("KILN_INBOX_DIR", DATA / "inbox"))
INBOX_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
# One-click run with a preview: Kiln shows the exact command and what it
# touches, then runs it only on an explicit click. Commands whose base
# binary is not on this list are shown but never made runnable.
RUNNABLE_BINARIES = {
    "pip", "pip3", "python", "py", "uv", "uvx",
    "npm", "npx", "pnpm", "yarn", "bun",
    "winget", "choco", "scoop",
    "ollama", "git", "docker",
    "cargo", "go", "brew", "apt",
}

# Patterns that can never be one-click, even if the binary is allowed.
FORBIDDEN_PATTERNS = [
    "curl", "wget", "iwr", "invoke-webrequest",  # pipe-to-shell
    "rm -rf", "del /", "format ", "mkfs",
    "sudo", "runas", "reg add", "reg delete",
    "shutdown", "diskpart", ">", "|",
]
