# Ruflo: current console setup and a bounded orchestration comparison

Researched 2026-10-20.

## What the reel shows and what remains unproven
Ruflo is a third-party agent orchestration system, not an Anthropic feature. The reel shows a console and describes a queen coordinating workers; it does not demonstrate faster completion on a controlled task. Adoption should depend on measured output quality and coordination cost, not repository stars.

## Current setup differs from the dossier
The [current upstream README](https://github.com/ruvnet/ruflo) separates core tools, the Claude console and runtime mods. It gives this Claude Code route and states a compatible minimum build:

```text
/plugin marketplace add ruvnet/ruflo
/plugin install ruflo-core@ruflo
/plugin install ruflo-console@ruflo
/plugin install ruflo-mods@ruflo
/reload-plugins
/ruflo
```

Review these components before installing; mods run with the account's permissions. The broader project setup route can create workspace configuration. Start in a disposable folder, inspect the resulting files and keep actual credentials out of recorded examples.

```sh
npx ruflo@latest init wizard
npx -y ruflo@latest mcp start
```

The first command runs an initializer; the second starts a local stdio MCP service. They are future setup instructions, not actions performed during research. Use a pinned version for a reproducible experiment. The upstream docs recommend the npx wizard for native Windows instead of assuming a POSIX shell.

## Choose a narrow first mission
Use one local documentation task: read a small fixture repository and propose an architectural decision with evidence paths. Require a budget, explicit worker ownership, a fixed output schema and a human review before any file or external change. First establish that one agent can perform the task accurately; only then compare a coordinated run.

The [user guide](https://github.com/ruvnet/ruflo/blob/main/docs/USERGUIDE.md) is the reference for current console and CLI behavior. The dossier's long hive-mind command and its exact flags should be checked against the installed version's help before use. A successful initialization is not proof that every research, security, benchmark or learning stage executed.

## Measurement plan
For a single-agent baseline and a small coordinated run, record the same task input, model, repository revision and acceptance criteria. Capture elapsed time, model calls, token usage, duplicated work, conflicting edits and the number of unsupported conclusions. Compare complete artifacts with an independent rubric.

Add one failure fixture: a worker cannot find the required file. The final result should expose that missing evidence rather than fabricate consensus. Stop the run when its budget is reached. This experiment has not been run for the guide.

## Reusable prompt
```text
Plan a bounded Ruflo evaluation on a disposable repository.
Inspect current installation and help output before proposing commands.
Compare one agent with a small coordinated run on the same documentation task.
Set a model budget, worker ownership and a single required ADR output.
Require evidence paths for decisions and expose unavailable workers.
Do not enable federation, background daemons, persistent credentials,
external writes or unattended execution.
```

## Project idea: coordination cost report
Create a local importer for real run logs. Normalize duration, usage, stage outcomes and reviewer scores into a comparison table. Start with manual CSV input so invented or unavailable measurements remain blank. Add a stage-evidence checklist: "secure" needs an actual tool result; "benchmark" needs a workload and measurements.

## Relationship and next step
Ruflo's dedicated orchestration and setup deserve their own tile even though it uses Claude plugins. Link it to agent workflow and mods guides as related material. Next: review its current install surface and run the documentation-only baseline before deciding whether extra coordination earns its cost.


## Original sources
- https://www.instagram.com/reel/Deffz7nReN9/