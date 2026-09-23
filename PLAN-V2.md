# Kiln v2 — model control, Build-it, and a public site that cannot leak

Written 2026-09-23, after three research passes. Every limit quoted below was
read from a primary source or measured against this repo; the citations are in
the sections that use them.

---

## Context

Kiln today is a local Python app: a stdlib HTTP server, SQLite on disk,
Playwright driving a real browser, and a hard-coded model ladder in
`kiln/config.py`. Three things are wanted:

1. Control over which models run, which are backup, and the ability to add new
   API-based ones from the UI.
2. Anything installable or buildable should be *makeable* — via a copyable
   prompt, a local agent, or GitHub Actions — with a chat for follow-ups and
   optional push to GitHub.
3. It goes live on Vercel. Anyone may read. Nobody may write. No API key or
   personal data may be discoverable, "even through backend hacking or
   inspecting elements".

### The finding that decides the architecture

Two independent research passes landed on the same conclusion from different
directions:

- **Instagram blocks datacenter IP ranges at the ASN level.** The browser
  method in `kiln/acquire.py` works *because* it runs unauthenticated from a
  residential IP. On Vercel's `iad1` it returns the same 401s already measured
  from `instaloader`. This fails 100% in production while working perfectly in
  development.
- **The strongest security posture is to publish, not serve.** A backend with
  no secrets and no write routes cannot leak secrets or be mutated.

So Kiln splits in two, and the split is forced by physics, not preference.

| | **Kiln Local** (this machine) | **Kiln Public** (Vercel) |
|---|---|---|
| Runs | acquire · extract · enrich · build · install | nothing |
| Holds | every API key, the full DB, all media | **no secrets at all** |
| Writes | yes, full UI | **impossible — none exist** |
| Data | everything | a whitelisted public subset |

**Kiln Public is a static export.** Not a database with careful policies — a
folder of JSON and images. There is no connection string to leak, no RLS policy
to misconfigure, no service key to rotate. Research found 83% of real-world
exposures in this class trace to row-level-security misconfiguration; this
design has no RLS to misconfigure.

---

## What is broken today (verified in this repo)

| Issue | Where | Consequence |
|---|---|---|
| API key in the URL query string | `kiln/models.py:266` | Keys land in access logs, proxy logs, referrer headers, error traces |
| 5 write routes, zero auth | `kiln/server.py:142,163,172,180,193` | Anyone who reaches the port can mutate everything |
| `subprocess.run(shell=True)` | `kiln/server.py:240` | Remote code execution if ever exposed |
| Private columns in the same row as public ones | `kiln/store.py:46-59` | `user_note`, `user_do`, `cost_usd`, `pdf_path` one `SELECT *` from exposure |
| Job state in a module-level dict | `kiln/server.py:22` | Vanishes on restart; cannot survive a serverless instance |
| DDL on every connection | `kiln/store.py:116` | Harmless on SQLite, wrong against Postgres |
| Model ladder hard-coded | `kiln/config.py:105-142` | Cannot be changed without editing Python |

---

## Phase 1 — Model control

**Goal:** add, remove, enable, disable, reorder and test models from the UI,
including new API providers, with credentials that never leave this machine.

### 1.1 Provider registry — `kiln/providers.py` (new)

Four adapters cover essentially every model worth having:

| Adapter | Covers |
|---|---|
| `gemini` | Gemini (existing code, moved) |
| `ollama` | local + Ollama Cloud (existing code, moved) |
| `openai_compatible` | OpenAI, Groq, OpenRouter, DeepSeek, xAI, Together, Mistral, Fireworks, LM Studio, vLLM, llama.cpp — all speak `/v1/chat/completions` |
| `anthropic` | Claude (`/v1/messages`) |

Each adapter declares capabilities — `vision`, `video`, `json_mode`,
`thinking`, `streaming` — so the router can **skip a rung that structurally
cannot serve a request** instead of failing it. `kiln/models.py` already does
this for video; generalise it.

### 1.2 Configuration moves from code to data

`kiln/config.py` `LADDERS` becomes the *seed* for `data/models.json`, which the
UI owns thereafter:

```jsonc
{
  "providers": {
    "groq": { "adapter": "openai_compatible",
              "base_url": "https://api.groq.com/openai/v1",
              "key_ref": "groq"          // a REFERENCE, never the key itself
            }
  },
  "models": [
    { "id": "gemini-3.5-flash-lite", "provider": "gemini",
      "enabled": true, "capabilities": ["vision","video","json_mode"],
      "price_in": 0.30, "price_out": 2.50, "free_rpd": 450 }
  ],
  "ladders": {
    "extract": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "qwen3-vl:4b"]
  }
}
```

