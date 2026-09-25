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
| D15 | On the queue card, "all" means every project the card listed | A job queued after the card went up waits for the next card rather than riding in on an answer given before it existed. |
| D16 | The published page names no AI vendor | It named none before this work. The follow-up is called "the follow-up" on the page; the README still names Claude where it is a dependency, as it already named its other providers. |

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

- [~] **4.1 An artifact writer.** Kiln cannot produce a document. The only PDF
      writer binds carousel images (`acquire.py:510`). Two instructions asked
      for a PDF and neither could ever have worked. Plan: Markdown or HTML in,
      PDF out through the Chromium that Playwright already installs, kept per
      item under `data/artifacts/<item id>/`. Being built by a helper agent
      (`kiln/artifacts.py`), rendering with JavaScript off and the network
      blocked, so a document cannot fetch anything while it is printed.
- [-] **4.2 Wire the grounded-research ladder.** Dropped, see D12. Measured
      unreachable on this key: 429 on the first grounded call of the day on
      every rung while plain calls answer. The dead `research` ladder comes out
      of the config and the picker instead of staying as config nothing can use.
- [~] **4.3 Surface artifacts** on the item and in the UI, locally and on the
      published site, and make the leak audit read them. Also found: the
      answer to an attached instruction (3.4) is stored but shown nowhere,
      not in the UI and not on the site. Built: one function
      (`publish.followup`) feeds the item drawer locally and on the site, so
      the two cannot drift; files download from both; the audit now reads the
      text inside every PDF and fails if any sentence of an instruction shows
      up in the build. Not yet looked at in a browser.
- [~] **4.4 The free models say what they could not do.** Every enrichment
      schema gains `followups` (a next step that would finish the job, and
      what stopped the model doing it) and `could_not`. Owner's words: the
      models should know to check this and return it where possible.
      Built in `enrich.py` (on every enrichment, asked or not) and
      `extract.py` (`could_not` on the read, kept across both passes).
- [~] **4.5 One place that runs Claude headless** (`kiln/claude_cli.py`):
      safe and restricted mode, model and effort per call, JSON schema output,
      timeouts, usage-limit detection, and the Fable refusal (D10, D13). Written.
- [~] **4.6 The planner.** `claude-opus-5` at `max` effort reads what the free
      models produced and the owner's instruction, and returns a verdict
      (nothing to do, or work), the tasks, and the model and effort for each.
      Written in `kiln/brain.py`. A refused plan goes back once with the
      reasons (a Fable model, an unknown item, a circle of dependencies...).
- [~] **4.7 The executor.** Runs the plan (independent tasks in parallel),
      then a final assembly step, checks the result against the contract,
      stores it on the item and renders any documents through 4.1. Written.
      Running out of Claude usage part way leaves the item "blocked" and it is
      picked up on the next sync; that does not count as a failure.
- [~] **4.8 Wiring.** A stage in `daily.py` right after the inbox, the same
      follow-up after a localhost add or re-fire, and a visible "Claude is
      working on this" state in the UI. Written. The sync is six stages now.
- [~] **4.9 The ask rule for unreadable items** (D11). Pending briefs are
      printed by the sync, raised as one question card, and read by Claude
      on a yes. Written; "wait" clears the card and the free models retry.

## Phase 5: Queue consent gate (supersedes the 9am rule)

Backend built by a helper agent and re-run here: `test_queue_gate.py` 87/87,
`test_ship.py` 66/66. `daily.py` rewired and `test_daily_commit.py` re-keyed
from the old 9am rule to this one: 23/23.

- [~] **5.1** Builds are offered on every sync, not on a morning schedule.
- [~] **5.2** Estimate the work and rough time per queued project. From the
      median of past builds (one so far, 37 minutes) and past publishes
      (none timed yet, so 30 minutes until one is).
- [~] **5.3** Question card with all / one / few / none, answered from the UI.
      A tick box per project, plus all and none. Not yet seen in a browser.
- [~] **5.4** Update the routine prompt and `README.md` to match. README done.
      The new routine prompt is drafted and goes live at the merge, because
      until then the scheduled run still has the five-stage script.

## Phase 6: The brain

- [~] **6.1 A playbook store that accumulates.** Nothing learns today; the
      thirteenth reel on a topic gets the same three template queries as the
      first. Plan: the planner writes short lessons after each piece of work,
      and both the planner and the free tier's search step read the ones that
      match the next item. Built: a `playbook` table. Lessons carrying a link
      are refused, so a post cannot plant one that rides into every later
      prompt.
