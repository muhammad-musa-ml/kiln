# Kiln

Scroll goes in. Substance comes out.

You drop a link in a Google Doc. Kiln watches the thing, reads every slide,
pulls out the links, works out what it's *for*, then goes and finds what the
post left out — and files it where you'll find it again.

---

## Start it

```bash
python -m kiln.server
```

Open <http://127.0.0.1:7878>. Paste a link in the box and press **Fire**.

Add context inline, in any order:

```
https://instagram.com/p/ABC/ | do: find the real job posting | by: Oct 14 | !
https://github.com/x/y       | note: is this worth installing?  | tag: ai
```

`!` = urgent (jumps the queue and triggers the deeper, more expensive read).

## Feed it from Google Drive

Kiln reads a doc you own and **never edits it** — it hashes each line, so you
can reorder, annotate and reformat freely without causing repeats.

```bash
python scripts/sync_inbox.py inbox.txt     # or: cat inbox.txt | python scripts/sync_inbox.py
```

Re-running is always safe: already-processed lines are skipped, and an item
that is already done is never paid for twice.

---

## What it does per item

| Stage | What happens |
|---|---|
| **acquire** | A real headless browser opens the post, rewinds the carousel to slide 1, clicks through every slide, downloads them full-resolution, and binds them into one PDF. |
| **extract** | One multimodal call reads speech, on-screen text, captions and code in a single pass. Thin reads trigger a second pass whose results are merged. |
| **enrich** | Searches the live web, fetches the actual pages, and answers the question you had when you saved it — grounded, with citations. |
| **tag** | Files it on four independent axes so it stays findable at 800 items. |

Enrichment is different per kind:

- **learn / tutorial** → what it really is, current version, prerequisites, gotchas,
  what the post left out, and **a project you could build and put on GitHub** —
  scoped, staged, with a pinned stack and an hours estimate.
- **tool / repo** → is it actually good (evidence *and* the case against),
  maintenance status, alternatives, and an exact install command.
- **job** → the real posting, whether it's open, deadline, visa sponsorship.

---

## Two things nothing else does

**Gated payloads.** Half of saved posts say *"comment PDF and I'll send it."*
The file is never public — no scraper, and no competing app, can reach it.
Kiln detects the gate, extracts the keyword, and tells you exactly what to
comment. A dead end becomes a one-tap action.

**Link rot.** Every URL is resolved before you're shown it, and marked live or
dead. Measured on a real carousel: 2 of 3 on-screen links were already dead —
and two independent models had read the same strings, so the OCR was right and
the links had simply rotted. You see that instead of discovering it later.

---

## Tagging

Four independent axes, not a flat tag list:

| Facet | Values |
|---|---|
| `action` | apply · learn · install · read · watch · visit · build · reference |
| `topic` | model-assigned, normalised (langgraph, ai agents, …) |
| `status` | inbox · triage · active · done · dropped |
| `place` | LA, Madison, remote, … detected from context |

"Things to do", "things about AI" and "things in LA" are all just projections
of the same table. Plus your own `tag:` values and full-text search over
everything — transcripts, on-screen text and enrichment included.

---

## Models: free first, quality when it counts

Kiln routes each task down a ladder and takes the first rung that works.

```
extract       gemini-3.5-flash-lite → 3.1-flash-lite → qwen3-vl:235b-cloud → local qwen3-vl
extract_deep  gemini-3.8-flash      → 3.5-flash      → qwen3-vl:235b-cloud
research      own retrieval + reason ladder
reason        gemini-3.8-flash      → kimi-k2.5:cloud → gpt-oss:120b-cloud → local qwen3
```

A rung that 429s is marked spent for the day and skipped; a 503 is retried.
Typical item costs **1–3 cents**, and often **$0.00** when a free rung answers.

Everything in that ladder was measured on 2026-09-23, not assumed:

- **Thinking makes extraction worse** — 51 transcribed lines → 18, for 63% more
  money. It is off for `extract` and saved for judgement calls.
- **Gemini 3.1 Pro is not viable free** — HTTP 429 on the first call.
- **Extraction is non-deterministic** — the same model on the same input gave
  3/3 links and 91 lines once, 2/3 and 51 the next time. Hence the second pass.
- **Local VLMs cannot read video at all**, and run ~11× slower than the cloud
  rung. They are the always-available fallback, not the default.
- **Gemini's grounded-search tool 429s immediately** on its own tiny quota, so
  Kiln does its own retrieval (`kiln/search.py`) and never depends on it.

## Installing things it recommends

One click, with a preview. Kiln shows the exact command, what it touches, and
how to undo it. The **allow-list is enforced server-side**, not in the UI, so a
crafted request can't run something the preview never displayed. Anything with
a pipe, redirect, `sudo`, or `curl`-to-shell is shown but never runnable.

---

## Layout

```
kiln/
  config.py     paths, routing policy, allow-lists   (all env-overridable)
  models.py     the router: fallback, quotas, JSON repair, cost metering
  search.py     free web search + page fetch (no API key)
  acquire.py    browser-driven media capture + PDF binding
  extract.py    multimodal read, union of passes, gate detection
  enrich.py     per-kind research, link health, install previews
  ingest.py     inbox line grammar + dedupe
  pipeline.py   acquire → extract → enrich → tag → store
  store.py      SQLite + FTS5, faceted tags
  server.py     stdlib HTTP server, no framework
web/index.html  the UI, single file, no build step
data/           db, media, PDFs, quota ledger  (gitignored)
```

## Requirements

Python 3.11+, `playwright` + `playwright install chromium`, and one of:
a `GEMINI_API_KEY` (free tier is plenty), or Ollama running locally.
`Pillow` for PDF binding, `trafilatura` for article text, `yt-dlp` for YouTube.

Ollama port is auto-detected — a stray `OLLAMA_MODELS` pointing at another
project makes the default-port server report zero models, so Kiln prefers
whichever port actually serves them.