Keys live in `data/secrets.json`, encrypted at rest with Windows DPAPI
(`win32crypt.CryptProtectData`, machine+user scoped) and `chmod`-equivalent
ACLs. Gitignored, and **excluded from the export by construction** — the
exporter whitelists fields, so a new secret field can never accidentally ship.

### 1.3 Adding a model asks for everything, then proves it works

The "Add model" flow is a three-step wizard:

1. Pick provider (or "custom OpenAI-compatible" → base URL).
2. Paste key. **Nothing is saved yet.**
3. Kiln immediately fires a real test call — a 5-token completion, plus a
   1-pixel image if the model claims vision — and reports latency, cost, and
   what actually came back. Only a passing test saves the model.

This is the difference between "added a model" and "added a model that works".
It also auto-detects capabilities rather than trusting a checkbox.

### 1.4 UI

A **Models** panel in the rail: each task (`extract`, `extract_deep`,
`classify`, `research`, `reason`) shows its ladder as a reorderable list.
Rung 1 is labelled *primary*, the rest *backup*. Each row shows live health,
today's usage against its free budget, and measured median latency. A toggle
disables a model everywhere without deleting it.

---

## Phase 2 — Build it

**Goal:** anything installable or buildable becomes makeable, three ways.

### 2.1 Fix the brief first

`kiln/enrich.py` emits `scope` as one prose string. An agent given
"IN: … OUT: …" as a blob builds the wrong thing. Split it into
`scope_in[]` / `scope_out[]`, and render `milestones[].outcome` as an explicit
acceptance checklist. This single change does more for build quality than the
choice of agent.

### 2.2 Three targets

**(a) Copy the prompt — the default, and the one that always works.**
Assembles a complete, self-contained build prompt: scope in/out, pinned stack
with versions, milestones as acceptance criteria, README outline, and the
source links with their verified-alive status. One click to clipboard, drop it
in any chat. Zero infrastructure, zero cost, no account, never breaks.

**(b) Local agent.** Kiln asks *where* — a directory picker — then runs the
build there, streaming output into the chat. Optional `git init`, commit, and
push. This is also where install commands keep working after deployment, since
`/api/run` can never exist on Vercel.

**(c) GitHub Actions → pull request.** Kiln creates the repo, commits a
workflow using `google-github-actions/run-gemini-cli`, dispatches it, and
reports the PR URL. Free, works from anywhere, no machine needed. CI is a poor
chat surface, so follow-ups re-dispatch rather than continue a conversation —
stated plainly in the UI rather than pretended away.

*(Optional 4th, behind a setting: **Google Jules** — the only API that does
sandbox + agent + chat + auto-PR in one call, including a repoless mode that
returns a git patch with no repo needed. Free tier 15 tasks/24h. **Its key is
not `GEMINI_API_KEY`** — it comes from Jules' own settings page, so it is
opt-in with its own setup step, never assumed.)*

### 2.3 Chat

Server-sent events, not WebSockets — auto-reconnect, no proxy special-casing,
and every major LLM API already speaks it. One thread per item:

```
build_session   item_id · target · model · repo · pr_url · state
                brief_snapshot (the exact JSON sent, so re-runs are diffable)
build_message   role · content · created_at
```

Editing the brief opens a **new** session rather than mutating a running one —
agent sessions accumulate context and a mid-run prompt rewrite produces
confused behaviour.

### 2.4 GitHub auth

A **GitHub App** using the web application flow. Fine-grained permissions
(`administration: write`, `contents: write`, `metadata: read`), 8-hour user
tokens with refresh. Not device flow — GitHub's own docs warn it enables
remote impersonation phishing. Not a classic OAuth App — its `repo` scope is
all-or-nothing across every repository.

---

## Phase 3 — Public site that cannot leak

### 3.1 Export, don't serve

`kiln/publish.py` (new) produces `public/`:

```
public/
  index.html          the existing UI, read-only mode
  data/items.json     WHITELISTED fields only
  data/facets.json
  media/<id>/*.webp   slides
  media/<id>/*.pdf
```

**Whitelist, never blacklist.** The exporter names the fields that may ship;
anything new is private by default:

```python
PUBLIC_FIELDS = ("id", "url", "kind", "action", "title", "hook", "summary",
                 "owner", "posted", "slide_count", "topics", "links")
```

Never exported: `user_note`, `user_do`, `status`, `urgent`, `deadline`,
`cost_usd`, `error`, `media_dir`, `pdf_path` (replaced by an opaque media id),
`_meta` provenance, and the whole of `runs`, `actions_log`, `seen`, `quota`.

