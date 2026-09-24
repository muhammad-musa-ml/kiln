"""Take a finished build, check it, write its readme, put it on GitHub.

Three stages after the builder stops. A reviewer reads the project and
tries to run it, a readme gets written and has to pass the slop check,
and then the repo is created and pushed.

The reviewer gets a named list of tools rather than a blanket permission
bypass, so it can edit the project and run its tests and not much else.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

from . import slop

REVIEW_TIMEOUT = 1800
README_TIMEOUT = 900
PUSH_TIMEOUT = 600

# One entry per rule, and they stay whole. These were a single string that
# got split on whitespace, which turns Bash(python *) into Bash(python and
# *) and leaves the reviewer unable to run anything at all. It still wrote a
# verdict, so the failure looked like a bad project rather than a bad flag.
REVIEW_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write",
                "Bash(python *)", "Bash(py *)", "Bash(pytest *)",
                "Bash(pip *)", "Bash(ls*)", "Bash(dir*)", "Bash(cat*)",
                "Bash(type*)")
README_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write")

# Build tooling leaves these behind. None of it belongs in a published repo.
STRIP = [".planning", ".agents", "kiln-review.json", ".codex", ".gemini"]

# A failed build matching one of these is the agent being unavailable, not
# the project being broken. The difference decides whether to retry later or
# tell someone the build is bad. Anchored on word boundaries on purpose:
# a bare substring for a network error finds ENOTFOUND inside
# ModuleNotFoundError, which is the most ordinary build failure there is.
UNAVAILABLE = [
    (r"\brate[ _-]?limit", "rate limited"),
    (r"\btoo many requests\b", "rate limited"),
    (r"(?<![\w.])429(?![\w.])", "rate limited"),
    (r"\bquota\b", "out of quota"),
    (r"\binsufficient_quota\b", "out of quota"),
    (r"\busage[ _-]limit", "usage limit reached"),
    (r"\bnot authenticated\b", "not signed in"),
    (r"\blogin required\b", "not signed in"),
    (r"\bunauthorized\b", "not authorised"),
    (r"(?<![\w.])401(?![\w.])", "not authorised"),
    (r"\binvalid api key\b", "bad credentials"),
    (r"\bbilling\b", "billing problem"),
    (r"\bfetch failed\b", "network unreachable"),
    (r"\benotfound\b", "network unreachable"),
    (r"\beconnrefused\b", "network unreachable"),
    (r"\betimedout\b", "network unreachable"),
    (r"\bservice unavailable\b", "service down"),
    (r"(?<![\w.])50[23](?![\w.])", "service down"),
    (r"\bbad gateway\b", "service down"),
]


def agent_blocked(text: str) -> str:
    """Name the reason the agent could not run, or empty if it did run."""
    low = (text or "").lower()
    for rx, reason in UNAVAILABLE:
        if re.search(rx, low):
            return reason
    return ""


def _run(cmd: list[str], cwd: Path, timeout: int, stdin_text: str = "") -> tuple:
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd),
            input=stdin_text.encode("utf-8") if stdin_text else None,
            stdin=None if stdin_text else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -1, "[timed out after %d seconds]" % timeout
    except Exception as e:
        return -1, "[failed to start: %s: %s]" % (type(e).__name__, e)


def _claude_cmd(exe: str, prompt: str, tools) -> list:
    """The command line, built separately so a test can read it back."""
    return [exe, "-p", prompt, "--permission-mode", "acceptEdits",
            "--permission-prompts", "none", "--output-format", "text",
            "--allowedTools"] + list(tools)


def _claude(prompt: str, workdir: Path, tools, timeout: int) -> tuple:
    exe = shutil.which("claude")
    if not exe:
        return -1, "[claude is not on PATH]"
    return _run(_claude_cmd(exe, prompt, tools), workdir, timeout)


REVIEW_PROMPT = """Review this project. It was generated from a brief and nobody has checked it yet.

Do these in order.

