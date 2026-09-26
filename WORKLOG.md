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
| D8 | The queue question is one card listing every queued project numbered with an estimate, with a tick box per project plus all and none | Fits the question-card mechanism already built. The answer is read when the next sync reaches its build queue (stage 4 of 6), or by a manual run. From a terminal: `python -m kiln.questions answer build-queue.queue some 1 3`. |
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
- [x] **2.2 Define and enforce the quality floor.** A read of a post with
      pictures or video that returns no sections and no on-screen text (for
      a video, no speech either) has failed, whatever the model said. Until
      the coherence pass it only covered two or more pictures, so a single
      image or a reel could pass with nothing in it; it covers any media now.
- [x] **2.3 Remove sub-floor models** from `config.LADDERS` and
      `data/models.json` (loading the registry now drops the ladder of any
      task the code no longer has and, when it does, the seeded models no
      ladder then uses; ones added by hand stay). There is no picker on the page;
      models are managed through the local `/api/models` routes. Known bad:
      `ollama:qwen3-vl-nothink` (shipped a 0-section read),
      `ollama_cloud:qwen3-vl:235b-cloud` (retired upstream, returns HTTP 410).
- [x] **2.4 Claude as the final backup.** When every rung fails the floor, a
      brief is written instead of storing a thin read. Found on 2026-09-25:
      nothing ever picked those briefs up (the routine prompt never mentions
      them and `daily.py` never prints them). Picking them up is 4.9.

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

- [x] **4.1 An artifact writer.** Kiln could not produce a document. The only
      PDF writer bound carousel images (`acquire.py:510`). Two instructions
      asked for a PDF and neither could ever have worked. Built in
      `kiln/artifacts.py` (`a063985`): Markdown or HTML in, PDF out through
      the Chromium that Playwright already installs, kept per item under
      `data/artifacts/<item id>/`, rendered with JavaScript off and the
      network blocked, so a document cannot fetch anything while it is
      printed. `test_artifacts.py` 125/125, and the live follow-up on the
      roadmap image produced a real PDF.
- [-] **4.2 Wire the grounded-research ladder.** Dropped, see D12. Measured
      unreachable on this key: 429 on the first grounded call of the day on
      every rung while plain calls answer. The dead `research` ladder comes out
      of the config and the picker instead of staying as config nothing can use.
- [x] **4.3 Surface artifacts** on the item and in the UI, locally and on the
      published site, and make the leak audit read them. Also found: the
      answer to an attached instruction (3.4) is stored but shown nowhere,
      not in the UI and not on the site. Built: one function
      (`publish.followup`) feeds the item drawer locally and on the site, so
      the two cannot drift; files download from both; the audit now reads the
      text inside every PDF and fails if eight words in a row of an
      instruction, or a whole note of five to seven words, show up in the
      build. A note under five words is not checked. `test_audit.py` plants
      each kind of leak in a throwaway copy. Seen on the live site on
      2026-09-25: the carousel's `ai-startup-jobs.pdf` is listed on the item
      and downloads (200, `application/pdf`, 117,296 bytes), and the drawer
      shows each follow-up's answer under "What the follow-up added".
- [~] **4.4 The free models say what they could not do.** Every enrichment
      schema gains `followups` (a next step that would finish the job, and
      what stopped the model doing it) and `could_not`. Owner's words: the
      models should know to check this and return it where possible.
      Built in `enrich.py` (on every enrichment, asked or not) and
      `extract.py` (`could_not` on the read, kept across both passes).
      Tested; not yet seen live, because no free model read anything on
      this code on 2026-09-25 (the quota was spent all day). First chance:
      the first sync after 02:00 here on 2026-09-26, when the quota resets
      (midnight Pacific).
- [x] **4.5 How the follow-up runs Claude headless** (`kiln/claude_cli.py`):
      safe and restricted mode, model and effort per call, JSON schema output,
      timeouts, usage-limit detection, and the Fable refusal (D10, D13).
      Written. The publish chain's reviewer (`ship.py`) and the claude build
      agent (`runner.py`) keep their own command lines with a narrow shell,
      because they install and test a project; the readme writer has file
      tools only. Used live by every follow-up on 2026-09-25 (the planner on
      `claude-opus-5` at max, workers on `claude-sonnet-5`). The usage-limit
      path is tested with a stub and has not happened live.