`enrich_json` is exported **field-by-field**, not wholesale — it currently
carries `_meta.attempts`, which contains model names and error strings, and
`error` values that can embed a URL with `?key=…` in them.

### 3.2 Why static beats a database here

| | Static export | Hosted DB + RLS |
|---|---|---|
| Credentials on Vercel | **none** | publishable key, at minimum |
| Ways to misconfigure | whitelist is one file | policies per table per operation |
| Cost | $0 | free tier that **pauses after a week idle** |
| Search | client-side over a few hundred items | server-side |
| Breach surface | a folder of JSON | a live database endpoint |

Search over a personal library is trivially fast client-side. If it ever
outgrows that, the upgrade is **Turso** — it *is* SQLite, so `FTS5` and `MATCH`
work unchanged, where Postgres would require rewriting search to `tsvector`
with different ranking and no `NEAR()`.

Media goes to **Cloudflare R2** (10 GB free, **zero egress**) rather than
through Vercel, because a Vercel function has a hard **4.5 MB** request/response
cap and the existing 13-slide PDF is already 4.6 MB — it would return
`413 FUNCTION_PAYLOAD_TOO_LARGE` today.

### 3.3 Local hardening (P0, before anything is published)

- Move the Gemini key from the query string into the `x-goog-api-key` header
  (`kiln/models.py:266`).
- Require a local bearer token on every write route; bind to `127.0.0.1` only.
- Re-validate the install allow-list server-side — already done, keep it, and
  make `/api/run` refuse to load unless `KILN_LOCAL=1`.
- Set a **Gemini project spend cap** in AI Studio. This is the control that
  turns a runaway loop from catastrophic into annoying.
- Migrate to a **restricted Gemini auth key** — since 2026-05-28 all new keys
  are service-account-bound and the API rejects unrestricted standard keys.

### 3.4 The launch test — five `curl`s that must all fail

Before going public, and re-run on every deploy:

1. Fetch every file under `public/` and grep for `AIza`, `sb_secret`, `sk-`,
   and the first 8 characters of each configured key → **zero hits**.
2. Grep the same files for `user_note`, `user_do`, `cost_usd`, `media_dir`,
   `C:\\Users` → **zero hits**.
3. `POST` to every former write route on the deployed origin → **404/405**.
4. Confirm `/api/run` does not exist in the deployment at all.
5. Diff `items.json` keys against `PUBLIC_FIELDS` → **exact match, no extras**.

This ships as `scripts/audit_public.py` and runs in CI, so the check cannot be
forgotten. A publish that fails it does not deploy.

---

## Phase 4 — The things not asked for, that matter

- **Budget guard.** Port `data/quota.json` into a hard pre-flight check that
  refuses a call projected to exceed a daily dollar cap, rather than reporting
  the overspend afterwards.
- **"What's public?" preview.** A toggle on any item showing precisely what a
  stranger sees. Security you can *look at* beats security you have to reason
  about.
- **Backfill.** 163 URLs already sit in `wa-pipeline/state/classified_urls.json`
  with 121 captions and 101 transcripts. Import them so tagging and search face
  real scale instead of one item.
- **Scheduled Drive sync.** Twice-daily pull of the `To-Do AI` inbox.
- **`gitleaks` pre-commit + GitHub push protection**, and `.gitignore` gains
  `.env*`, `*.db`, `data/secrets.json`.
- **Cost and provenance stay local.** The public site never reveals what
  anything cost or which model produced it.

---

## Order of work

Risk first, and something usable after every step.

| # | Step | Done when |
|---|---|---|
| 1 | Key → header; local auth token; `/api/run` gated behind `KILN_LOCAL` | `curl` without the token gets 401; key absent from all URLs |
| 2 | Provider registry + `models.json` + capability skipping | A Groq key added via UI runs an item end-to-end |
| 3 | Model panel UI: reorder, toggle, test, live health | Ladder reordered in the UI changes which model runs |
| 4 | Split `scope` into in/out; brief → build prompt | Copy-prompt output builds the project in a fresh chat |
| 5 | Build chat (SSE) + local agent target | A project is built in a chosen directory, streamed live |
| 6 | GitHub App + Actions target | A PR appears in a new repo from one click |
| 7 | `publish.py` whitelist export + R2 media | `public/` builds; `audit_public.py` passes |
| 8 | Deploy to Vercel; audit in CI | Live, read-only, five checks green |
| 9 | Backfill 163 items; scheduled Drive sync | Library at real scale, inbox pulled automatically |

Steps 1–3 deliver model control. 4–6 deliver Build-it. 7–8 deliver the public
site. Each is independently useful and independently revertable.
