# Optimizing Claude Code: Verifying Hidden Settings, CLI Workflows, and Eval Loops

Researched 2026-10-12.

# Claude Code Configuration & Optimization Guide

### Overview & Context
This research guide analyzes optimization techniques presented in the tutorial video [AI LABS Dossier](https://youtube.com/watch?v=i6Q7bXnWGlM) against official references, including the [Claude Code Setup Guide](https://code.claude.com/docs/en/setup), the [Terminal Guide](https://code.claude.com/docs/en/terminal-guide), and community references such as the [claude-code-setup-guide repository](https://github.com/AlexandrG539/claude-code-setup-guide).

---

## 1. What the Reel Claims
The video outlines a series of performance, permission, and context-reduction techniques:
* **Interactive Initialization**: Setting `CLAUDE_CODE_NEW_INIT=1` prior to executing `claude` replaces static codebase scanning with an interactive interrogation regarding deployment and workflow standards.
* **Migration Commands**: A claimed `/import [agent]` command migrates setup files, instructions, and MCP configs directly from tools like Cursor or Codex.
* **Auditing & Pruning**: Claims `/claude-api prompt-audit` audits instructions in `CLAUDE.md`, and `/skill-doctor` (plus `/skills` sorted by `t`) detects context-draining custom skills.
* **Context & Tool Suppression**: Disabling connectors via `disableClaudeAiConnectors: true` and UI artifacts via `enableArtifact: false` in `~/.claude/settings.json` frees context window capacity.
* **Evals & Optimization**: Uses `/claude-api build-eval` and `/claude-api hillclimb` to score and iteratively improve API-driven applications against test splits.
* **Multi-Session Orchestration**: Commands such as `/branch`, `/fork`, `/subtask`, and `/list-agents` allow background task isolation and cross-agent peer messaging.

---

## 2. What Official Sources & Specifications Confirm

### Verified System Requirements & Core Commands
According to the [Claude Code Setup Docs](https://code.claude.com/docs/en/setup):
* **Operating Systems**: macOS 13.0+, Windows 10 (1809+), Ubuntu 20.04+, Debian 10+, Alpine Linux 3.19+.
* **Account Requirements**: Pro, Max, Team, Enterprise, or Console account (the free `claude.ai` web tier does **not** include Claude Code access).
* **Core Diagnostics**: `claude doctor` provides read-only verification of installation integrity, PATH configuration, and JSON settings validity.

### Verified Configuration Settings & Flags
Cross-referencing the video against the [claude-code-setup-guide](https://github.com/AlexandrG539/claude-code-setup-guide):
* **Pre-Launch Environment Variables**: Running `CLAUDE_CODE_NEW_INIT=1 claude` triggers the multi-phase guided `/init` flow.
* **Permission Reduction**: Running `/fewer-permission-prompts` inspects command history to propose pre-approved read-only operations for the project-level allowlist.
* **Session Model Pins & Subagents**: Pinning subagent behavior via environment variables in `settings.json` (`CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`) enforces lightweight execution profiles for delegatable tasks.
* **Session Separation**: Since v2.1.212+, `/fork` launches an independent background process, while `/subtask` provides subagent delegation with inherited context, and `/branch` maintains an in-session alternate line.
* **Context Suppression**: The keys `disableClaudeAiConnectors: true` (disabling claude.ai MCP auto-loading) and `enableArtifact: false` are functional settings keys in modern Claude Code releases.

---

## 3. Discrepancies, Nuances & Uncertain Claims

* **Migration `/import` Command (*Unverified*)**: Neither official setup docs nor community indices list a native `/import` command for migrating Cursor/Codex configs. This is suspected to be a feature of external tooling or a custom local skill. Verify via `/help` prior to execution.
* **Prompt Audit Conflation**: The reel suggests `/claude-api prompt-audit` reviews project `CLAUDE.md` files. In reality, `/claude-api` subcommands target application code calling the Anthropic SDK. Auditing repository instructions and configuration hygiene is handled by `/doctor prompt-audit` (or alias `/checkup prompt-audit`). Running `/claude-api` on non-SDK code returns empty findings.
* **Exact Settings Keys (*Unverified / Draft Syntax*)**: Specific settings referenced in spoken transcripts - such as `"show clear context on plan exit"`, `"plans directory"`, and `"show thinking summaries"` - lack documented schema validation in official references. Avoid adding non-standard keys to `~/.claude/settings.json` without verifying them against `claude doctor` warnings.
* **Interactive Timeout Behavior**: `askUserQuestionTimeout: "60s"` auto-advances multiple-choice `AskUserQuestion` dialogs, but it **never** auto-approves destructive shell permissions or plan mode exits.

---

## 4. Practical Implementation Workflow

### Prerequisites
* Ensure a compatible runtime (macOS 13+, Ubuntu 20.04+, or Windows 10+ with Git Bash or PowerShell) per the [Setup Docs](https://code.claude.com/docs/en/setup).
* Verify current CLI status:
```bash
claude --version
claude doctor
```

### Safe Configuration Tuning (`~/.claude/settings.json`)
```json
{
  "disableClaudeAiConnectors": true,
  "enableArtifact": false,
  "askUserQuestionTimeout": "5m",
  "env": {
    "CLAUDE_CODE_SUBAGENT_MODEL": "haiku",
    "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"
  }
}
```

### Operational Slash Commands (Session-level)
* Run `/doctor prompt-audit` to diagnose outdated guidelines or contradictory paths.
* Run `/fewer-permission-prompts` to generate safe read-only allowlists.
* Run `/skills` (press `t`) or `/skill-doctor` to observe per-turn context overhead.

---

## 5. Reusable Prompt Template

```text
Perform a structured health check and context audit of this repository's Claude Code setup:
1. Inspect CLAUDE.md and report any rules that are either redundant (already detectable from package manifests) or advisory formatting rules that belong in pre-commit hooks instead.
2. Verify the permissions allowlist and check if any non-read-only commands are improperly set to auto-allow.
3. Output a summarized report of recommended diffs without modifying files until approved.
```

## Original sources
- https://youtube.com/watch?v=i6Q7bXnWGlM