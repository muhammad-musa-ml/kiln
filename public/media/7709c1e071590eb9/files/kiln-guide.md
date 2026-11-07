# Untangle Codebase: published skill and evidence-led boundary changes

Researched 2026-11-07.

## Strengths and best use
The published Untangle Codebase skill asks whether pieces should change together. It organizes findings into hidden links, needless links, and surplus, then records structural decisions. That gives a code cleanup a stronger rationale than reducing line count alone. I found its public source and installation instructions during this research. [Published skill](https://github.com/caldoai/skills/blob/main/skills/untangle-codebase/SKILL.md) - [Repository](https://github.com/caldoai/skills)

## Current checks and setup
The repository lists MIT licensing and documents the following install route. Its source directs a broad refactor and has optional comment and test cleanup, so inspect the scope before invoking it in a project. The reel's attribution and time-saving claims remain unconfirmed by the inspected evidence.
```sh
npx skills add caldoai/skills --skill untangle-codebase
```

## Run a bounded assessment
Choose one change that currently touches several modules. Trace the actual dependency and data flow. Record duplicated rules, implicit ordering requirements, and volatile dependencies with file evidence. Protect CLI commands, webhooks, plugin exports, scheduled jobs, and other external entry points. Compare proposed boundaries against current callers and behavior.

Static reports from Knip or Vulture can identify candidates for investigation. Include a baseline and the behavior checks that would catch a real regression. Review the resulting diff in small stages. [Knip](https://knip.dev/overview/getting-started) - [Vulture](https://github.com/jendrikseipp/vulture)

## Reusable prompt
```text
Assess one bounded feature for hidden dependencies, needless coupling, and surplus. Cite file evidence and current callers. Protect external entry points. Propose a structural change with a behavior baseline, rollback plan, and tests that would catch a regression. Record why the proposed pieces should change together.
```

## Project idea
Build a change-coupling decision ledger joining imports, repeated rules, external entry points, and the observed cost of one maintenance task.


## Original sources
- https://www.instagram.com/reel/DfYbglQxEbl/