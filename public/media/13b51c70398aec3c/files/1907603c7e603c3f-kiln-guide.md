# Business lead research with treg: an auditable, capped pilot

Researched 2026-11-03.

## A measured account research workflow

The reel reports 142 prospects, 76 verified email addresses, and about $0.25. The recording provides no endpoint ledger, scoring rubric, or deliverability results. The catalog size makes treg a plausible identification. The creator's gated link and the specific run remain unverified. The public treg repository documents a gateway, per-call billing for supported provider routes, and a Claude Code plugin. The correct repository owner is `superdesigndev`. [treg repository](https://github.com/superdesigndev/treg) - [Gateway site](https://treg.to/)

## Pilot the pipeline

1. Define a niche, geography, and evidence rubric. For example, record an inaccessible site, a missing booking path, or an absent mobile contact route as separate observations. Set an authorized source and a hard request and spend cap before running any metered call.
2. Use fictional rows first. For an authorized real pilot, capture the business domain, source URL, timestamp, and reason for inclusion. Deduplicate domains before enrichment. The official Places Text Search API documents field masks and pagination if you choose it for discovery. [Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search)
3. Manually review the highest-scoring candidates and a random sample. Separate a published business contact route from an inferred address, a catch-all result, and a source with no usable contact route.
4. Log each provider's call count, billed amount, result count, and retries. Record model cost and review time separately. Divide total cost by the number of unique, manually approved records. Keep list quality and delivery outcomes in separate columns.

## Official setup reference

The repository documents the following commands inside Claude Code. Authentication is through the MCP menu. Review the server's access and the catalog's current pricing before authorizing a provider call. [Plugin guide](https://github.com/superdesigndev/treg/blob/main/docs/CLAUDE-PLUGIN.md)

```text
/plugin marketplace add superdesigndev/treg
/plugin install treg@treg
/mcp
```

With the CLI already installed, the repository documents discovery and balance checks. [CLI documentation](https://github.com/superdesigndev/treg)

```sh
treg catalog search "business discovery by region"
treg balance
```

## Practice project

Prototype a CSV-to-review queue with fictional business records and mocked provider outcomes. Add a per-run ceiling, provenance, a manual approval field, and a reconciliation report for duplicate charges and retries.

## Reusable prompt

```text
Design a capped business-discovery pilot using these fictional fixtures. Produce a deduplicated review queue with source evidence and explainable site scores. Show how to reconcile model and provider charges. Preserve unknown values, distinguish verified fields from guesses, and stop at a human review report. Leave publishing and outreach disabled in the prototype.
```


## Original sources
- https://www.instagram.com/reel/DfPEnw6MqPP/