- [x] **4.6 The planner.** `claude-opus-5` at `max` effort reads what the free
      models produced and the owner's instruction, and returns a verdict
      (nothing to do, or work), the tasks, and the model and effort for each.
      Written in `kiln/brain.py`. A refused plan goes back once with the
      reasons (a Fable model, an unknown item, a circle of dependencies...).
      Live on 2026-09-25: it planned the six units of the sync that ended at
      13:06 and the Jarvis re-runs. The refused-plan path is tested.
- [x] **4.7 The executor.** Runs the plan (independent tasks in parallel),
      then a final assembly step, checks the result against the contract,
      stores it on the item and renders any documents through 4.1. Written.
      Running out of Claude usage part way leaves the item "blocked" and it is
      picked up on the next sync; that does not count as a failure. Live on
      2026-09-25: tasks ran in parallel and the final step stored answers and
      files (the carousel's PDF; three files on `0d895b2b9d4ca82d`). Running
      out of usage is tested, not seen live.
- [~] **4.8 Wiring.** A stage in `daily.py` right after the inbox, the same
      follow-up after a localhost add or re-fire (both off under
      `KILN_BRAIN=0`), and a visible "following up" state in the UI (D16).
      Written. The sync is six stages now. The sync stage is seen live (the
      sync that ended at 13:06 on 2026-09-25). The follow-up after a
      localhost add, and the UI's "following up" state, wait for a free
      model to read something first: the first sync after the quota resets.
- [~] **4.9 The ask rule for unreadable items** (D11). Pending briefs are
      raised as one question card, printed in full at the end of the sync
      that raises it, and read by Claude on a yes. One yes covers every item
      the card listed, six a sync (`KILN_BRAIN_UNITS`). "wait" clears the
      card and gives the free models their three tries back. Written. Raised
      live by the sync that ended at 13:06, and refreshed on 2026-09-25 with
      one plain reason per item (`3ea0f31`, `8624bd0`). The yes or wait is
      the owner's; the card is open with 11 items.

## Phase 5: Queue consent gate (supersedes the 9am rule)

Backend built by a helper agent and re-run here: `test_queue_gate.py` 87/87,
`test_ship.py` 66/66. `daily.py` rewired and `test_daily_commit.py` re-keyed
from the old 9am rule to this one: 23/23.

- [x] **5.1** Builds are offered on every sync, not on a morning schedule.
      Tested (`test_daily_commit.py`), and the sync that ended at 13:06 on
      2026-09-25 ran the queue stage then, not at 9am.
- [~] **5.2** Estimate the work and rough time per queued project. From the
      median of past builds (one so far, 37 minutes) and past publishes
      (none timed yet, so 30 minutes until one is). Tested; not yet seen on a
      real card, because nothing has been queued since it was built. First
      chance: the next project queued.
- [x] **5.3** Question card with all / one / few / none, answered from the UI.
      A tick box per project, plus all and none. Walked in a browser on a copy
      of the data (2026-09-25): nothing ticked is refused with "tick at least
      one first", and one ticked project comes back from `consented()` as
      exactly that job. From a terminal: `answer <id> some <numbers>`.
- [x] **5.4** Update the routine prompt and `README.md` to match. Both done
      and brought up to date again in the coherence passes (7.1). The routine
      prompt was installed on the scheduled task at the merge, and what landed
      was read back and matches the draft line for line.

## Phase 6: The brain

- [x] **6.1 A playbook store that accumulates.** Nothing learns today; the
      thirteenth reel on a topic gets the same three template queries as the
      first. Plan: the planner writes short lessons after each piece of work,
      and both the planner and the free tier's search step read the ones that
      match the next item. Built: a `playbook` table. Lessons carrying a link
      are refused, so a post cannot plant one that rides into every later
      prompt. On 2026-09-25 it turned out the lessons were never read (see
      "Found while building"); fixed in `8c88bd0` and `c5635bb`, and the 20
      live lessons re-filed. From the live store the Jarvis tutorial now
      finds ten lessons and the job carousel six, where both found none. The
      free tier's search step reads through the same call; tested, not yet
      seen live (quota).
- [x] **6.2 A fulfilment check.** Nothing anywhere asks whether the owner's
      request was answered. A processed item with an unanswered instruction
      falls out of every check permanently. Plan: every sync looks at every
      item with an instruction; unanswered or blocked ones go back to Claude,
      and answers that are only partial are named in the check with the reason.
      Built: `brain.needs_follow_up` picks the work each sync (anything with
      an instruction first), and `health.check_follow_ups` reports partial
      answers with their reason. Live: the sync that ended at 13:06 picked
      six units and its check printed the two still waiting.
- [x] **6.3 Sections with subsections.** The `tags` table is three columns with
      no parent or depth, and section names are validated against a closed list
      of eight. "to watch" worked by coincidence. Plan: an open, two-level
      section tree, filed by the planner, shown as a tree in the sidebar.
      Built: a `sections` table, a `section` tag, filtering that includes
      subsections, the tree in the sidebar and on the site. On the live site
      on 2026-09-25: "To Watch" (9 items) with "Concept Explainers", "Full
      Courses" and "Talks & Panels" under it, in the data and on the page.

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
- A spent free-tier day was never recognised (found 2026-09-25, fixed in
  `0816427`). Gemini says whether a 429 is the minute or the day only in the
  `quotaId` near the end of the body, at character 1021 of 1362 in the one
  measured, and `_post` cut the body to 400 characters before anything read
  it. So every item waited 4 + 9 + 20 seconds and asked four times on every
  model, all day, re-sending a reel's whole video each time, and the ledger
  never marked a model out: it still said 18 of 18 left while the API
  refused every call. The ledger also turned over at local midnight while
  Google's quota resets at midnight Pacific ("Requests per day (RPD) quotas
  reset at midnight Pacific time", ai.google.dev rate-limits page).
- A spent day also used up a link's tries (fixed in `d498b7d`). A try was
  counted as the read started, so every sync inside a spent day took one
  of a link's three without any model reading anything. A read every model
  turned away for a spent day now gives its try back.
- The follow-up could add to an item but never take a first pass back
  (fixed in `f1a94d6` and `8473ea3`). Live example: a setup guide for a
  local assistant (`03d5b6b18a964e5d`) is tagged apply. The post names
  TypeSafe once, as the maker of the Jev classifier it uses, and the first
  pass went looking for a job there and filled the item with an
  infrastructure job posting. The final step can now set that research
  aside with a reason (kept on the item, off the page and the site) and
  correct the tag.
- A later look that found nothing to add threw the earlier answer away
  (found and fixed 2026-09-25, `3a9040c`). The `nothing_to_do` branch
  wrote a fresh follow-up record over the old one. Live: re-running
  `03d5b6b18a964e5d` by hand took it from an answer with 15 sources and 2
  tasks to no answer at all. A sync can do the same, because an item read
  again after its follow-up is picked again. The earlier answer now stays
  and the later look is kept beside it, the rule `_mark` already followed
  for failed runs. The new checks fail on the code before (164/168).
- That re-run's planner took the earlier answer's word over the item. The
  earlier follow-up ran on code that could not take research off: it took
  the two job links off the item's link list and said so, while the job
  research itself stayed (25 mentions of TypeSafe in the stored research).
  The planner read that as already fixed. It is now told an earlier answer
  is only what it said, and shown what was really set aside (`3a9040c`).
- The card asking to let Claude read the unreadable items printed each
  item's raw HTTP error body, JSON and all. It now gives one plain line per
  item from what the models answered: out of quota for the day, overloaded,
  or a read below the floor (`3ea0f31`).
- The playbook was written but never read (found and fixed 2026-09-25,
  `8c88bd0`, `c5635bb`). `lessons_for` matches the next item by its kind
  and topic tags, but each lesson was filed under the model's own label
  for it ("pitfall", "tip") and its own topic words, so an item with no
  instruction matched nothing: the Jarvis tutorial got none of 20 lessons,
  six of them written from it. A lesson is now filed under the kind and
  topic tags of the items it came from, a group bringing its eight most
  common topics (the seven "to watch" videos have 25 between them), and
  topics are stored whole: the joined text used to be cut at 300
  characters, mid-word. The 20 live lessons were re-filed by the same rule
  (store backed up first); the new checks fail on the code before.

## Phase 7: Coherence and proof

- [x] **7.1 Full read-through** for contradictions between code, tests, README,
      the routine prompt and this file. Found while orienting on 2026-09-25:
      - README's "Models" section still described the lite and local ladders.
        Fixed.
      - README said `pip install -r requirements.txt` and there was no such
        file. Added.
      - The routine prompt never mentioned the Claude briefs (see 2.4).
        Rewritten and installed on the scheduled task (5.4).
      - The sidebar's "free today" meter read a retired lite model, and
        `models.health()` pinged that model on every 30 second poll. Fixed: the
        meter sums the ladder models, and the health check reads the model's
        metadata (no quota) at most every five minutes.
      - `test_daily_commit.py` asserted the old 9am build rule. Re-keyed.

      Then a separate reviewer read everything at `8fd7045` and found 45 live
      contradictions, six of them bugs where the code did something other than
      what a card or a doc promised. All 45 are fixed on the branch
      (`60ab305` for the code, then the README, this file and the routine
      prompt). Each of the six bugs has a test, and each of those tests was
      run against the old code (`8fd7045`) and fails there; the "ignore" one
      by crashing, because the card key it needs did not exist yet:
      - A Claude read left the item marked `redo`, so it was never followed
        up again.
      - "ignore" on a health card was never read, and the card came back.
      - "claude cloud" on a build card built locally, and "look" retried the
        whole publish chain whether or not anything had been fixed. Both
        choices are gone.
      - "wait" on the unreadable-items card did not give the free models any
        more tries once they had used their three.
      - Copy on the local page built the prompt in JavaScript, 50 lines
        against the 75 that Queue it writes. The server sends the one prompt.
      - A second link added to an inbox line already read was never read,
        and an instruction added under a read link never reached it. Links
        are now remembered one by one.
      Also: `sync_inbox.py` skipped the follow-up when nothing was new;
      questions raised during a sync were never printed in full; a project's
      CI result was thrown away; the queue card could not be ticked from a
      terminal; a video's frames stopped at its 48th second; the audit never
      checked a note shorter than eight words (a five to seven word note
      could not match an eight word run); token counts were missing for two
      calls; the gate box on the site showed an empty line; and a dozen
      comments, docstrings and README lines described code that had changed.

      A second reviewer then read the branch at `8473ea3`. It confirmed all
      45 fixed, with the file and line for each, and found 18 more, most of
      them run to prove them. Fixed, each with a test that was run against
      the code before it and fails there, except the published page's health
      check, which has no test and was checked by reading the code:
      - A Claude read of a reel took its frames from the sound-only file and
        got none (`8f2c7d0`).
      - Setting research aside left its install preview, citations, the
        links it had added (published) and the search entry (`f69261e`).
      - "skip" on a failing build lost to an older card answered "claude"
        (`b55b600`).
      - A card answered from a terminal needed an id it never printed, and
        stored "1" as the answer (`4d944f7`).
      - `brain run <id>`, which the health check recommends, could not read
        an item no free model could (`3cd4309`).
      - A CI run still going after ten minutes was printed as a failure
        (`6f86daa`).
      - Tests one folder down counted as no tests, so a project went out
        untested (`2e1a52f`).
      - Sixteen of eighteen slides were sent while the prompt said to cover
        all eighteen (`8c22dcb`).
      - A Claude read dropped the links it found and the comment gate, and the
        gate's keyword swallowed the next word ("PDF below") (`731f72b`).
      - The page named the model providers, and its health check threw on the
        published copy every thirty seconds (`2d8a3c0`).
      - A link read alone on its line never joined the line's group
        (`60e75b8`).
      - A built project's own ship.py or slop.py skipped the writing gate
        (`79169cf`).
      - The follow-up printout cut item ids and only counted files (`4a5b7b9`).
      - The rest were words, fixed in `8a82dbe` and in this file.
      Two of its points are questions instead: thinking for reading (Q2) and
      a session name in a probe script (Q8).
- [~] **7.2 Re-fire the five stuck reels** and confirm they leave `inbox` with
      real titles and honoured instructions. Also re-fire the 11-slide job
      carousel (`0bcb16be366c6c1b`), whose stored read is empty and which
      carries a PDF request, and the older items whose enrichment failed
      against a local model that was not running.
      - The carousel is done, by the follow-up on the first real sync of the
        new code (2026-09-25, 11:47 to 12:13). The planner saw that the first
        pass had captured no company names; Sonnet workers read the slides
        and researched each company; the answer lists all ten with site and
        where to apply, and says which application links could not be
        confirmed; `ai-startup-jobs.pdf` was made; answered "fully"; the
        title is now "10 Funded AI Startups That Are Hiring: RUNE, Thatch,
        Crusoe, ...".
      - The five reels now download (each one fetched on that run, video
        and sound), but no free model could read them: Gemini's free quota
        was spent for the day (429 on every model) and 3.5 flash was
        overloaded (503). They wait for either the quota to come back at
        midnight Pacific, or a yes on the card asking whether Claude should
        read them.
- [x] **7.3 All suites green**, site rebuilt, audit clean, pushed. On
      2026-09-25: all twelve suites green in the main checkout at `c5635bb`;
      the site rebuilt and pushed (`6123b9e`) with the audit passing 33
      checks. The live site then served this build: 25 items, no provider
      name in the page, no console errors, 375 pixels wide on a phone with
      nothing overflowing, the carousel's PDF downloading, and the Jarvis
      item showing the new answer with none of the job research.

## Phase 8: The routine runs with nobody there (added 2026-09-25)

The owner's report: every scheduled run starts in Manual mode (asks before
each tool) on Opus 5.5 at medium effort, so it waits at its first command
until he switches it to bypass permissions by hand. Wanted: every run starts
on its own in bypass permissions mode, on `claude-opus-5` at `max` effort
(not Opus 5.5).

