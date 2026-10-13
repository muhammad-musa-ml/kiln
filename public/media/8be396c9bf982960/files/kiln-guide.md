# Claude Code Mods Architecture and Implementation Guide

Researched 2026-10-12.

# Claude Code Mods: Architectural Analysis and Implementation Guide

## 1. Executive Summary & Core Mechanics

As of October 2026, Claude Code version 2.1.287+ includes a native extensibility architecture referred to as **Mods**. Unlike Model Context Protocol (MCP) servers (which run out-of-process to supply tools) or system prompt instructions (skills), mods are TypeScript extensions running directly within the Claude Code client process. They listen to internal lifecycle events (such as `tool.call`, `session.start`, `turn.complete`, and `prompt.submit`), allowing developers to observe, modify, or block tool runs and render rich interactive UI elements across terminal panes and input bands.

---

## 2. Evidence Separation: Reel Claims vs. Official Documentation

### What the Reel Claims
In the [RoboNuggets walkthrough](https://youtu.be/lDrAZ1wAyVs), Jay E presents 9 mods spanning visual enhancements, sub-agent telemetry, cost controls, and safety checks:
- **Savvy Progress**: Custom progress bar and sub-agent tracker with pixel-art mascots.
- **Claude Skins**: Terminal transcript reskinning with 7 default themes.
- **You Should Know**: A purported Anthropic built-in mod running a secondary monitoring agent.
- **Filetree**: Right-sidebar IDE-style file directory showing real-time file interactions.
- **Cache Tax**: Session warmers via `/keepwarm` to avoid prompt cache expiration penalties.
- **Blast Radius**: Command confirmation gate preventing destructive CLI actions.
- **Reflect**: In-session prompt monitoring saving feedback rules into `CLAUDE.md`.
- **Terminal Browser**: In-terminal Chromium preview using the Kitty graphics protocol.
- **Replay Theater**: Step-by-step diff reviewer for file edits.

### What Official & Repo Sources Confirm
- **Safety Gate & Diff Replay**: Anthropic's official [claude-code-playground repository](https://github.com/anthropics/claude-code-playground/tree/main/claude-code/mods) confirms both [`blast-radius`](https://github.com/anthropics/claude-code-playground/tree/main/claude-code/mods/blast-radius) and [`replay-theater`](https://github.com/anthropics/claude-code-playground/tree/main/claude-code/mods/replay-theater). Blast Radius halts risky bash calls (`rm -rf`, `git reset --hard`, database migrations) and renders Proceed/Cancel buttons. Replay Theater hooks `tool.call` to track file modifications and exposes a step-by-step diff pane.
- **Cache Tax Mechanics**: The [cache-tax repository](https://github.com/karanb192/cache-tax) confirms that prompt cache lifetimes differ by billing tier: subscription sessions default to 1 hour, whereas API/cloud sessions default to 5 minutes unless `promptCacheTtl: "1h"` is configured per [Anthropic Prompt Caching Docs](https://docs.claude.com/en/docs/build-with-claude/prompt-caching). The mod sends synthetic forks to refresh the cache before the expiration deadline.
- **UI Rendering Extensions**: Verified third-party plugins like [`claude-skins`](https://github.com/hellosverre/claude-skins) and [`claude-code-filetree`](https://github.com/data-goblin/claude-code-filetree) render custom views using Claude Code's terminal layout engine, requiring full-screen terminal modes (`/tui fullscreen`) and terminal widths >= 110-144 columns.
- **Reflect Dual Formats**: Documentation in [`claude-reflect`](https://github.com/BayramAnnakov/claude-reflect) confirms a Python hook version and a TypeScript `reflect-mod` that runs lightweight one-shot model evaluations on short prompts to update `CLAUDE.md` rules.

### What Remains Uncertain or Unverified
- **Built-in Status of "You Should Know"**: The reel claims Anthropic ships a built-in mod enabled via `/plugin enable cc-plugin-you-should-know@builtin`. This command is **unverified** in official documentation repositories. Treat this command as speculative until verified by official Anthropic plugin catalog updates.
- **Provider Anecdotes**: The creator's claim regarding "GAI" cost warnings for Kling video workflows is an unverified personal anecdote.
- **Sub-agent Cost Exactness**: Per [savvy-progress documentation](https://github.com/JohnnyVizz/claude-kit/tree/main/plugins/savvy-progress), reported token costs are static table estimates, not live Anthropic billing data.

---

## 3. Verified Installation & Operational Commands

*Note: Do not execute commands without verifying plugin sources. Mods run unsandboxed on your system.* 

### Anthropic Playground Samples (Verified from Source)
```bash
# Clone the official playground samples
git clone https://github.com/anthropics/claude-code-playground.git
cd claude-code-playground/claude-code/mods

# Validate and run Blast Radius for a single session
claude plugin validate ./blast-radius
claude --plugin-dir ./blast-radius

# Validate and run Replay Theater for a single session
claude plugin validate ./replay-theater
claude --plugin-dir ./replay-theater
```

### Verified Third-Party Marketplace Plugins
```bash
# Cache Tax (Prompt Cache Management)
claude plugin marketplace add karanb192/claude-code-mods
claude plugin install cache-tax@claude-code-mods

# Filetree Sidebar (Requires >=110 columns)
claude plugin marketplace add data-goblin/claude-code-filetree
claude plugin install filetree@claude-code-filetree

# Claude Skins (Themes and Cards)
claude plugin marketplace add hellosverre/claude-skins
claude plugin install skins@hellosverre-mods

# Reflect Mod (Self-learning memory)
claude plugin marketplace add bayramannakov/claude-reflect
claude plugin install reflect-mod@claude-reflect-marketplace
```

### Standalone Helper Tools
```bash
# Terminal Browser (Standalone CLI referenced by Zenbu Labs)
curl -fsSL https://terminal-browser.sh/install | bash
# or via Homebrew on macOS:
brew install terminal-browser
```

### Unverified Reel Commands (DO NOT RUN WITHOUT MANUAL CHECK)
- `claude update` *(Unverified syntax in docs; use your standard package manager update flow)*
- `/plugin enable cc-plugin-you-should-know@builtin` *(Unverified mod identifier)*

---

## 4. Technical Constraints, Gaps, and Pitfalls

1. **Zero Sandboxing Risk**: Mods run with the exact privileges of the host Claude Code process. A malicious mod can read local filesystem files, access environment variables, or execute outbound network requests. Always audit `hooks/register.tsx` or plugin entry points.
2. **UI Real Estate Contention**: Both Blast Radius and Cache Tax leverage the `AbovePrompt` rendering slot. When multiple mods request the prompt band simultaneously in narrow terminals (<144 columns), one mod may suppress another's buttons, potentially causing commands to stall or time out.
3. **Prompt Cache TTL Mismatch**: Cache Tax's 50-minute ping default assumes a 1-hour cache TTL (standard on Claude subscriptions). If using direct API keys or third-party gateways with a 5-minute cache TTL, keepwarm pings will fail to prevent cold cache penalties unless `promptCacheTtl: "1h"` is explicitly passed.
4. **Token Cost Creep**: Mods running background model calls (such as Reflect running one-shot Haiku calls on inputs, or second-agent overseers) consume billable tokens on every interaction.

---

## 5. Reusable Claude Code Prompt

Use this prompt inside Claude Code (v2.1.287+) to scaffold a verified local mod structure:

```text
I want to create a local, safe Claude Code mod using the official plugin-authoring hooks. 
Requirements:
1. Hook into `tool.call` to inspect calls to the `Bash` tool.
2. If the command contains destructive patterns (`rm -rf`, `git reset --hard`, `drop table`), intercept execution and prompt for explicit user confirmation in the AbovePrompt slot.
3. Provide fallback logging using `$.ui.log` if the terminal window is under 110 columns.
4. Avoid calling background LLMs; keep all evaluation deterministic.
Provide only the `plugin.json` manifest and `hooks/register.tsx` code ready for `claude plugin validate`.

## Original sources
- https://youtu.be/lDrAZ1wAyVs