1. Read the code and work out whether it does what the brief asked for.
2. Install what it needs and run its tests if it has any. If you cannot install or cannot reach the network, say so rather than guessing.
3. Fix what you can fix safely: broken imports, missing files, wrong paths, failing tests, anything half finished.
4. Write your verdict to a file called kiln-review.json in the project root. Use exactly this shape and nothing else in the file:

{"complete": true, "runnable": true, "tests_run": true, "tests_pass": true, "fixed": ["what you changed"], "blocking": ["what should stop this being published"], "summary": "one or two plain sentences"}

complete means every part of the brief is actually implemented, not stubbed.
runnable means someone could clone it and get it working by following the readme.
blocking is an empty list if there is nothing serious wrong.

Be honest. A project that does not work is a useful thing to say."""


def review(workdir: Path) -> dict:
    """Have the reviewer check and fix the project, then read its verdict."""
    out_file = workdir / "kiln-review.json"
    if out_file.exists():
        out_file.unlink()

    code, log = _claude(REVIEW_PROMPT, workdir, REVIEW_TOOLS, REVIEW_TIMEOUT)
    verdict = {"complete": False, "runnable": False, "tests_run": False,
               "tests_pass": False, "fixed": [], "blocking": [], "summary": ""}

    if out_file.exists():
        try:
            raw = out_file.read_text(encoding="utf-8", errors="replace").strip()
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                verdict.update(json.loads(m.group(0)))
        except Exception as e:
            verdict["blocking"] = ["could not read the review file: %s" % e]
    else:
        verdict["blocking"] = ["the reviewer wrote no verdict"]
        verdict["summary"] = log.strip()[-400:]

    verdict["exit_code"] = code
    verdict["log_tail"] = log.strip()[-1500:]
    return verdict


def _readme_prompt(job: dict, verdict: dict) -> str:
    source = job.get("source") or job.get("source_url") or ""
    banned = ", ".join(slop.BANNED_PHRASES[:28])
    return """Write the README.md for this project.

You are writing as the person whose repository this is. A graduate student, writing plainly about something they built. First person. Short sentences. No selling.

Cover, in whatever order reads best:
what it does, what it is built with, how to install and run it, how to run the tests, and what is rough or missing. Say in one line that the idea came from %s, without naming any tool or assistant.

Say what is actually true. The reviewer found this: %s

Hard rules. A check rejects the file if you break any of them.
Plain ASCII punctuation only. No em dashes, en dashes, arrows, middots, curly quotes, bullet characters, ellipsis characters, check marks or emoji. Hyphens and straight quotes are fine.
Never say or imply that any AI tool, model or assistant produced this. No co-author lines. Naming a library the project depends on is fine.
Do not use any of these words or phrases: %s.
Do not write "not just X but Y" or "it is not X, it is Y" or "more than just".
No padding, no marketing, no section that exists only so there is a section.

