# Claude session handoffs: You Should Know and auto-handoff

Researched 2026-10-20.

## Two tools solve different problems
The reel puts You Should Know and auto-handoff together. The first surfaces an overlooked point while a session is working; the second replaces automatic compaction with a structured transfer to a fresh session. Neither promises perfect memory.

[Anthropic's current interactive-mode documentation](https://code.claude.com/docs/en/interactive-mode#you-should-know-suggestions) confirms that You Should Know is off by default, requires a compatible build and eligible feature flags, and uses a side request without tools. A missing-plugin message can mean the current session is ineligible; changing telemetry is a separate preference, not a prerequisite Kiln has changed.

## Supported setup
Check the installed version, then use the enable command inside an eligible Claude Code session:

```sh
claude --version
```

```text
/plugin enable cc-plugin-you-should-know@builtin
```

The [community auto-handoff README](https://github.com/alexknowshtml/claude-auto-handoff) documents this separate local plugin path:

```sh
git clone https://github.com/alexknowshtml/claude-auto-handoff.git claude-auto-handoff
claude plugin validate ./claude-auto-handoff
claude --plugin-dir ./claude-auto-handoff
```

Inspect the cloned handlers before launching. These commands are documented instructions, not software installed during this research. Use an isolated session first, and record the chosen Git commit. Ongoing model requests and brief generation consume the user's plan or API allowance.

## Handoff behavior and settings
The repository describes a Haiku-written brief, a facts-only fallback if generation fails, a clear-and-reseed transition, an editable template and loop guards. Its default threshold is 160,000 tokens for a 200k context; that is a project setting, not a universal optimum. It also applies a minimum amount of new work after a seeded session. The optional brief viewer can bind to Tailscale; disable it if local files are sufficient. Current release notes include Windows fallbacks, while serving the viewer may still depend on a POSIX shell. [Source and settings](https://github.com/alexknowshtml/claude-auto-handoff#configure).

## A useful reproduction
Before enabling a low threshold, write an answer key containing two decisions, one rejected approach, the exact unfinished request and a next step. Use a disposable repository with no credentials. Let the session do ordinary bounded work, observe a real handoff and compare the brief and resumed answer with that key.

Record missing decisions, invented details, repeated work, tool calls blocked at the threshold, elapsed time and additional model usage. Test the documented disable flag in a separate session. Do not pad a session with private files just to force a transition.

## Reusable prompt
```text
Evaluate You Should Know plus claude-auto-handoff in a disposable repository.
First report version, eligibility, plugin commit and relevant settings.
Use fictional seeded facts and an independently saved answer key.
Show a manual handoff baseline and one actual automatic handoff.
Report unknowns and failures, including facts-only fallback behavior.
Do not change persistent settings or expose the brief viewer without asking.
```

## Project idea and remaining gaps
Create a handoff regression fixture with a checklist of preserved decisions, abandoned paths and the next requested action. Compare manual notes, native compaction and the community mod on identical work. A successful prototype produces inspectable briefs and honest results; no timing or recall benchmark was run for this guide.

This source expands the existing Claude Code mods topic. Its transcript and original URL remain separate evidence while the main topic integrates handoffs with panes, watchers, dashboards and unfinished-work tracking.


## Original sources
- https://www.instagram.com/reel/Deo8i2rEQi5/