# Auditing and Structuring Claude Agent Skills Against Anthropic Standards

Researched 2026-10-12.

# Claude Agent Skill Architecture and Audit Guide

### 1. What the Social Reel Claims
The social reel by Kevin Magnan on [Instagram](https://www.instagram.com/reel/DeQYD7-CXLk/) presents recent guidance as an unannounced rule shift and gates an audit prompt behind direct-message engagement. The reel outlines five core rules:
- Keep the primary `SKILL.md` under 500 lines.
- Shift complex operational details into external reference files linked directly from the primary skill file.
- Enforce single-hop file referencing (avoiding reference chains) because Claude truncates secondary files with tools like `head -100`.
- Insert a table of contents at the top of reference files exceeding 100 lines.
- Balance instructions using "degrees of freedom" (narrow bridge vs. open field analogy).

The reel's framing treats these practices as secret updates and mischaracterizes code reviews as requiring written procedural instructions (low-to-medium freedom).

---

### 2. What Official Sources and Technical Evidence Confirm

Official Anthropic documentation and empirical session logs confirm the structural requirements while refining behavioral mechanics:

* **Skill Structure and Progressive Disclosure:** Official guidelines in [Anthropic's Skill Authoring Best Practices](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices) confirm that `SKILL.md` must stay under 500 lines to avoid consuming the context window prematurely. Reference files must link directly from `SKILL.md` (one level deep) because nested link chains cause Claude to preview only initial lines. Files longer than 100 lines require a leading table of contents.
* **Degrees of Freedom Nuance:** The official guidelines define three distinct tiers:
  - **High Freedom:** Text heuristics and principles where multiple paths are valid. The documentation explicitly lists *code reviews* as high freedom, correcting the reel's description.
  - **Medium Freedom:** Pseudocode or parameterized templates where a standard pattern exists (e.g., report generators).
  - **Low Freedom:** Exact deterministic scripts with strict commands and flags (e.g., database migrations that must run sequentially as-is).
* **Invocation and Listing Budgets:** According to [Claude.ai Skills Documentation](https://claude.com/docs/skills/overview), Claude evaluates `name` and `description` headers to select skills. Descriptions must state what the skill does and concrete triggering circumstances. As noted by [Implicator's reporting on Claude Code updates](https://www.implicator.ai/anthropic-claude-code-skill-doctor-context-audit/), skill listings are placed into context on every turn and consume up to 1% of the model window by default. In Claude Code 2.1.261+, listing entries cap combined descriptions at 1,536 characters (the base Agent Skills specification caps descriptions at 1,024 characters).
* **CLI Tooling Integration:** Custom commands and skills have merged under Claude Code. Native diagnostic commands (`/doctor` and `/skill-doctor`) audit unused context consumption and flag dormant skills.
* **Empirical Session Validation:** Independent testing published by [StationX](https://app.stationx.net/articles/claude-code-skills) across 17,000 CLI sessions confirmed that descriptions function as both triggers and brakes; overly vague descriptions cause false activations on non-matching tasks. Furthermore, Claude failed to read beyond the first 100 lines in 14% of file reads, confirming the necessity of leading indices.

---

### 3. What Remains Uncertain

- **Empirical Impact of TOCs:** StationX's controlled test runs across Haiku 4.5, Sonnet 5.5, and Opus 5.5 indicated that while top-of-file placement is crucial, strict table-of-contents formatting did not systematically alter retrieval accuracy in every benchmark.
- **Internal Benchmark Baselines:** Anthropic's internal claims that cutting over 80% of system prompts caused "no measurable loss" on Opus and Fable evaluations remain backed only by internal notes, with no public evaluation dataset.
- **Universal Frontmatter Portability:** The header option `disable-model-invocation: true` prevents background listing overhead in Claude Code, but [StationX notes](https://app.stationx.net/articles/claude-code-skills) that strict external Agent Skills linters outside Claude Code may reject this custom key.

---

### 4. Implementation Prerequisites and Common Pitfalls

#### Prerequisites
- Claude Code CLI version 2.1.261 or later for diagnostic audits.
- Python 3.10+ for running deterministic validation or migration utility scripts.
- File workspace configured with local `.claude/skills/` or `~/.claude/skills/` directories.

#### Common Mistakes
1. **Chained References:** Linking `SKILL.md -> guide.md -> api.md`. Claude frequently partial-reads `api.md` with head utilities and misses parameters.
2. **Vague Metadata:** Using descriptions like `Helps with data` instead of exact keyword-rich triggers (`Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs.`).
3. **Over-Constraining High-Reasoning Models:** Feeding exhaustive line-by-line procedural instructions to Claude Opus on subjective tasks, which restricts exploration and degrades analytical output.
4. **Unstated Script Dependencies:** Writing low-freedom scripts in `scripts/` that assume libraries are already installed without explicit setup or install guards in the execution block.

---

### 5. Reusable Claude Code Skill Audit Prompt

Use this standalone prompt inside Claude Code or Claude Chat to inspect installed skills against official specifications:

```markdown
Audit all skill definitions in this repository against Anthropic's Agent Skill best practices.

Inspect all SKILL.md files located in .claude/skills/ and ~/.claude/skills/.
Validate the following criteria:
1. SKILL.md line count: Must not exceed 500 lines (excluding YAML frontmatter).
2. Reference depth: Every linked Markdown document must be directly referenced from SKILL.md. Flag any multi-hop references.
3. Table of Contents: Any referenced Markdown file over 100 lines must contain a table of contents within the first 50 lines.
4. Metadata sanity: Ensure 'name' is lower-case alphanumeric with hyphens (max 64 chars) and 'description' details both what it does and specific user invocation triggers (max 1024 chars).
5. Degrees of freedom: Verify fragile operations (file mutations, migrations, deletions) use exact scripts rather than open prose instructions.

Generate a Markdown report summarizing: Skill Name | File Path | Rule Status | Recommended Remediation.
Do not modify any files until instructed.
```

---

### 6. Official Reference Links
- [Claude Platform Documentation](https://platform.claude.com/docs/en/home)
- [Anthropic Skill Authoring Best Practices](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices)
- [Claude.ai Skills Overview](https://claude.com/docs/skills/overview)
- [MindStudio Analysis: Claude Skills Best Practices](https://www.mindstudio.ai/blog/claude-skills-best-practices-update)
- [Implicator: Claude Code /skill-doctor Audit](https://www.implicator.ai/anthropic-claude-code-skill-doctor-context-audit/)
- [StationX: 8 Rules From 17,000 Real Sessions](https://app.stationx.net/articles/claude-code-skills)

## Original sources
- https://www.instagram.com/reel/DeQYD7-CXLk/