- [x] **8.1 Find where a run gets its mode and model.** Read from this
      machine and from the docs:
      - Each routine has its own permission mode and model, set in the
        routine's Edit form. Docs (desktop-scheduled-tasks): "Each task has
        its own permission mode, which you set when creating or editing the
        task", and the instructions box "includes pickers for the permission
        mode and model". The same page: "If a task runs in Manual mode and
        needs to run a tool it doesn't have permission for, the run stalls
        until you approve it." That is this bug.
      - The app keeps those per routine in its own `scheduled-tasks.json`.
        The old `check-jobs` routine carries `permissionMode:
        bypassPermissions` and a model. `kiln-inbox-sync` carries neither,
        so every run falls back to the defaults: Manual mode (no settings
        file sets `permissions.defaultMode`), and whatever model the picker
        last had.
      - All four runs so far were switched to bypass by hand while they ran
        (`bypassChosenInApp` on each). The first started on
        `claude-opus-5-5[1m]` at `medium`, effort inherited.
      - Effort is not part of a routine. The fields the app will change on
        a routine are cron, fire time, folder, worktree, branch, model,
        permission mode, browser permission mode, name and notify target;
        there is no effort. A run's effort is left to Claude Code's own
        order: the `CLAUDE_CODE_EFFORT_LEVEL` environment variable, then a
        saved level in the settings file, then the model's default, which
        is `high` for Opus 5. Docs (model-config): "`max` is the deepest
        reasoning level. Unless you set it through the
        `CLAUDE_CODE_EFFORT_LEVEL` environment variable, Claude Code applies
        `max` to the current session only." A session cannot raise its own
        effort either: the app refuses that.
      - Found 2026-09-26 in the app's log (`%LOCALAPPDATA%\Claude\Logs\main.log`)
        and the run transcripts. The routine had no stored mode until he saved
        one at 02:02:13 on 09-26 (`updateScheduledTask`). The 09-25 21:11 run
        started in Manual (`[permissionMode] spawn ... requested=default
        effective=default`), asked to read the Drive doc at 21:11:57, and
        waited until he set bypass by hand at 23:12:21; the read went through
        at once, so bypass covers it. Every run so far waited there the same
        way (`Not auto-approving ... not covered by usable stored approvals`).
      - `change_directory` asks even after bypass: requested at 23:12:53,
        `Not auto-approving ... no suggestions on request`, approved by hand
        at 23:25:38. The app's own note to every scratch-folder run says to
        use it for an existing project. The 09-24 morning run never called it:
        it wrote `data\inbox_snapshot.txt` by its full path and ran
        `python scripts/daily.py` after a `cd` into Kiln in the same command.
      - Effort measured at the request itself: a local catcher that records a
        request's `output_config` and refuses it, forwarding nothing. Opus 5
        from a plain folder asked for medium (his top-level `effortLevel`).
        From a folder whose `.claude/settings.local.json` sets
        `"env": {"CLAUDE_CODE_EFFORT_LEVEL": "max"}` it asked for max. A call
        started the way Kiln starts its workers, with `--effort low`, asked
        for low, and for max when it inherited that variable: the variable
        outranks `--effort`.
