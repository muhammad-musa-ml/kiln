# OptMem: persistent notes, summary trees and a memory reliability test

Researched 2026-10-20.

## What the reel contributes
The Muse account describes a persistent agent memory that keeps recent notes readable and compresses older ranges. It is a useful memory design to evaluate, rather than proof that one chat can remember everything.

## What current primary sources establish
[OptMem's current README](https://github.com/VictorTaelin/OptMem) documents an append-only raw log, a rebuildable summary tree, regex retrieval and navigation back to raw notes. WAKE_LINES limits the briefing, not the stored history. A note is limited to **280 bytes**, which is different from 280 characters for Unicode text. The documented integration makes the parent responsible for memory; subagents should not write their own duplicate notes. The README's speed figures are author measurements, not Kiln benchmarks.

This belongs beside an Obsidian wiki as a distinct option: a wiki organizes curated documents, while OptMem keeps an event stream with a compressed briefing. Neither should silently become the authoritative record for a decision that exists in source control.

## Setup and commands
Requires Python 3. The [installer source](https://github.com/VictorTaelin/OptMem/blob/main/install.sh) writes the tool under the user's home directory. The following first command downloads it for review; inspect that file before choosing to run it. POSIX shell commands are for macOS/Linux/WSL or Git Bash; do not paste them into native PowerShell unchanged.

```sh
curl -fsSL https://raw.githubusercontent.com/VictorTaelin/OptMem/main/install.sh -o optmem-install.sh
# After reviewing the downloaded installer:
sh optmem-install.sh
~/.optmem/memo wake
~/.optmem/memo note "Decision: use SQLite for the scratch evaluation."
~/.optmem/memo recall "SQLite"
~/.optmem/memo config WAKE_LINES=300
```

Copy the printed integration block only into a scratch agent's instructions at first. The tool's own instructions are configuration for that future agent, not actions Kiln has executed. Keep the memory directory separate from production data. Record the repository revision used so future changes can be compared.

## Evaluate before adopting
Create twenty fictional facts and a separate answer key: ten decisions, five rejected approaches and five dates. Record them with several paraphrases and non-ASCII characters. Add enough intervening notes to trigger summaries, then start a fresh test session. Ask ten direct questions and ten questions requiring navigation into an older range.

Score each answer as correct with raw evidence, correct without evidence, unknown, or wrong. Record briefing size, merge calls and elapsed time. Compare with the same facts in a plain Markdown file. A fixed briefing size is not a quality guarantee: failure to record a fact cannot be repaired by searching, and a misleading summary should be checked against the log.

## Reusable project prompt
```text
Design an OptMem evaluation in a disposable workspace using fictional facts.
Keep a separate ground-truth file that the answering agent cannot read.
Compare raw Markdown memory with OptMem on identical questions.
Check byte limits, duplicate notes, stale summaries and raw-evidence recovery.
Do not modify global agent instructions, record personal facts, or claim a
benchmark result before a real run. Produce a scorecard and adoption decision.
```

## Project idea: memory reliability scorecard
Build a small Python harness that stores the question set and expected facts, imports actual answers, and exports a CSV plus a short report. Milestones: create fixtures; capture two real runs; score evidence support; inspect every wrong answer. Success means demonstrating the tradeoff with a reproducible dataset, not achieving a predetermined win.

## Limits and next step
The reel's permanent-chat framing is stronger than the evidence. Summaries remain lossy, regex depends on query wording, and the log is plaintext. This research did not install OptMem or execute the experiment. Next: review the installer and run the fictional-fact evaluation in isolation.


## Original sources
- https://www.instagram.com/reel/DeqPjGzjqD0/