- [~] **6.2 A fulfilment check.** Nothing anywhere asks whether the owner's
      request was answered. A processed item with an unanswered instruction
      falls out of every check permanently. Plan: every sync looks at every
      item with an instruction; unanswered or blocked ones go back to Claude,
      and answers that are only partial are named in the check with the reason.
      Built: `brain.needs_follow_up` picks the work each sync (anything with
      an instruction first), and `health.check_follow_ups` reports partial
      answers with their reason.
- [~] **6.3 Sections with subsections.** The `tags` table is three columns with
      no parent or depth, and section names are validated against a closed list
      of eight. "to watch" worked by coincidence. Plan: an open, two-level
      section tree, filed by the planner, shown as a tree in the sidebar.
      Built: a `sections` table, a `section` tag, filtering that includes
      subsections, the tree in the sidebar and on the site.

Found while building, and fixed in the same change:
- A failed read was never retried. `process_url` allowed it, but the inbox
  only hands over lines it has not seen. `pipeline.retry_failed` now does it
  each sync, three tries at most, six hours apart.
- A re-fire wiped the item's own tags, including the group tag that ties a
  link to the others on its line. That is how `4091b1ffc3d48ceb` fell out of
  the "to watch" set of seven.
- Search together with a filter came back empty: the SQL arguments were in
  the wrong order.
- The `/media/` route checked containment with a text prefix, which lets a
  sibling folder pass.

## Phase 7: Coherence and proof

- [~] **7.1 Full read-through** for contradictions between code, tests, README,
      the routine prompt and this file. Already found while orienting on
      2026-09-25, to be fixed in this pass:
      - README's "Models" section still describes the lite and local ladders.
        Fixed.
      - README says `pip install -r requirements.txt` and there is no such file.
        Being added with 4.1.
      - The routine prompt never mentions the Claude briefs (see 2.4). Drafted,
        live at the merge.
      - The sidebar's "free today" meter reads a retired lite model, and
        `models.health()` pings that model on every 30 second poll. Fixed: the
        meter sums the ladder models, and the health check reads the model's
        metadata (no quota) at most every five minutes.
      - `test_daily_commit.py` asserts the old 9am build rule. Re-keyed.
      The full pass still has to run once everything is in.
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
- Two live follow-ups on a copy of the data, with real Claude calls:
  - The roadmap image ("extract the links inside the image"). The planner
    (Opus 5, max) saw on its own that "alive" proves nothing for YouTube:
    a watch page answers 200 for any id, and ids are case sensitive. It sent
    two Sonnet workers to re-read the image and check each link. They found
    three of the seven ids misread by the free model (for example
    `T9arN5JKmL8` for `T9aRN5JkmL8`), proved it with YouTube's oEmbed (the
    misread id is a 404), and the answer lists all seven with title,
    channel and length. About four and a half minutes in all. It also
    wrote its first playbook lesson, about checking video ids that way.
  - The seven "to watch" videos. The planner made "To watch" with four
    types (Explainers, Hands-on courses, Tool deep dives, Talks and
    panels), filed all seven, and sent one Haiku worker to find the video
    an article pointed at without linking it.
- What those runs showed, and what changed because of them:
  - The wrong links stayed on the item marked live: the last step could add
    a link but not take one off, and the old merge compared links
    lowercased, so the corrected id counted as a duplicate of the wrong
    one. Added `drop_links`, and links are now compared exactly.
  - The answer's single line breaks ran together on the page and bare
    links were not clickable. The last step is now told to write Markdown
    links, and the page renders the stored Markdown each time it is shown
    rather than storing HTML once.
  - The seven videos came back "not asked", although I had asked. The
    last step is now told what filing the plan already did, and code sends
    back a "not asked" when there was an instruction.
- The two new audit checks were made to fail on purpose before being
  trusted. A planted Windows path inside a PDF was caught. A planted
  instruction was NOT caught at first, because in the raw JSON a quote is
  stored as `\"`; the check now compares parsed text in runs of eight
  words, and catches it.
- Tests: `test_brain.py` 101/101, `test_queue_gate.py` 87/87,
  `test_daily_commit.py` 23/23. Twelve deliberate breakages of the new code
  were each caught by the test meant to catch them.
