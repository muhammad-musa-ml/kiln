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

---

## Decisions taken

| # | Decision | Why |
|---|---|---|
| D1 | Reels are downloaded by watching the network for `video/mp4` and stripping Instagram's `bytestart`/`byteend` params, not by reading `video.src` | `video.src` is a `blob:` URL that Playwright refuses. Measured: the stripped URL returns a playable mp4 with a valid `ftyp` box. |
| D2 | Extraction runs on full `gemini-3.8-flash` first, never on a `-lite` rung | Measured: the lite tier is what shipped every thin entry. 3.8-flash is available on this key. |
| D3 | Every model in a ladder must clear a quality floor. Models that cannot are removed from the config and the picker, not kept as a weak fallback | Owner's instruction. A fallback that degrades the work is worse than no fallback. |
| D4 | Claude is the final backup. When no model clears the floor, the item is handed to the Claude session that runs the sync rather than filed thin | Owner's instruction. Running out of models is an acceptable outcome; shipping a bad read is not. |
| D5 | An attached message is a TASK, not metadata. Routing is on presence, not on whether it starts with an imperative verb | The `^`-anchored verb regex sent four of the owner's richest instructions to the wrong field. |
| D6 | Every enrichment schema gains a free-form field for answering the attached instruction | The fixed schemas had no slot for an answer, so compliance was structurally impossible. |
| D7 | The build queue no longer runs on a 9am schedule. It is offered on every sync, behind a question listing the projects and rough times, answered all / one / few / none | Owner's instruction, superseding the earlier "9am only" decision. |
| D8 | The queue question is one card listing every queued project numbered with an estimate, with a button per choice | Fits the question-card mechanism already built. Answers are read at the start of the next sync or by a manual run. |

---

## Phase 1 — Unblock. COMPLETE.

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

## Phase 2 — Model policy. COMPLETE.

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
- [x] **2.4 Claude as the final backup.** When every rung fails the floor, hand
      the item to the sync's Claude session rather than storing a thin read.

## Phase 3 — Honour the attached instruction. COMPLETE.

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

## Phase 4 — Deliver something

- [ ] **4.1 An artifact writer.** Kiln cannot produce a document. The only PDF
      writer binds carousel images (`acquire.py:341`). Two instructions asked
      for a PDF and neither could ever have worked.
- [ ] **4.2 Wire the grounded-research ladder.** Verified unreachable: the only
      `models.generate()` call sites are `reason`, `extract` and
      `extract_deep`. The `research` ladder with Gemini's search tool and a
      1024 thinking budget is dead config.
- [ ] **4.3 Surface artifacts** on the item and in the UI.

## Phase 5 — Queue consent gate (supersedes the 9am rule)

- [ ] **5.1** Builds are offered on every sync, not on a morning schedule.
- [ ] **5.2** Estimate the work and rough time per queued project.
- [ ] **5.3** Question card with all / one / few / none, answered from the UI.
- [ ] **5.4** Update the routine prompt and `README.md` to match.

## Phase 6 — The brain

- [ ] **6.1 A playbook store that accumulates.** Nothing learns today; the
      thirteenth reel on a topic gets the same three template queries as the
      first.
- [ ] **6.2 A fulfilment check.** Nothing anywhere asks whether the owner's
      request was answered. A processed item with an unanswered instruction
      falls out of every check permanently.
- [ ] **6.3 Sections with subsections.** The `tags` table is three columns with
      no parent or depth, and section names are validated against a closed list
      of eight. "to watch" worked by coincidence.

## Phase 7 — Coherence and proof

- [ ] **7.1 Full read-through** for contradictions between code, tests, README,
      the routine prompt and this file.
- [ ] **7.2 Re-fire the five stuck reels** and confirm they leave `inbox` with
      real titles and honoured instructions.
- [ ] **7.3 All suites green**, site rebuilt, audit clean, pushed.

---

## Open questions for the owner

**Q1. The free tier may not be enough for the quality you asked for.**
Measured today: `gemini-3.1-pro-preview` and every grounded-search rung come
back `429 ... quota metric generate_content_free_tier_input_token_count`.
That is a token budget, not a request count, and carousels and video eat it
fast: one reel alone was ~10k input tokens. The flash rungs still answer, so
nothing is blocked, but the pro rung and live web research are effectively
unavailable on a free key. Enabling billing would make the whole ladder real.
Your call, since it costs money. Nothing is waiting on the answer.

**Q2. Thinking budget for the deep read is still 0.** The comment in
`config.py` says thinking was measured to make extraction *worse* because the
model reasons instead of transcribing. That measurement predates the deep
ladder now also being the one that has to follow an attached instruction,
which is reasoning rather than transcription. I have not changed it, because
overriding a recorded measurement on a hunch is how the original problem got
made. Worth one measured A/B when quota allows.

---

## Session log

### 2026-09-24
- Diagnosed the run. Fourteen issues found across acquisition, instruction
  handling, model policy and architecture. Reel fix proven by hand end to end.
- This file created. Work starting at Phase 1.
