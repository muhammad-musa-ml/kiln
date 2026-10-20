# Matt Pocock skills: decisions, specifications, vertical tickets and retrospectives

Researched 2026-10-20.

## What the video adds
The explainer presents a workflow in which a human settles product decisions, an agent writes a specification, tickets become small vertical slices, implementation is reviewed, and a retrospective improves the environment. The coffee-subscription example illustrates why "pause" and "skip" need explicit meanings before code is written.

## Current installation
Matt Pocock's [current repository](https://github.com/mattpocock/skills) documents a Claude Code plugin that updates automatically, plus editable-file installation for other workflows. Pick one route to avoid duplicate copies.

```sh
claude plugin install mattpocock-skills@claude-plugins-official
```

Run setup once in a scratch repository and choose local files as the tracker if no external writes are wanted:

```text
/setup-matt-pocock-skills
/grill-with-docs
/to-spec
/to-tickets
/implement
/code-review
/retro
```

These names are repository skills, not a promise that every agent exposes identical commands. Check the installed version and files. The video describes a particular release; install paths and skill behavior can evolve. Nothing here installed the plugin or started a build.

## Apply the workflow at the right scale
For a small change, use one short plan and one implementation slice. For a larger change, settle terms and behavior, then record the decisions the code cannot answer. Keep unresolved questions visible rather than letting an agent invent defaults.

The [to-spec implementation](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-spec/SKILL.md) turns established context into a specification and confirms testing seams. The [ticket skill](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-tickets/SKILL.md) creates vertical work items with dependency edges. A slice should produce observable behavior across necessary layers, not merely create all database files first and all UI files later.

The video's 150k-token rule is a heuristic, not a universal reasoning limit. Use actual task size, context pressure and failure observations when deciding whether to split work.

## Review and retrospective
Compare implementation with explicit acceptance criteria and separately inspect maintainability. Avoid treating the implementer's assertion that tests pass as proof that the feature matches the decision. A [retrospective](https://github.com/mattpocock/skills/blob/main/skills/engineering/retro/SKILL.md) should suggest environment improvements for human selection, such as a navigation pointer or a meaningful check; it should not silently rewrite every instruction after one difficult run.

## Project: a subscription-pause practice feature
In a disposable app, model subscription state, next charge, resume date and a packed delivery. Decide exactly when pause takes effect and what happens to an already packed order. Write three acceptance cases, then slice the work: charge suppression, resume behavior and packed-order handling. A test at the billing boundary must show the before/after behavior.

Deliver a small spec, dependency diagram, tests, change review and retrospective recommendations. This is a proposed exercise; neither a payment integration nor an actual charge should be introduced.

## Reusable prompt
```text
Help specify a subscription-pause exercise in a disposable app.
Read facts from the code before asking about product choices.
Resolve billing timing, packed deliveries, pause length and domain terms.
Write testable stories and minimal vertical tickets with dependency edges.
Implement only the approved scope, review behavior against the stories,
then suggest retrospective improvements for me to choose.
Do not create external issues, submit a PR or connect real payments.
```

## Next step
Read the setup and first skill, choose one small feature and measure whether clearer decisions reduce rework. Repository popularity, narrated delivery time and a claimed skill-token total are not quality guarantees.


## Original sources
- https://youtu.be/Q3uuE2adUT8