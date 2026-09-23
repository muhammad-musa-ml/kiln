"""Catch writing that reads like a machine wrote it.

This is a gate, not a judge. It can tell you something is wrong. It can
never tell you the text sounds like you, because only you can say that.
Treat a clean run as "nothing obvious left", not as approval.

Characters are built with chr() so this file stays plain ASCII. Writing
them as escapes does not survive every editor, and a needle file full of
the very characters it bans is a trap.

    python -m kiln.slop <path>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED_CHARS = {
    chr(0x2014): "em dash",
    chr(0x2013): "en dash",
    chr(0x2192): "arrow",
    chr(0x2190): "arrow",
    chr(0x21D2): "arrow",
    chr(0x00B7): "middot",
    chr(0x2022): "bullet character",
    chr(0x25AA): "bullet character",
    chr(0x25CF): "bullet character",
    chr(0x2018): "curly quote",
    chr(0x2019): "curly quote",
    chr(0x201C): "curly quote",
    chr(0x201D): "curly quote",
    chr(0x2026): "ellipsis character",
    chr(0x00A0): "non breaking space",
    chr(0x2713): "check mark",
    chr(0x2717): "cross mark",
    chr(0x2705): "check mark",
}

# Words and phrases that read as marketing or as a model padding a sentence.
BANNED_PHRASES = [
    "seamless", "seamlessly", "elevate", "unlock", "leverage", "dive into",
    "deep dive", "delve", "a testament to", "in the realm of",
    "it is important to note", "worth noting that",
    "furthermore", "moreover", "cutting edge", "cutting-edge",
    "state of the art", "state-of-the-art", "game changer", "game-changer",
    "best in class", "best-in-class", "empower", "streamline", "plethora",
    "myriad", "revolutionize", "harness the", "boasts", "in today's",
    "ever-evolving", "at its core", "robust and scalable", "first-class",
    "battle-tested", "rock-solid", "supercharge", "effortlessly",
    "in conclusion", "let's explore", "we'll explore", "whether you're",
    "look no further", "the world of",
]

# Sentence shapes a model reaches for far more often than a person does.
BANNED_PATTERNS = [
    (r"\bnot (just|only) [^.,;]{1,60}[,]? but\b", "not just X but Y construction"),
    (r"\bit'?s not [^.,;]{1,40}[,]? it'?s\b", "it is not X, it is Y construction"),
    (r"\bmore than just\b", "more than just construction"),
]

# Crediting the tools that produced the work. This is the hard ban.
ATTRIBUTION = [
    (r"co-authored-by", "co-author trailer"),
    (r"\b(generated|created|written|built|made)\s+(with|by|using)\s+"
     r"(claude|codex|chatgpt|gpt|copilot|an?\s+ai|ai\b)", "tool attribution"),
    (r"\b(claude|codex|chatgpt|copilot)\s+(code\s+)?(wrote|built|generated|created)",
     "tool attribution"),
    (r"\bai[\s-]generated\b", "tool attribution"),
    (r"\bas an ai\b", "model voice"),
]

# Naming a model is legitimate when it is a dependency. Surface it for a
# human to look at rather than blocking a project that genuinely uses one.
TOOL_NAMES = [r"\bclaude\b", r"\bcodex\b", r"\banthropic\b", r"\bopenai\b"]

EMOJI = re.compile("[%s-%s%s-%s%s]" % (
    chr(0x1F300), chr(0x1FAFF), chr(0x2600), chr(0x27BF), chr(0xFE0F)))

CODE_EXT = {".py", ".js", ".ts", ".sh", ".yml", ".yaml", ".toml"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".planning", ".agents", ".pytest_cache", ".mypy_cache"}
# This file is a list of the things it looks for, so it always matches itself.
SKIP_FILES = {"slop.py"}
ALLOW = "slop: allow"


def _finding(path, line, rule, detail, severity, excerpt):
    return {"path": str(path), "line": line, "rule": rule, "detail": detail,
            "severity": severity, "excerpt": excerpt.strip()[:110]}


def check_text(text: str, path: str = "", kind: str = "prose") -> list[dict]:
    """Findings for one blob. kind is prose or code."""
    out = []
    lines = text.splitlines()

    for n, line in enumerate(lines, 1):
        # A pattern that matches a banned character has to contain one.
        if ALLOW in line:
            continue
        for ch, name in BANNED_CHARS.items():
            if ch in line:
                out.append(_finding(path, n, "char", name, "block", line))
        if EMOJI.search(line):
            out.append(_finding(path, n, "char", "emoji", "block", line))

        low = line.lower()
        for phrase in BANNED_PHRASES:
            if phrase in low:
                out.append(_finding(path, n, "phrase", phrase, "block", line))
        for rx, name in BANNED_PATTERNS:
            if re.search(rx, low):
                out.append(_finding(path, n, "pattern", name, "block", line))
        for rx, name in ATTRIBUTION:
            if re.search(rx, low, re.IGNORECASE):
                out.append(_finding(path, n, "attribution", name, "block", line))
        for rx in TOOL_NAMES:
            if re.search(rx, low):
                out.append(_finding(path, n, "tool name",
                                    "names a model or vendor, check it is a real "
                                    "dependency and not a credit", "warn", line))

    if kind == "code":
        out += _comment_findings(lines, path)
    return out


def _comment_findings(lines: list[str], path: str) -> list[dict]:
    """Long comment blocks and overall comment density."""
    out = []
    run = 0
    code = 0
    comments = 0
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("#") or s.startswith("//"):
            run += 1
            comments += 1
            if run == 5:
                out.append(_finding(path, n - 4, "comment block",
                                    "five or more comment lines in a row",
                                    "block", line))
        else:
            run = 0
            if s:
                code += 1
    if code > 20:
        ratio = comments / float(code)
        if ratio > 0.15:
            out.append(_finding(path, 1, "comment density",
                                "comments are %d%% of code lines" % (ratio * 100),
                                "block", ""))
    return out


def check_file(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    kind = "code" if path.suffix in CODE_EXT else "prose"
    return check_text(text, str(path), kind)


def check_tree(root: Path, only: list[str] | None = None) -> list[dict]:
    """Walk a repository. only limits it to certain suffixes."""
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        if only and p.suffix not in only:
            continue
        if p.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico",
                        ".woff", ".woff2", ".zip", ".pyc"}:
            continue
        out += check_file(p)
    return out


def blocking(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["severity"] == "block"]


def report(findings: list[dict], limit: int = 60) -> str:
    if not findings:
        return "no findings"
    L = []
    for f in findings[:limit]:
        L.append("%-8s %s:%s  %s: %s" % (f["severity"], f["path"], f["line"],
                                         f["rule"], f["detail"]))
        if f["excerpt"]:
            L.append("         " + f["excerpt"])
    if len(findings) > limit:
        L.append("... and %d more" % (len(findings) - limit))
    return "\n".join(L)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    found = check_tree(target) if target.is_dir() else check_file(target)
    print(report(found))
    bad = blocking(found)
    print("\n%d blocking, %d warnings" % (len(bad), len(found) - len(bad)))
    sys.exit(1 if bad else 0)