- [!] **8.2 Make the routine start in bypass, on Opus 5 at max.** Owner
      action, because permission mode is a security setting:
      1. Settings, Claude Code: "Allow bypass permissions mode" on (it
         already is, since bypass could be picked during runs).
      2. Code tab, Routines, "Kiln inbox sync", Edit. In the pickers on the
         instructions box, set the permission mode to Bypass permissions and
         the model to Opus 5. Save.
      3. Effort. `~/.claude/settings.json` has a top-level
         `"effortLevel": "medium"`, and the docs say that key applies to
         Opus 5 (not to Opus 5.5). So once the routine is on Opus 5 it would
         start at medium. Two documented ways up: set that key to `"xhigh"`,
         which only Opus 5 and older sessions read, so Opus 5.5 sessions are
         untouched; or, for exactly max, add
         `"env": {"CLAUDE_CODE_EFFORT_LEVEL": "max"}`, which puts every
         session on every model at max. Either needs an app restart. The
         Kiln follow-up itself already runs its planner on `claude-opus-5` at
         `max` on every pass, whatever the routine's own session uses.
      4. The routine only runs while the app is open and the laptop is
         awake. A run the laptop sleeps through is skipped, and one
         catch-up run starts on wake.
      Re-checked 2026-09-25 before 13:27, before telling him: the record for
      `kiln-inbox-sync` still has no `permissionMode` and no `model`, while
      `check-jobs` has `"permissionMode": "bypassPermissions"` and a model,
      so the app does keep both per routine once they are set. The four runs
      report, at their end (after anything changed by hand while they ran):
      09-23 21:11 `claude-opus-5-5[1m]` medium; 09-24 09:11
      `claude-opus-5-5[1m]` max; 09-24 21:11 `claude-opus-5` max; 09-25 09:11
      `claude-opus-5` xhigh. The docs re-read the same day: "Each task has its
      own permission mode, which you set when creating or editing the task";
      the top-level `effortLevel` "keeps applying where it applied before, on
      Opus 5 ... while Opus 5.5 ... start[s] at [its] own default"; "`max`
      isn't accepted as a level in either key". The update tool this session
      can call changes a routine's prompt, schedule and on/off only, not its
      model or mode, so steps 2 and 3 are his.
      2026-09-26: he wants max for the routine only, nothing else, so step 3's
      two ways (every session, or every Opus 5 session) are off the table.
      Done instead, and measured (8.1):
      - The routine's own folder (the scratch workspace the app made for it,
        under `%APPDATA%\Claude\scratch-workspaces\`; its full path is the
        `cwd` in the app's `scheduled-tasks.json`)
        got `"env": {"CLAUDE_CODE_EFFORT_LEVEL": "max"}` in its
        `.claude\settings.local.json`, beside the allow list already there.
        Only a session started in that folder reads it, and only the routine
        starts there. A call from that folder asked for max.
      - Kiln no longer passes that variable on (`3bb3360`): the planner, the
        workers, builds, the reviewer and the readme writer each run at the
        effort they are given. Shown on the real launcher: `--effort low` with
        the variable set now asks for low.
      - The routine's instructions (`~\.claude\scheduled-tasks\kiln-inbox-sync\SKILL.md`)
        now say to stay in its folder, never call `change_directory` or
        `request_directory`, and reach Kiln by full path.
      Left for him: the saved model is `claude-opus-5-5` (read 02:28 on
      09-26); Edit, pick Opus 5, save. Bypass is saved already.
- [ ] **8.3 Watch the next scheduled run start that way**, with nobody at the
      keyboard, and record what its session reports (`permissionMode`,
      `bypassChosenInApp`, `model`, `effort`). For the 09-26 09:00 run, the
      app log should show `[permissionMode] spawn <id> ... requested=bypassPermissions`
      and no `Emitted tool permission request` for that session, and its
      transcript should show `claude-opus-5` from the first turn. Effort is
      not in the app log; the folder file was proved at the request (8.1).

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
answering itself moves to the enricher and to Claude. Still open: the free
quota was spent for the whole of 2026-09-25, so there was nothing to run it
on. Found on the way: a budget of 0 does not switch thinking off, it sends
no thinking setting at all, which leaves each model's own default in place.
Sending an explicit 0 needs a live check first, because a model that cannot
turn thinking off may refuse the request.

**Q3. First-pass text on the site keeps its typographic characters.** The
build brief for `excalidraw-quick-diagram` holds 22 non-breaking hyphens, 2
en dashes and 4 arrows, and the free models' briefs and research are
published as written. Claude's answers are already converted (`slop.plain`),
and the publish gate stops such characters in a project's own files. Should
the first pass's text on the site be converted too, or is it fine as it is?

**Q4. Item ids ignore case.** `store.item_id` lowercases the whole link, and
YouTube ids and Instagram codes are case sensitive, so two links that differ
only in case become one item. Unlikely, but the misread id in the roadmap
image (`T9arN5JKmL8` for `T9aRN5JkmL8`) is exactly that shape. Fixing it means
moving every stored id, media folder and document. Leave it, or migrate?

**Q5. `scripts/run_cycle.py`** is referenced nowhere; `sync_inbox.py` does the
same job and more. Delete it?

**Q6. A guard against `python -`.** Typed as a command it hangs on this
machine. It happened to me three times in this session and once in the
2026-09-25 9am run. A PreToolUse hook in `~/.claude/settings.json` could refuse any Bash
command that runs `python -`. That changes your Claude Code settings, so it
waits for a yes.

**Q7. Answered 2026-09-26: max for the routine only, nothing else.** Done
with a settings file in the routine's own folder (8.2). The question as it
stood: **Max effort for the routine** (8.2, step 3). With `"effortLevel":
"medium"` in your user settings, a routine on Opus 5 starts at medium (that
key still applies to Opus 5; Opus 5.5 ignores it). `max` cannot be saved in
settings at all. The one lasting way to max is the `CLAUDE_CODE_EFFORT_LEVEL`
environment variable, which puts every session on every model at max.
`"effortLevel": "xhigh"` instead raises only Opus 5 and older sessions, one
step below max. Which do you want?

**Q8. An Instagram session name in the public repo.** `scripts/probe_acquire.py`
loads a saved Instaloader session by its account name, which is written out
in the file. Remove it from the script? It stays in the git history either way.

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
- A separate security and correctness review, and the coherence review in
  7.1. Security fixes: documents a model wrote are served sandboxed and never
  published as HTML (`8fd7045`), and the local server answers only to this
  machine's own names (`5ddc110`). All 45 coherence findings fixed (`60ab305`, `ef49bf8`).
  Two new suites: `test_audit.py` plants each kind of leak in a throwaway
  copy and runs the real audit; `test_server.py` runs a real server. Twelve
  suites now, all green on the branch and again in the main checkout.
- The 9am scheduled sync ran the old code (09:23 to 10:05). Gemini answered
  503 (overloaded) and then 429 on every model; the free quota was spent for
  the day by 11:00. Found and fixed from that: the daily-quota bug in
  "Found while building" (`0816427`).
- Merged the branch into master (fast forward to `ef49bf8`). The live
  registry dropped the retired research list on first load (backed up
  first). The group tag on `4091b1ffc3d48ceb` was put back, so "to watch"
  has all seven again (database backed up first).
- Measured: a worker asked to read a file one folder outside its own was
  refused ("--restricted confines the file tools to the working
  directory"), so the README's claim that workers see nothing else holds.
- Owner's new request, recorded as Phase 8: routines start in Manual mode.
  Cause and steps are in 8.1 and 8.2.
- The routine prompt was rewritten for the six-stage sync and installed on
  the scheduled task, with a note about quota-spent days.
- Looked at the page in a browser: the gate box, and the queue card (tick
  boxes, "tick at least one first", the stored answer read back by
  `consented()` as exactly the ticked job). At phone width the page was 460
  pixels wide on a 375 pixel screen because a failed item's link title could
  not wrap; fixed in `5985131` and measured at 375 after.
- One slip of mine: I typed `python -` in a command, which hangs on this
  machine. Stopped within the minute; its output was 10 bytes and nothing
  was written.
- The first sync by hand on the merged code ended at 13:06 (inbox 2304 s,
  follow-up 4719 s). The five reels were fetched again and still could not
  be read, the quota being spent. The follow-up worked on six units, the
  carousel among them (7.2). Site rebuilt, audit passed 32 checks, pushed
  (`68d2300`), each of those printed exit 0; the printout does not carry
  the run's own exit code. It raised the card for the 11 unreadable items.
- Rebased the branch onto that site commit and fast-forwarded master twice
  (`3ea0f31`, then `3a9040c`), all twelve suites green in the main checkout
  each time. The rebase gave the branch's commits new ids, so every id in
  this file was pointed at its rebased copy by script and checked against
  master (21 ids, 24 places).
- Routine (Phase 8): re-checked the cause against the app's stored record
  and the docs before writing the owner's steps, and corrected Q7, which
  said Opus 5 starts at high when his settings make it start at medium.
- Re-ran the Jarvis item's follow-up by hand to set its wrong research
  aside. The first re-run (13:17) found nothing to do and exposed the two
  bugs in "Found while building". The second (13:25, on `3a9040c`) set the
  research aside with its reason, corrected the tag from apply to build,
  and answered with 19 sources: the repo sits in a paid community, Jev
  checked claim by claim, and what running the stack takes.
- Published and pushed the site (`6123b9e`) and checked the live copy
  (7.3). Refreshed the unreadable-items card the old code had written with
  raw error bodies: 11 items, one plain reason each (`8624bd0` also makes
  its opening name overloaded models).
- Found the playbook never read, fixed it, and re-filed the 20 live
  lessons (`8c88bd0`, `c5635bb`), store backed up first.
- Two more slips of mine: a time (13:45) and a backup's name (1340) written
  without reading the clock, which said 13:27; both corrected. And two
  inline `python -c` commands with quotes, which the house rule sends to a
  script file.

### 2026-09-26
- The 09-25 21:11 run waited in Manual mode until he came back (8.1). While
  it ran he had it hear the reels: a session commit at 00:35 added
  `kiln/listen.py` (a reel's sound transcribed here with faster-whisper
  when Claude reads it, since Claude sees only frames) and
  `scripts/test_listen.py`, now 17/17. It carried a Co-Authored-By trailer;
  the message was reworded to drop it before anything was pushed (same
  tree), and it went out as `f4fa733`. The README's Needs now says what it
  wants.
- He asked for max effort on the routine only. Measured where effort can
  be read (the request), found the inherited variable outranks `--effort`,
  fixed Kiln so its workers keep their own (`3bb3360`), gave the routine's
  folder the setting, and stopped its runs calling `change_directory`
  (8.2). Thirteen suites green before and after, pushed.
