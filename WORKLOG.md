# Kiln overhaul, September 2026

Why this file exists: the work below is long enough to cross several sessions,
and the owner needs to see at a glance what is done, what is left, and what
turned up along the way. It is updated as work happens, not at the end.

Status marks: `[ ]` not started, `[~]` in progress, `[x]` done and verified,
`[!]` blocked or needs a decision, `[-]` dropped with a reason.

---

## Where this came from

The 2026-09-24 run produced thin entries, ignored the instructions attached to
the links, and failed on every reel. The investigation that followed found
three independent faults stacked on each other, not one. The models were never
the problem: a reel rescued by hand and fed to the same model tier returned 18
company names, the on-screen section headers and a summary of the speech.

Full diagnosis with evidence is in the session transcript; the numbered issues
below carry the file and line where each was proven.

On 2026-09-25 the owner added a rule that reshapes phases 4 to 6: the free
models do what they can, and Claude does the rest automatically (D10 below).

---

## Decisions taken

| # | Decision | Why |
|---|---|---|
| D1 | Reels are downloaded by watching the network for `video/mp4` and stripping Instagram's `bytestart`/`byteend` params, not by reading `video.src` | `video.src` is a `blob:` URL that Playwright refuses. Measured: the stripped URL returns a playable mp4 with a valid `ftyp` box. |
| D2 | Extraction runs on full `gemini-3.8-flash` first, never on a `-lite` rung | Measured: the lite tier is what shipped every thin entry. 3.8-flash is available on this key. |
| D3 | Every model in a ladder must clear a quality floor. Models that cannot are removed from the config and the picker, not kept as a weak fallback | Owner's instruction. A fallback that degrades the work is worse than no fallback. |
| D4 | Claude is the final backup. When no model clears the floor, the item is handed to Claude rather than filed thin | Owner's instruction. Running out of models is an acceptable outcome; shipping a bad read is not. How Claude gets it is D11. |
| D5 | An attached message is a TASK, not metadata. Routing is on presence, not on whether it starts with an imperative verb | The `^`-anchored verb regex sent four of the owner's richest instructions to the wrong field. |
| D6 | Every enrichment schema gains a free-form field for answering the attached instruction | The fixed schemas had no slot for an answer, so compliance was structurally impossible. |
| D7 | The build queue no longer runs on a 9am schedule. It is offered on every sync, behind a question listing the projects and rough times, answered all / one / few / none | Owner's instruction, superseding the earlier "9am only" decision. |
| D8 | The queue question is one card listing every queued project numbered with an estimate, with a button per choice | Fits the question-card mechanism already built. Answers are read at the start of the next sync or by a manual run. |
| D9 | Gemini billing stays off | Owner: enable it only if no card or payment method is needed. Checked 2026-09-25 on Google's billing page: the paid tier needs a payment method and a prepayment (minimum $5), and the $300 Cloud trial credit cannot pay for Gemini API use on accounts opened after 2026-03-02. So it was left alone. |
| D10 | The free models do what they can. Anything that can be improved, anything they suggest but cannot do themselves, and any part of an attached instruction they cannot do, Claude then does automatically, without asking. A planner on `claude-opus-5` at `max` effort decides what to do and how, and which model does each piece (Opus 5, Opus 5.5, Sonnet 5 or Haiku 4.5, at any effort level). Never Fable. The final result is what the site and localhost show | Owner's instruction, 2026-09-25. The Fable ban is enforced in code, not only in the prompt. |
| D11 | When no free model can read an item at all, Kiln asks first (a question card), and Claude does the read only on a yes | Owner, 2026-09-25: that case asks, while the D10 case never asks. |
| D12 | The grounded-research ladder is retired rather than wired (was 4.2) | Measured 2026-09-25: the first grounded call of the day on 3.8, 3.7 and 3.5 flash all came back 429, while a plain call on the same key answered. With billing off (D9) nothing makes it answer. Free research stays on Kiln's own search and fetch; research past that is Claude's job under D10. |
| D13 | Claude workers run headless in safe mode and restricted mode, with no shell | Measured: a plain `claude -p` loads about 183k tokens of this machine's own setup on every call; safe mode brings that to 2k to 5k (about 14k with tools). Restricted mode keeps file writes inside the worker's own folder: a write outside it was refused and no file appeared. |
| D14 | The planner decides and Python runs the plan | Code checks every plan before anything runs: allowed models and effort levels only, known tool kits, no cycles, a cap on tasks. A prompt can be talked around; a check in code cannot. |

---

## Phase 1: Unblock. COMPLETE.

- [x] **1.1 Reel download** (`kiln/acquire.py`). DONE. mp4 responses are
      captured via `page.on("response")`, `bytestart`/`byteend` stripped, the
      whole asset refetched. Picture and sound arrive as separate renditions
      and are muxed with ffmpeg. Measured end to end on `/reel/DdphNPwqFbl/`:
      12.7 MB, vp9 + aac, 37.06s against the 37.07s the page reports.
      Carousels re-checked and unaffected.
