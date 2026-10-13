# Agentic Engineering & Skill Craft Guide: From Vibe Coding to Rigorous AI Systems

Researched 2026-10-12.

### 1. What the Reel Claims

In an October 2026 Instagram reel ([Instagram source](https://www.instagram.com/reel/DeCZn6JMmYf/)), creator Ibrahim Shareef argues that achieving 'S-tier' AI development requires studying three core videos totaling under 90 minutes:
1. **Andrej Karpathy:** Explaining why fast prototyping ('vibe coding') is insufficient and why builders must prioritize engineering quality and orchestration.
2. **Matt Pocock:** Demonstrating how to design modular agent skills (pre-prompts/reusable workflows) tailored to developer workflows.
3. **Boris Cherny:** Explaining how Anthropic's team eliminated approximately 80% of Claude Code's system prompts across model releases to avoid prompt bloat.

The reel uses a keyword gate (`STIER`) to distribute links via automated direct messages rather than publishing them in the description.

---

### 2. What Primary and Current Sources Confirm

Cross-referencing the reel's claims against official releases and repository documentation reveals solid foundations behind each reference:

* **Andrej Karpathy on Agentic Engineering:**
  * Karpathy introduced 'vibe coding' in early 2025 and expanded on 'Agentic Engineering' at Sequoia Capital's AI Ascent fireside chat (April 2026; writeup mirrored at [ElevateX](https://elevatex.de/blog/ai/what-is-agentic-engineering/)).
  * **Software 3.0 framing:** Karpathy contrasts Software 1.0 (manual coding) and 2.0 (weights trained on data) with Software 3.0 (context engineering). In this paradigm, programming consists of structuring prompts, tools, diff reviews, and context windows. Builders shift from manual implementation to verification and test loops ('You can outsource thinking; you can't outsource understanding').

* **Matt Pocock's Agent Skill Framework:**
  * Pocock's AI Engineer SF presentation ([YouTube](https://www.youtube.com/watch?v=UNzCG3lw6O0)) and repository ([GitHub: mattpocock/skills](https://github.com/mattpocock/skills)) formalize the design of `.md` skills to prevent 'Skill Hell' (unstructured prompt graveyards).
  * **Skill Checklist:**
    * **Trigger:** Split skills strictly between *user-invoked* (`/grill-me`, `/tdd`, `/triage`) for high-level orchestration, and *model-invoked* (`diagnosing-bugs`, `code-review`) for internal tool-use disciplines.
    * **Structure:** Keep the root `SKILL.md` minimal; delegate expansive background documentation to referenced sub-paths.
    * **Steering:** Use high-density domain words (ubiquitous language) and enforce intermediate steps ('leg work') instead of single-shot completions.
    * **Pruning:** Conduct deletion tests. Any line whose removal does not alter behavior is dead weight.

* **Boris Cherny on Prompt Ablation (Claude Code):**
  * In an interview mirrored in community records ([GitHub: colmarius/with-agents](https://github.com/colmarius/with-agents)), Claude Code creator Boris Cherny explained how Anthropic cut over 80% of Claude Code's system prompt during the Opus 5 release cycle.
  * As underlying foundational models acquire innate abilities, previous corrective prompting becomes counterproductive noise. Anthropic uses systematic ablation (removing system prompts entirely, then re-introducing instructions line-by-line against regression benchmarks).

---

### 3. Uncertainties, Nuances, and Unverified Reel Claims

* **Frequency of the 80% Cut:** The reel claims the Claude Code team cuts 80% of system prompts *every single time* a model is released. Primary notes indicate the >80% reduction was a specific milestone for the Opus 5 transition. What happens per-generation is prompt rewrites and ablation testing, not an automatic 80% compounding shrinkage.
* **Unverified Internal Harness Commands:** The interview transcript discusses an undocumented minimal mode (`CLAUDE_CODE_SIMPLE=1`) and custom prompt flags (`--system-prompt`) used internally by Anthropic engineers. *Label: Unverified / Undocumented.* Do not rely on them in standard production environments without official Anthropic documentation.
* **Engagement Funnel:** The DM keyword requirement (`STIER`) is an engagement mechanism, not a proprietary repository or private tool release.

---

### 4. Prerequisites, Realistic Limits & Common Pitfalls

* **Prerequisites:** Modern agent-compatible harnesses (Claude Code, GitHub Copilot CLI, OpenAI Codex CLI, or Gemini CLI) and a project equipped with automated test suites (`pytest`, `vitest`, `cargo test`, etc.).
* **Limits of Skills:** Skills cannot compensate for absent unit tests, static typing, or undefined domain requirements. If the model has no feedback mechanism, a structured skill will still generate broken code.
* **Common Pitfalls:**
  * *Prompt Sedimentation:* Retaining legacy instructions in `CLAUDE.md` or `AGENTS.md` intended to patch weaknesses of older model generations.
  * *Monolithic Skill Files:* Writing 300-line prompt files containing instructions, reference docs, and styling rules in one context block.
  * *Blind Vibe Delegation:* Accepting agent diffs without inspecting edge cases, architectural coherence, or test assertions.

---

### 5. Command Reference

#### Verified Installation & Usage Commands
*Documented in [mattpocock/skills](https://github.com/mattpocock/skills):*

```bash
# Claude Code
claude plugin install mattpocock-skills@claude-plugins-official

# Codex CLI
codex plugin marketplace add mattpocock/skills
codex plugin add mattpocock-skills@mattpocock

# GitHub Copilot CLI
copilot plugin marketplace add mattpocock/skills
copilot plugin install mattpocock-skills@mattpocock

# Gemini CLI
gemini skills install https://github.com/mattpocock/skills.git --path skills/engineering
gemini skills install https://github.com/mattpocock/skills.git --path skills/productivity

# Generic Agent / Editable files
npx skills@latest add mattpocock/skills -a <agent>
npx skills@latest update
```

*Documented in transcript mirror repo [colmarius/with-agents](https://github.com/colmarius/with-agents):*

```bash
npm ci
npm run build
npm test
```

#### Unverified Commands from Reel Dossier
*Do not execute in production without verification:*
* `export CLAUDE_CODE_SIMPLE=1` *(Unverified internal environment flag)*
* `claude --system-prompt <file>` *(Unverified CLI option)*

---

### 6. Reusable Prompt: The Skill & Steering Ablation Audit

Use this prompt inside your coding agent to audit your existing `CLAUDE.md`, `AGENTS.md`, or custom skills against Pocock's and Cherny's criteria:

```markdown
You are auditing our repository's steering files and custom agent skills against Pocock's Skill Checklist and Cherny's Ablation Discipline.

Input to inspect: [Insert path to CLAUDE.md, AGENTS.md, or SKILL.md]

Perform the following evaluation:
1. INVENTORY: Identify each rule, instruction, or contextual constraint.
2. NO-OP & SEDIMENT IDENTIFICATION: Flag rules that modern flagship models follow natively (e.g., standard formatting, basic syntax reminders) or rules designed for previous model generations.
3. TRIGGER & STRUCTURE: Is this file lean (<80 lines)? Can domain explanations, templates, or references be pushed behind pointers into a docs/ or references/ directory?
4. DELETION TEST RECOMMENDATION: For each flagged line, specify the precise risk if deleted and propose a minimal 3-step test to verify if the model regresses without it.

Output a streamlined draft reducing total line count by at least 30%, retaining only verifiable behavioral constraints and project-specific invariants.
```

---

### 7. Concrete Implementation Steps

1. **Baseline Snapshot:** Archive your repository's existing steering files (`CLAUDE.md`, `.cursorrules`, or skill manifests).
2. **Run the Ablation Test:** Temporarily clear all non-essential instructions, leaving only test runners and strict safety constraints. Execute 5 standard development tasks.
3. **Re-add by Failure:** Only reintroduce directives when the model repeatedly makes a specific, verifiable mistake across standard evaluation runs.
4. **Adopt Modular Skills:** Install standardized skills via official package managers (`claude plugin` or `npx skills`) rather than copying raw Markdown blocks across repositories.

## Original sources
- https://www.instagram.com/reel/DeCZn6JMmYf/