Write the file and nothing else.""" % (source or "a post I saved",
                                       verdict.get("summary") or "no summary",
                                       banned)


def write_readme(workdir: Path, job: dict, verdict: dict) -> dict:
    """Write the readme, then hold it to the slop check. One retry."""
    path = workdir / "README.md"
    attempts = []

    for attempt in (1, 2):
        prompt = _readme_prompt(job, verdict)
        if attempt == 2 and attempts:
            prompt += ("\n\nYour last attempt was rejected. Fix exactly these "
                       "and rewrite the whole file:\n" + attempts[-1]["report"])
        code, log = _claude(prompt, workdir, README_TOOLS, README_TIMEOUT)

        if not path.exists():
            attempts.append({"attempt": attempt, "ok": False,
                             "report": "no README.md was written",
                             "exit_code": code, "log_tail": log[-600:]})
            continue

        found = slop.check_file(path)
        bad = slop.blocking(found)
        attempts.append({"attempt": attempt, "ok": not bad,
                         "report": slop.report(bad, 25),
                         "findings": len(bad), "exit_code": code})
        if not bad:
            break

    return {"ok": bool(attempts) and attempts[-1]["ok"], "attempts": attempts,
            "path": str(path)}


def _force_rm(path: Path) -> None:
    """Remove a tree even when git has left files read only."""
    def on_error(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    if path.exists():
        shutil.rmtree(path, onerror=on_error)


def scrub(workdir: Path) -> list[str]:
    """Drop build tooling artifacts and start the history clean."""
    removed = []
    for name in STRIP + [".git"]:
        p = workdir / name
        if p.is_dir():
            _force_rm(p)
            removed.append(name)
        elif p.exists():
            p.unlink()
            removed.append(name)
    return removed


def gate(workdir: Path) -> dict:
    """What must be clean before anything is pushed.

    Characters and tool credit are not judgement calls, so they stop the
    push. Wording in the project's own code is reported and left alone,
    because blocking a working project over a word in a docstring helps
    nobody.
    """
    findings = slop.check_tree(workdir)
    hard = [f for f in findings if f["severity"] == "block"
            and f["rule"] in ("char", "attribution")]
    soft = [f for f in findings if f not in hard]
    return {"ok": not hard, "hard": hard, "soft": soft,
            "report": slop.report(hard, 30)}


def publish(workdir: Path, name: str, description: str = "",
            public: bool = True) -> dict:
    """Create the repo and push one clean commit."""
    gh = shutil.which("gh")
    git = shutil.which("git")
    if not gh or not git:
        return {"ok": False, "error": "gh and git both need to be on PATH"}

    steps = []
    for cmd in ([git, "init", "-b", "main"],
                [git, "add", "-A"],
                [git, "-c", "commit.gpgsign=false", "commit", "-m",
                 "First working version of %s" % name]):
        code, out = _run(cmd, workdir, 120)
        steps.append({"cmd": " ".join(Path(c).name if i == 0 else c
                                      for i, c in enumerate(cmd)),
                      "exit": code, "out": out.strip()[-400:]})
        if code != 0:
            return {"ok": False, "error": "git step failed", "steps": steps}

    create = [gh, "repo", "create", name,
              "--public" if public else "--private",
              "--source", ".", "--push"]
    if description:
        create += ["--description", description[:340]]
    code, out = _run(create, workdir, PUSH_TIMEOUT)
    steps.append({"cmd": "gh repo create", "exit": code,
                  "out": out.strip()[-600:]})
    if code != 0:
        return {"ok": False, "error": "gh repo create failed", "steps": steps}

    url = ""
    m = re.search(r"https://github\.com/[\w.-]+/[\w.-]+", out)
    if m:
        url = m.group(0)
    else:
        c2, o2 = _run([gh, "repo", "view", "--json", "url", "-q", ".url"],
                      workdir, 120)
        if c2 == 0:
            url = o2.strip().splitlines()[-1] if o2.strip() else ""
    return {"ok": True, "url": url, "steps": steps}


def ship(workdir: Path, job: dict, public: bool = True) -> dict:
    """Review, write the readme, check it, and push. Stops at the first no."""
    out = {"started": time.time()}

    out["review"] = review(workdir)
    if out["review"].get("blocking") or not out["review"].get("complete"):
        out["stage"] = "review"
        out["ok"] = False
        out["why"] = "the reviewer found blocking problems"
        return out

    out["readme"] = write_readme(workdir, job, out["review"])
    if not out["readme"]["ok"]:
        out["stage"] = "readme"
        out["ok"] = False
        out["why"] = "the readme did not pass the slop check"
        return out

    out["scrubbed"] = scrub(workdir)
    out["gate"] = gate(workdir)
    if not out["gate"]["ok"]:
        out["stage"] = "gate"
        out["ok"] = False
        out["why"] = "banned characters or tool credit in the files"
        return out

    name = job.get("repo_name") or workdir.name
    out["publish"] = publish(workdir, name,
                             out["review"].get("summary", ""), public)
    out["stage"] = "publish"
    out["ok"] = out["publish"].get("ok", False)
    out["why"] = "" if out["ok"] else out["publish"].get("error", "push failed")
    out["finished"] = time.time()
    return out