- [x] **1.2 Stop swallowing acquisition failures** (`acquire.py`). DONE. The
      real reason is recorded and surfaced instead of one sentence covering
      three different causes. Found and fixed alongside: OpenGraph serves no
      tags at all for a `/reel/` url, so every reel also lost its caption,
      owner and date. Those are read off the open page now, and the caption
      is where the company names and links live.
      Pinned by `scripts/test_reel_media.py` (16 checks).
- [x] **1.3 Failed items must be retryable** (`pipeline.py:177` sets
      `processed_at` on the failure path; `pipeline.py:141` then skips forever).
- [x] **1.4 A 429 must not burn the day** (`models.py:285`). Retry with backoff.
      Only burn on a repeated failure or an explicit daily-quota message.
      Measured: one burn wrote `450` into the ledger on a day with 2 real calls.
- [x] **1.5 Context-window guard** (`models.py:346`, `num_ctx: 16384`). Measured
      `in=16254 out=130` and `in=16264 out=120`, both exactly 16384. Cap images
      per call, raise the window, and reject any result where in+out equals the
      window.
- [x] **1.6 An empty read must not file as a success** (`pipeline.py:222`). A
      clipped summary satisfied the `or`, so a 0-section, 0-link, 0-entity read
      of an 11-slide carousel was filed `triage`/`reference` with no error.

## Phase 2: Model policy. COMPLETE.

- [x] **2.1 Best-first ladders.** `gemini-3.8-flash` heads extraction.
      Confirmed available on this key alongside 3.7, 3.6, 3.5 and
      `gemini-3.1-pro-preview`.
- [x] **2.2 Define and enforce the quality floor.** A read of a multi-slide post
      that returns no sections, no on-screen text and no links has failed,
      whatever the model said.
- [x] **2.3 Remove sub-floor models** from `config.LADDERS`, `data/models.json`
      and the picker UI. Known bad: `ollama:qwen3-vl-nothink` (shipped a
      0-section read), `ollama_cloud:qwen3-vl:235b-cloud` (retired upstream,
      returns HTTP 410).
- [x] **2.4 Claude as the final backup.** When every rung fails the floor, a
      brief is written instead of storing a thin read. Found on 2026-09-25:
      nothing ever picked those briefs up (the routine prompt never mentions
      them and `daily.py` never prints them). Closed by 4.9.

## Phase 3: Honour the attached instruction. COMPLETE.

- [x] **3.1 Route on presence, not phrasing** (`ingest.py:36`). Verified: all
      four `with message :` instructions landed in `user_note`, so `user_do`
      was empty and every consumer that acts on an instruction saw nothing.
- [x] **3.2 An instruction forces escalation** (`pipeline.py:186` currently
      reads `user_do` only and keyword-matches `"job"`). Verified:
      `extract_deep` has fired 0 times across all 13 items with metadata.
- [x] **3.3 The instruction drives the enricher and the search queries**
      (`enrich.py:177`, `enrich.py:214`). Measured: the job carousel was
      searched three times by its own clickbait headline and never once by a
      company name.
- [x] **3.4 Add the answer field to all four schemas** (`enrich.py` `_LEARN`,
      `_TOOL`, `_JOB`, `_GENERIC`).
- [x] **3.5 Frame the instruction as a task in both prompts** (`extract.py:83`
      says "What the person saving it said", which is reported speech).

## Phase 4: Deliver something

- [ ] **4.1 An artifact writer.** Kiln cannot produce a document. The only PDF
      writer binds carousel images (`acquire.py:510`). Two instructions asked
      for a PDF and neither could ever have worked. Plan: Markdown or HTML in,
      PDF out through the Chromium that Playwright already installs, kept per
      item under `data/artifacts/<item id>/`.
- [-] **4.2 Wire the grounded-research ladder.** Dropped, see D12. Measured
      unreachable on this key: 429 on the first grounded call of the day on
      every rung while plain calls answer. The dead `research` ladder comes out
      of the config and the picker instead of staying as config nothing can use.
- [ ] **4.3 Surface artifacts** on the item and in the UI, locally and on the
      published site, and make the leak audit read them. Also found: the
      answer to an attached instruction (3.4) is stored but shown nowhere,
      not in the UI and not on the site.
- [ ] **4.4 The free models say what they could not do.** Every enrichment
      schema gains `followups` (a next step that would finish the job, and
      what stopped the model doing it) and `could_not`. Owner's words: the
      models should know to check this and return it where possible.
- [ ] **4.5 One place that runs Claude headless** (`kiln/claude_cli.py`):
      safe and restricted mode, model and effort per call, JSON schema output,
      timeouts, usage-limit detection, and the Fable refusal (D10, D13).
- [ ] **4.6 The planner.** `claude-opus-5` at `max` effort reads what the free
      models produced and the owner's instruction, and returns a verdict
      (nothing to do, or work), the tasks, and the model and effort for each.
