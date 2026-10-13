# Atomic Claude & Semantic Code Intelligence Research Guide

Researched 2026-10-12.

## 1. Overview & Verification Breakdown

Developer workflows in [Claude Code](https://claudecodeguide.dev/docs/workflows/stop-reexplaining-your-project) often suffer from a recurring 'search tax' where agents exhaust context tokens re-discovering project structure, grepping for call sites, and guessing build commands across fresh sessions. The open-source project [Atomic Claude](https://github.com/damusix/atomic-claude) proposes tackling this by moving codebase mapping into deterministic, offline artifacts.

### What the Reel Claims
- **Problem:** AI coding agents repeatedly grep files and misidentify call sites, wasting tokens across clean sessions.
- **Symbol Graph:** Running `atomic code index` parses code with Tree-sitter compiled to WebAssembly into a single local SQLite file (`.claude/.atomic-index/atomic.db`) across 31 languages.
- **Zero Overhead:** Operates offline without servers, accounts, or system dependencies; only updates changed files.
- **Precise Query verbs:** Provides file:line answers for callers, callees, and blast radius via `callers`, `callees`, and `impact`.
- **Database Lineage:** Indexes SQL files statically down to column-level lineage (stored procedures, temp tables, dbt models, Snowflake tasks, and embedded SQL in 20 languages) without connecting to live databases.
- **Evaluator-Optimizer Workflow:** Enforces a test-first implementer and fresh-context reviewer loop alongside auto-generated wikis.

### What Today's Official Sources Confirm
- **Static WASM Parsing:** According to [code-intel.md](https://github.com/damusix/atomic-claude/blob/main/docs/reference/code-intel.md), Tree-sitter grammars are compiled to WebAssembly and run inside an embedded engine without CGO. Coverage includes 31 languages (23 tree-sitter, 5 regex including SQL, 3 file-level) and 23 web framework route resolvers.
- **Local Storage & Offline Operation:** Indexes store locally in `<project>/.claude/.atomic-index/atomic.db` (gitignored). CLI queries operate without network connectivity, model calls, or API keys.
- **CLI Surface:** Verified query verbs documented in [code-intel.md](https://github.com/damusix/atomic-claude/blob/main/docs/reference/code-intel.md) include `index`, `sync`, `status`, `search`, `callers`, `callees`, `impact`, `node`, `files`, `affected`, `explore`, `mcp`, and `comments`.
- **Embedded SQL Extraction:** Confirmed in [code-intel.md](https://github.com/damusix/atomic-claude/blob/main/docs/reference/code-intel.md); supports DDL/DML in string literals across 20 host languages without database connections.
- **Subagent Maker-Checker Separation:** Confirmed in [workflow.md](https://github.com/damusix/atomic-claude/blob/main/docs/reference/workflow.md); subagents query the graph directly via `atomic code ... --json` and fall back to `sg`/`grep` if the database is missing.
- **External Validation:** Independent architectural assessment in [rjwalters/loom Issue #5844](https://github.com/rjwalters/loom/issues/5844) confirms that the dual-scope persistent wiki, symbol graph, and maker/checker separation address key cold-start agent bottlenecks.

### What Remains Uncertain or Unverified
- **Unquantified Token Savings:** The reel's assertion that 'the loop spends its tokens on the change' lacks published comparative token telemetry or standardized SWE-bench style evals.
- **System Independence Caveats:** While the `atomic` binary has no CGO dependency, the complete toolchain requires `git 2.30+`, GitHub CLI (`gh`), a POSIX shell (`bash`/`zsh` with standard utilities), Node.js 18+, and the `@anthropic-ai/claude-code` CLI with a paid Anthropic plan or API key per [install.md](https://github.com/damusix/atomic-claude/blob/main/docs/guides/install.md).
- **Maturity & Edge-case Handling:** With under 100 stars and solo maintainership, complex grammar parsing edge cases (e.g., dynamic SQL via `EXEC(@sql)` or complex Vue/Svelte bindings) can lead to unresolved edges or partial parses.

---

## 2. Verified Tooling & Commands

### Prerequisites
- POSIX shell (`bash` or `zsh`) with `grep`, `sed`, `awk`, `find`, and `jq`
- `git` 2.30+ and GitHub CLI (`gh` authenticated)
- Node.js 18+ with Claude Code installed: `npm install -g @anthropic-ai/claude-code`
- Valid `ANTHROPIC_API_KEY` or an authenticated Pro/Team/Max Claude subscription
- Windows users must operate within WSL2 (native cmd/PowerShell is unsupported per [install.md](https://github.com/damusix/atomic-claude/blob/main/docs/guides/install.md))

### Official Atomic Claude Installation & Verification
```bash
# Download and install the atomic binary to ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/damusix/atomic-claude/main/install.sh | bash

# Wire artifacts into ~/.claude/ and configure the session hook
atomic claude install

# Run diagnostic health check
atomic doctor
```

### Verified Code-Intelligence Workflows
```bash
# Run from repository root to build the SQLite symbol graph
atomic code index

# Inspect call sites from parsed AST (not text matches)
atomic code callers chargeCard

# Inspect callees with recursion depth
atomic code callees validateToken --depth 2

# Calculate structural blast radius before edits
atomic code impact --depth 2 PaymentService

# Incrementally update index after modifying code
atomic code sync

# Natural-language structural context discovery
atomic code explore "how does session refresh work"

# CI affected-test selection
atomic code affected --json $(git diff --name-only main...HEAD)
```

### Alternative Semantic Indexing ([Serena](https://github.com/oraios/serena))
For compiler-grade type and reference accuracy in typed ecosystems, Serena leverages Language Server Protocol (LSP) daemons rather than Tree-sitter AST queries:
```bash
# Install Serena via uv (official docs method; avoid MCP marketplaces)
uv tool install -p 3.13 serena-agent

# Initialize with default LSP backend
serena init
```

---

## 3. Architectural Comparisons

| Capability | Atomic Claude ([damusix/atomic-claude](https://github.com/damusix/atomic-claude)) | Serena ([oraios/serena](https://github.com/oraios/serena)) | Native CLAUDE.md ([Claude Code Guide](https://claudecodeguide.dev/docs/workflows/stop-reexplaining-your-project)) |
| :--- | :--- | :--- | :--- |
| **Underlying Engine** | Tree-sitter WASM grammars + regex extractors | LSP language servers or JetBrains IDE plugin | Text markdown instruction files |
| **Storage** | Local SQLite (`.claude/.atomic-index/atomic.db`) | Local project workspace config / in-memory | Committed markdown (`CLAUDE.md`) |
| **SQL / Data Lineage** | Column-level lineage, dbt models, Snowflake tasks, embedded SQL strings | None (focused on code language ASTs) | Manual schema documentation notes |
| **Dynamic Dispatch** | Blind to reflection, runtime DI, dynamic metaprogramming | Resolves compiler-level types, inheritance hierarchies | None |
| **Offline Usability** | 100% offline local binary query surface | 100% offline local LSP daemons | Static context read by LLM |
| **Agent Integration** | Native Claude Code slash commands (`/atomic-plan`, `/autopilot`) + MCP | Model Context Protocol (MCP) compatible with any client | Preloaded into system prompt context |

---

## 4. Realistic Limits & Common Mistakes

1. **Assuming AST Graphs Catch Dynamic Execution:** Tree-sitter extracts syntax trees, not runtime symbols. Metaprogramming (Ruby on Rails, Django dynamic model properties, Spring dependency injection) will yield missing edges. In heavily dynamic code, supplement with [Serena](https://github.com/oraios/serena) or integration test suites.
2. **Stale Index Drift:** While `atomic code sync` is incremental and fast, failing to sync before a reviewer pass causes the agent to query an obsolete graph. Keep `atomic code sync` in your pre-review hooks.
3. **Bloated Root Rules:** As highlighted in [Claude Code Guide](https://claudecodeguide.dev/docs/workflows/stop-reexplaining-your-project), injecting entire system specifications into static markdown files burns 80-200+ tokens on every single interaction. Use persistent index files and targeted subagent exploration (`atomic code explore`) rather than inflating `CLAUDE.md`.
4. **Uncommitted Graph Files:** Never commit `.claude/.atomic-index/atomic.db`. Ensure `.gitignore` ignores the directory to avoid merge conflicts and bloated git history.

---

## 5. Reusable Claude Code Audit & Indexing Prompt

Use this prompt in any repository to configure baseline memory and evaluate static code-intel coverage:

```markdown
Act as a code-intelligence systems architect. Audit this repository for agent session context efficiency.

1. Inspect the directory layout, package managers, and configuration files.
2. Check if CLAUDE.md exists. If absent or exceeding 150 lines, draft an optimized CLAUDE.md under 80 lines specifying:
   - Project purpose & runtime stack
   - Build, lint, and test commands
   - Strict conventions and 'never-do' rules
3. Evaluate whether our codebase benefits from an AST symbol graph (e.g., Atomic Claude) or an LSP semantic server (e.g., Serena):
   - Count primary languages, presence of embedded SQL, and presence of dynamic metaprogramming.
   - Identify top 3 cross-cutting functions and identify their call sites via grep vs structural syntax.
4. Output an actionable context maintenance plan with zero fabricated commands.
```

## Original sources
- https://www.instagram.com/reel/DeNJmVuDpx_/