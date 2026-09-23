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

# Task -> ordered ladder of (provider, model). First healthy one wins.
LADDERS: dict[str, list[tuple[str, str]]] = {
    # Default read: fast, generous free tier, good enough for most items.
    "extract": [
        ("gemini", "gemini-3.5-flash-lite"),
        ("gemini", "gemini-3.1-flash-lite"),
        ("ollama_cloud", "qwen3-vl:235b-cloud"),
        ("ollama", "qwen3-vl-nothink:latest"),
        ("ollama", "qwen3-vl:4b"),
    ],
    # Deep read. Escalated to automatically when an item is marked urgent,
    # is a job application, or when the first pass produced links that all
    # fail to resolve (a strong signal the read was incomplete).
    "extract_deep": [
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.5-flash"),
        ("ollama_cloud", "qwen3-vl:235b-cloud"),
        ("gemini", "gemini-3.5-flash-lite"),
    ],
    # Cheap structured text work: tagging, normalising, dedupe decisions.
    "classify": [
        ("gemini", "gemini-3.5-flash-lite"),
        ("ollama", "qwen3:4b-instruct-2507-q4_K_M"),
        ("ollama", "llama3.2:3b"),
    ],
    # Research that needs live web grounding.
    "research": [
        ("gemini_grounded", "gemini-3.5-flash-lite"),
        ("gemini_grounded", "gemini-3.1-flash-lite"),
        ("ollama_cloud", "gpt-oss:120b-cloud"),
    ],
    # Hard reasoning / judgement calls.
    "reason": [
        ("gemini", "gemini-3.8-flash"),
        ("ollama_cloud", "kimi-k2.5:cloud"),
        ("ollama_cloud", "gpt-oss:120b-cloud"),
        ("ollama", "qwen3:4b-instruct-2507-q4_K_M"),
    ],
}

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

if POLICY == "local_only":
    LADDERS = {
        k: [step for step in v if step[0] == "ollama"] or [("ollama", "qwen3:4b-instruct-2507-q4_K_M")]
        for k, v in LADDERS.items()
    }
elif POLICY == "quality_first":
    LADDERS["extract"].insert(0, ("gemini", "gemini-3.8-flash"))
    LADDERS["classify"].insert(0, ("gemini", "gemini-3.8-flash"))

# Per 1M tokens. Only used for the cost meter.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}

# Daily free-tier budget. Deliberately low so we drop a rung before a 429.
FREE_TIER_RPD: dict[str, int] = {
    "gemini-3.5-flash-lite": 450,
    "gemini-3.1-flash-lite": 450,
    "gemini-3.8-flash": 18,
    "gemini-3.5-flash": 18,
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