- [ ] **4.7 The executor.** Runs the plan (independent tasks in parallel),
      then a final assembly step, checks the result against the contract,
      stores it on the item and renders any documents through 4.1.
- [ ] **4.8 Wiring.** A stage in `daily.py` right after the inbox, the same
      follow-up after a localhost add or re-fire, and a visible "Claude is
      working on this" state in the UI.
- [ ] **4.9 The ask rule for unreadable items** (D11). Pending briefs are
      printed by the sync, raised as one question card, and read by Claude
      on a yes.

## Phase 5: Queue consent gate (supersedes the 9am rule)

- [ ] **5.1** Builds are offered on every sync, not on a morning schedule.
- [ ] **5.2** Estimate the work and rough time per queued project.
- [ ] **5.3** Question card with all / one / few / none, answered from the UI.
- [ ] **5.4** Update the routine prompt and `README.md` to match.

## Phase 6: The brain

- [ ] **6.1 A playbook store that accumulates.** Nothing learns today; the
      thirteenth reel on a topic gets the same three template queries as the
      first. Plan: the planner writes short lessons after each piece of work,
      and both the planner and the free tier's search step read the ones that
      match the next item.
- [ ] **6.2 A fulfilment check.** Nothing anywhere asks whether the owner's
      request was answered. A processed item with an unanswered instruction
      falls out of every check permanently. Plan: every sync looks at every
      item with an instruction; unanswered or blocked ones go back to Claude,
      and answers that are only partial are named in the check with the reason.
- [ ] **6.3 Sections with subsections.** The `tags` table is three columns with
      no parent or depth, and section names are validated against a closed list
      of eight. "to watch" worked by coincidence. Plan: an open, two-level
      section tree, filed by the planner, shown as a tree in the sidebar.

## Phase 7: Coherence and proof

- [ ] **7.1 Full read-through** for contradictions between code, tests, README,
      the routine prompt and this file. Already found while orienting on
      2026-09-25, to be fixed in this pass:
      - README's "Models" section still describes the lite and local ladders.
      - README says `pip install -r requirements.txt` and there is no such file.
      - The routine prompt never mentions the Claude briefs (see 2.4).
      - The sidebar's "free today" meter reads a retired lite model, and
        `models.health()` pings that model on every 30 second poll.
      - `test_daily_commit.py` asserts the old 9am build rule.
- [ ] **7.2 Re-fire the five stuck reels** and confirm they leave `inbox` with
      real titles and honoured instructions. Also re-fire the 11-slide job
      carousel (`0bcb16be366c6c1b`), whose stored read is empty and which
      carries a PDF request, and the older items whose enrichment failed
      against a local model that was not running.
- [ ] **7.3 All suites green**, site rebuilt, audit clean, pushed.

---

## Open questions for the owner

**Q1. Answered.** Billing needs a payment method, so it stays off (D9). The
free flash rungs keep doing the first pass; the pro rung and grounded search
stay out of reach, and Claude covers what they would have done (D10).

**Q2. Thinking budget for the deep read is still 0.** The comment in
`config.py` says thinking was measured to make extraction *worse* because the
model reasons instead of transcribing. That measurement predates the deep
ladder now also being the one that has to follow an attached instruction,
which is reasoning rather than transcription. I have not changed it, because
overriding a recorded measurement on a hunch is how the original problem got
made. Worth one measured A/B when quota allows. Less pressing now that the
answering itself moves to the enricher and to Claude.

---

## How the work is being done

Code changes are made on a branch in a separate worktree
(`.claude/worktrees/overhaul`, branch `overhaul`) against a copy of `data/`,
so the 9am and 9pm syncs keep running the last good version in the main
checkout. The branch is merged once a phase is tested. This file is only
edited in the main checkout, so it is always current where it is read.

---

## Session log

### 2026-09-24
- Diagnosed the run. Fourteen issues found across acquisition, instruction
  handling, model policy and architecture. Reel fix proven by hand end to end.
- This file created. Work starting at Phase 1.
- Phases 1 to 3 finished and committed (`fbef5dd`, `b2d6fdc`, `20d5689`,
  `fd0a8be`).

### 2026-09-25
- Pushed the four commits from the 24th.
- Baseline before any change: all seven suites green (actions 9/9,
  daily_commit 15/15, failed_links 20/20, inbox_parse no missing urls,
  reel_media 16/16, ship 66/66, slop 18/18).
- Owner's new rule recorded as D10 and D11, and billing settled as D9.
- Checked the Claude side before designing around it: `claude-opus-5`,
  `claude-opus-5-5`, `claude-sonnet-5` and Haiku 4.5 all answer, `--effort
  max` and `--json-schema` both work, and a sandboxed worker searched the web,
  read a slide image, wrote inside its folder and was refused outside it.
- Grounded search measured dead on this key (D12).
