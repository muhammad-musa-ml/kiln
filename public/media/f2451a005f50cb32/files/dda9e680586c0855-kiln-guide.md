# Claude and Obsidian: a source-backed wiki that can evolve

Researched 2026-10-12.

## The source pattern
[Karpathy's LLM Wiki idea file](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) describes immutable raw sources, a maintained interlinked wiki and instructions that define how the agent works. It is a pattern to adapt, not an installed product. The reel adds a personal Obsidian workflow; Muse's reconstruction is retained separately from today's source check.

## Suggested structure
Use `raw/` for source snapshots, `wiki/` for compiled topic/entity pages, `index.md` for navigation and `CLAUDE.md` or `AGENTS.md` for the operating rules. Each compiled claim should link to a raw source and a date. Keep uncertain claims and contradictions visible instead of silently replacing them.

## Initial setup
Install from [Obsidian's official download page](https://obsidian.md/download), create a test vault, and add two public articles that disagree on a specific point. Give a filesystem-capable assistant access only to that test vault. A path in a prompt alone cannot grant access. The [Obsidian CLI](https://obsidian.md/help/cli) is optional; enable it in the application's settings if using automation.

```sh
obsidian help
```

## A repeatable ingest loop
1. Save source content and its URL without modifying the original.
2. Identify existing topic and entity pages before creating another page.
3. Propose edits that incorporate new evidence, retain source dates and flag contradictions.
4. Review the diff and update the index and change log.
5. Run a lint pass for broken links, missing source attribution and stale summaries.
6. Ask a question that spans both documents, and check that the answer points to the original evidence.

## Limits
Compilation can compound errors just as easily as knowledge. A coherent page is not independent verification. Large or changing sources require incremental updates and a stale-evidence policy. The dossier's old licensing/pricing statements are not adopted here; check Obsidian's current terms and the assistant's own usage plan.

## Project and evaluation
Build a small source-to-topic compiler with previewed diffs and a one-writer rule. Test duplicate ingestion, a contradiction, a removed source and a handoff to another assistant. Score claim attribution and stale-page detection, not just the number of generated notes. This connects directly to Kiln's own source-to-unified-topic architecture.

## Reusable project prompt
```text
Build Source-backed wiki compiler. Immutable raw notes, reviewed topic updates, contradiction flags and link/source linting. Read the linked official docs first. Use fixture data; keep credentials outside source control. Deliver tests, setup instructions, an evidence/limitations note and a small reproducible example. Do not claim a measurement you did not run. Milestones: Create raw/wiki/index contract; Implement previewed source-to-topic diffs; Add provenance and contradiction checks; Test stale sources and handoffs.
```

## Delivery and next step
The linked current sources were retrieved for this guide; the original dossier and its extraction caveats are retained in Sources. The guide and printable PDF are research deliverables. The proposed project has not been built. Start with the first milestone and verify its acceptance criteria before expanding the scope.


## Original sources
- https://www.instagram.com/reel/DeNtCA0lvvp/