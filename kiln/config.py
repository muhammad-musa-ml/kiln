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

# LOCAL MODE. Everything that touches a secret, a browser or a shell is gated
# on this. The published site is a static export and never runs this server,
# so these capabilities simply do not exist in production - they are not
# "disabled by a flag an attacker might flip", they are absent from the build.
IS_LOCAL = os.environ.get("KILN_LOCAL", "1") == "1"


def _local_token() -> str:
    """A per-install bearer token for write routes.

    The server binds to 127.0.0.1, but loopback is not an authorisation
    boundary: any process on this machine, and any page in the browser via a
    stray fetch, can reach it. Writes therefore carry a token that only the
    locally-served page is given.
    """
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

# Ollama. NOTE: a stray OLLAMA_MODELS pointing at another project makes the
# server report zero models even with blobs on disk - so Kiln pins it.
def _find_ollama() -> str:
    """Auto-detect the Ollama port.

    A stray OLLAMA_MODELS env var (pointing at another project) makes the
    default-port server report zero models, so a second server on 11435 is
    a common local workaround. Kiln prefers whichever port actually serves
    models rather than assuming 11434.
    """
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
# Measured 2026-09-23 on an RTX 4050 (6 GB VRAM) against 11 identical images:
#   gemini-3.5-flash-lite : 26.7 s total, 3/3 on-screen links, clean JSON
#   qwen3-vl:4b (local)   : ~5-7 s PER IMAGE, 2/3 links, 1-in-11 runaway loop
# Gemini is ~11x faster, natively reads VIDEO (local VLMs cannot), and its
# free tier covers hundreds of items/day. So: free tier first, local as the
# always-available fallback that costs nothing and leaks nothing.
POLICY = os.environ.get("KILN_POLICY", "free_first")  # free_first | local_only | quality_first

# Head-to-head on the same 11 images, 2026-09-23 (3 real on-screen links,
# one of them live):
#   flash-lite            6.6s  $0.0064  51 lines  2/3 links  missed the live one
#   flash-lite +thinking 10.7s  $0.0104  18 lines  2/3 links  missed the live one
#   gemini-3.8-flash     36.7s  $0.0210 114 lines  2/3 links  FOUND the live one
#   gemini-3.1-pro         --     --      --        --        HTTP 429 immediately
#
# Three conclusions, all encoded below:
#  1. THINKING HURTS EXTRACTION. It spends budget reasoning instead of
#     transcribing - a third of the text for 63% more money. Thinking is
#     enabled only on the `reason` ladder, never on `extract`.
#  2. PRO IS NOT VIABLE FREE. Its free tier 429s on the first call, and
#     extraction is an OCR/transcription job, not a reasoning job.
#  3. EXTRACTION IS NON-DETERMINISTIC. flash-lite returned 3/3 links and 91
#     lines on one run and 2/3 links and 51 lines on the next, same input.
#     So high-value items get a second pass and the results are UNIONed
#     (see extract.py::extract_item) rather than trusting a single read.

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

# Thinking budget per task. 0 disables it. Measured: thinking costs a third
# of the transcript on extraction, and earns its keep only on judgement.
THINKING_BUDGET: dict[str, int] = {
    "extract": 0,
    "extract_deep": 0,
    "classify": 0,
    "research": 1024,
    "reason": 4096,
}

# When to spend the expensive read. Any one of these escalates extract ->
# extract_deep. Kept as data so the UI can show WHY an item was escalated.
ESCALATE_WHEN = {
    "urgent": "you marked it urgent",
    "job": "job applications are high-stakes",
    "all_links_dead": "every link from the first pass failed to resolve",
    "empty_extraction": "the first pass found almost nothing",
    "user_requested": "you asked for a deeper look",
}

# Items matching these get a second independent pass whose results are
# UNIONed with the first, to beat the measured run-to-run variance.
DOUBLE_PASS_KINDS = {"job", "tool", "repo"}

if POLICY == "local_only":
    LADDERS = {
        k: [step for step in v if step[0] == "ollama"] or [("ollama", "qwen3:4b-instruct-2507-q4_K_M")]
        for k, v in LADDERS.items()
    }
elif POLICY == "quality_first":
    LADDERS["extract"].insert(0, ("gemini", "gemini-3.8-flash"))
    LADDERS["classify"].insert(0, ("gemini", "gemini-3.8-flash"))

# Prices per 1M tokens, read from ai.google.dev/gemini-api/docs/pricing 2026-09-23.
# Used only for the running cost meter shown in the UI.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}

# Free-tier daily request budget per model. Conservative: sources disagree
# (500 vs 1000 RPD for flash-lite), so Kiln uses the low number and falls
# through to the next rung rather than eating a 429.
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
