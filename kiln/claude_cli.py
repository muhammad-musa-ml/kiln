"""Run Claude headless. The one place Kiln does it for follow-up work.

Two measurements shaped this. A plain `claude -p` on this machine loads
about 183k tokens of my own setup before it reads a word of the task:
every skill, every plugin, every connector, the global instructions. Safe
mode drops all of that and the same call costs 2k to 5k. And a worker
reading posts from strangers is reading text that can contain
instructions, so it runs restricted: no shell, and file writes confined
to its own folder. A write outside it was tried and refused.

The planner picks a model and an effort level for every task. It can pick
any of MODELS and nothing else, and never a Fable model. That rule is
checked here, in code, because a rule that only lives in a prompt is a
rule the model can talk itself out of.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# Who the planner can hand work to. The notes are what it reads when it
# chooses, so they say what each is for rather than how good it is.
MODELS = {
    "claude-opus-5": "Opus 5. Deepest judgement and synthesis. Slowest.",
    "claude-opus-5-5": "Opus 5.5. Deep judgement, research and writing that "
                       "has to be right.",
    "claude-sonnet-5": "Sonnet 5. Solid research, reading images and writing "
                       "documents. The usual choice for real work.",
    "claude-haiku-4-5-20251001": "Haiku 4.5. Quick lookups, checking a few "
                                 "links, formatting, simple extraction.",
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
PLANNER = ("claude-opus-5", "max")

# What a task can be given on top of reading its own folder.
KITS = {
    "web": ("WebSearch", "WebFetch"),
    "write": ("Write", "Edit"),
}
BASE_TOOLS = ("Read", "Glob", "Grep")

# The scheduled sync runs at max effort through CLAUDE_CODE_EFFORT_LEVEL, set
# for its own session only. That variable outranks --effort (measured
# 2026-09-26: a call started with --effort low asked the API for max), so a
# process Kiln starts must not inherit it, or every worker the planner put on
# low or medium runs at max.
_NOT_INHERITED = ("CLAUDE_CODE_EFFORT_LEVEL",)


def child_env() -> dict:
    """The environment for a process Kiln starts, minus what must not leak."""
    return {k: v for k, v in os.environ.items() if k.upper() not in _NOT_INHERITED}


# Words that mean the call never really happened, as opposed to a task that
# ran and went badly. The first wants trying again later and is nobody's
# fault; the second is a result. Only read off a failed call, never off the
# text of an answer, which can mention a rate limit perfectly innocently.
_BLOCKED = (
    ("usage limit", "usage limit reached"),
    ("rate limit", "rate limited"),
    ("rate_limit", "rate limited"),
    ("overloaded", "service overloaded"),
    ("429", "rate limited"),
    ("529", "service overloaded"),
    ("credit balance", "out of credit"),
    ("not logged in", "not signed in"),
    ("please run /login", "not signed in"),
    ("invalid api key", "not signed in"),
    ("authentication", "not signed in"),
    ("oauth", "not signed in"),
)


class Refused(ValueError):
    """A model or effort level the rules do not allow."""


def check_model(model: str, effort: str) -> None:
    if "fable" in (model or "").lower():
        raise Refused("Fable models are never used for Kiln work: %s" % model)
    if model not in MODELS:
        raise Refused("not an allowed model: %r (allowed: %s)"
                      % (model, ", ".join(MODELS)))
    if effort not in EFFORTS:
        raise Refused("not an effort level: %r (allowed: %s)"
                      % (effort, ", ".join(EFFORTS)))


@dataclass
class Result:
    ok: bool
    data: dict | None = None       # the structured answer when a schema was given
    text: str = ""
    model: str = ""
    effort: str = ""
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    turns: int = 0
    # Set when Claude could not run at all: out of usage, signed out, no
    # CLI. The work is not wrong, it is just not done yet.
    blocked: str = ""
    error: str = ""
    denied: list = field(default_factory=list)

    def log(self) -> dict:
        return {"model": self.model, "effort": self.effort, "ok": self.ok,
                "seconds": round(self.seconds, 1), "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "turns": self.turns,
                "blocked": self.blocked, "error": self.error[:300],
                "denied": len(self.denied)}


def blocked_reason(text: str) -> str:
    low = (text or "").lower()
    for needle, reason in _BLOCKED:
        if needle in low:
            return reason
    return ""


def command(exe: str, *, model: str, effort: str, kits=(),
            schema: dict | None = None) -> list[str]:
    """The command line, built on its own so a test can read it back.

    kits=None means no tools at all, not even reading its own folder. The
    planner runs like that: it decides, it does not go and look.
    """
    check_model(model, effort)
    tools = list(BASE_TOOLS) if kits is not None else []
    for k in kits or ():
        if k not in KITS:
            raise Refused("unknown tool kit: %r" % k)
        tools += [t for t in KITS[k] if t not in tools]
    cmd = [exe, "-p", "--model", model, "--effort", effort,
           "--output-format", "json", "--no-session-persistence",
           "--safe-mode", "--restricted",
           "--tools", ",".join(tools),
           "--permission-mode", "acceptEdits",
           "--permission-prompts", "none"]
    # Web tools ask for permission per call. With nobody there to answer,
    # anything not allowed up front is refused, so they are allowed here.
    # Writes need no rule: acceptEdits covers the working folder, and
    # restricted mode refuses everything outside it.
    web = [t for t in KITS["web"] if t in tools]
    if web:
        cmd += ["--allowedTools", *web]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    return cmd


def _kill_tree(p: subprocess.Popen) -> None:
    # Same reason as runner._kill_tree: a timed out agent can leave its own
    # children running unless the whole tree goes.
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                       capture_output=True)
    else:
        p.kill()
    try:
        p.wait(timeout=30)
    except Exception:
        pass


def run(prompt: str, *, model: str, effort: str, cwd: Path, kits=(),
        schema: dict | None = None, timeout: int = 1800) -> Result:
    """One headless call. Never raises; a refusal comes back as a failed Result."""
    res = Result(ok=False, model=model, effort=effort)
    exe = shutil.which("claude")
    if not exe:
        res.blocked = "claude is not on PATH"
        res.error = res.blocked
        return res
    try:
        cmd = command(exe, model=model, effort=effort, kits=kits, schema=schema)
    except Refused as e:
        res.error = str(e)
        return res

    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        # The prompt goes on stdin. On Windows a command line tops out at
        # about 32k characters, and a brief with a whole carousel in it is
        # longer than that.
        p = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=child_env())
    except Exception as e:
        res.error = "could not start claude: %s: %s" % (type(e).__name__, e)
        res.blocked = res.error
        return res
    try:
        out, err = p.communicate(prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        res.seconds = time.time() - t0
        res.error = "timed out after %d minutes" % (timeout // 60)
        return res
    res.seconds = time.time() - t0
    stdout = out.decode("utf-8", "replace").strip()
    stderr = err.decode("utf-8", "replace").strip()

    try:
        d = json.loads(stdout)
    except Exception:
        tail = (stdout or stderr)[-600:]
        res.error = "no JSON from claude (exit %s): %s" % (p.returncode, tail)
        res.blocked = blocked_reason(stdout + " " + stderr)
        return res

    usage = d.get("usage") or {}
    res.tokens_in = int(usage.get("input_tokens") or 0) \
        + int(usage.get("cache_creation_input_tokens") or 0) \
        + int(usage.get("cache_read_input_tokens") or 0)
    res.tokens_out = int(usage.get("output_tokens") or 0)
    res.turns = int(d.get("num_turns") or 0)
    res.text = str(d.get("result") or "")
    res.denied = list(d.get("permission_denials") or [])

    if d.get("is_error") or p.returncode != 0:
        why = " ".join(str(x) for x in (d.get("subtype"), d.get("api_error_status"),
                                        res.text, stderr) if x)
        res.error = ("claude reported an error: %s" % why)[:600]
        res.blocked = blocked_reason(why)
        return res

    if schema is not None:
        so = d.get("structured_output")
        if not isinstance(so, dict):
            res.error = "the answer did not come back in the required shape"
            return res
        res.data = so
    res.ok = True
    return res
