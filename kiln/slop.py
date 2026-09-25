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
# These two hold the list of things to look for, so they always match
# themselves. ship.py quotes the rules into the brief it sends the writer.
# Kiln's own two files, by path: matched by name, a built project's own
# ship.py or slop.py would have gone out unchecked.
SKIP_FILES = {Path(__file__).resolve(), Path(__file__).resolve().parent / "ship.py"}
ALLOW = "slop: allow"


def voice_rules() -> str:
    """The writing rules as a block to paste into a prompt.

    Two prompts need these: the one that asks for a project to be built, and
    the one that asks for its readme. They were going to be written out twice,
    and two copies of a rule drift until the one nobody is reading is the one
    that reaches a public repository. This is the only copy.

    It is built from the same lists the checker enforces, so a word added to
    BANNED_PHRASES is a word the writer is told about in the same commit.
    """
    return """Write the way I write. A graduate student saying plainly what
something does. First person where it is natural. Short sentences. No selling.

Plain ASCII punctuation only. No em dashes, en dashes, arrows, middots, curly
quotes, bullet characters, ellipsis characters, check marks or emoji. Hyphens
and straight quotes are fine.

Never say or imply that any AI tool, model or assistant had a hand in this.
No co-author lines, no credit, no mention of one anywhere. Naming a library
the project genuinely depends on is fine.

Do not use any of these words or phrases: %s.
Do not write "not just X but Y", or "it is not X, it is Y", or "more than just".

Comments explain why something is the way it is, not what the line does. No
comment blocks five lines long, no banner headers, no restating the function
name in a docstring. If a comment would only repeat the code, leave it out.

No padding, no marketing, and no section that exists only so there is a
section.""" % ", ".join(BANNED_PHRASES)


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
        if p.resolve() in SKIP_FILES:
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


# How each kind of banned character is spelled in ASCII, keyed by the names
# BANNED_CHARS uses, so a new character of a known kind needs no edit here.
PLAIN_KINDS = {
    "em dash": " - ", "en dash": "-", "arrow": "->", "middot": "-",
    "bullet character": "-", "curly quote": '"', "ellipsis character": "...",
    "non breaking space": " ", "check mark": "yes", "cross mark": "no",
}

# Kinds with more than one spelling, and emoji that still mean yes or no.
PLAIN_CHARS = {
    chr(0x2190): "<-", chr(0x21D2): "=>", chr(0x2018): "'", chr(0x2019): "'",
    chr(0x2714): "yes", chr(0x2611): "yes",
    chr(0x2716): "no", chr(0x2718): "no", chr(0x274C): "no", chr(0x2612): "no",
}


def plain(text: str) -> str:
    """The text with every banned character spelled in ASCII and emoji removed.

    check_text can only say a text is wrong. This is for text that gets
    written somewhere without passing through it: a title, a note, a document
    someone asked for. It walks BANNED_CHARS itself, so whatever the checker
    blocks is exactly what gets replaced. A character of a kind with no
    spelling is dropped rather than let through, and scripts/test_artifacts.py
    fails until the kind gets one. The emoji that mean yes and no are spelled
    out before the rest go, since dropping them would empty the answer column
    of a comparison table.
    """
    for ch, kind in BANNED_CHARS.items():
        if ch not in text:
            continue
        to = PLAIN_CHARS.get(ch, PLAIN_KINDS.get(kind, ""))
        if kind == "em dash":
            # Spaces round the dash merge into the spelling's own; indents stay.
            dash = "(?:%s[ \t]*)+" % re.escape(ch)
            text = re.sub(r"(?m)^([ \t]*)" + dash, lambda m: m.group(1) + to.lstrip(), text)
            text = re.sub(r"[ \t]*" + dash, lambda m: to, text)
        else:
            text = text.replace(ch, to)
    for ch, to in PLAIN_CHARS.items():
        text = text.replace(ch, to)
    run = "(?:%s)+" % EMOJI.pattern
    text = re.sub(r"(?m)^([ \t]*)" + run + "[ \t]?", lambda m: m.group(1), text)
    text = re.sub(r"(?m)[ \t]" + run + r"(?=[ \t\r]|$)", "", text)
    return re.sub(run, "", text)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    found = check_tree(target) if target.is_dir() else check_file(target)
    print(report(found))
    bad = blocking(found)
    print("\n%d blocking, %d warnings" % (len(bad), len(found) - len(bad)))
    sys.exit(1 if bad else 0)
