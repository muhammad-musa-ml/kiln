# Kiln

I save a lot of reels. Courses I mean to take, repos I mean to look at, job
posts, resume tips. Then they sit in a folder I never open again.

This reads them for me.

I paste a link into a Google Doc. Kiln opens the post, goes through every
slide, pulls the caption and whatever text is on screen, checks if the links
still work, and then goes and looks up the stuff the post skipped. Everything
lands in a local UI I can search.

**Live: https://kiln-by-m.vercel.app**

That link is a published copy of my library, not the app itself. Worth
explaining properly, because half of Kiln isn't there and that's on purpose.

## What the live site is, and isn't

It's a static export. A folder of JSON and images on a CDN. There is no
database behind it, no API key, and no write endpoint at all. Not hidden,
not disabled by a flag, just not built into it.

**Works there:** browsing everything, filtering by tag or by section, search,
every carousel slide, the PDFs, the full write-up for each item, the answer
to whatever I asked about it along with any document made for it, the
project briefs, and the copy-the-prompt button. That last one works because
the prompt ships inside the data, so it needs no server.

**Doesn't work there, and why:**

- **Adding links.** No write route exists. If you POST to one you get a 405.
- **Running or queueing a build.** Needs a real machine with a shell.
- **Installing anything.** Same. A public endpoint that runs shell commands
  is remote code execution with extra steps, so it only exists locally and
  it refuses to load unless `KILN_LOCAL=1`.
- **Live link checking.** It says "checked 23 Sep" rather than "checked just
  now" because that's the truth. The check ran when I processed the item and
  the result was stored. A static page has nothing to re-check with. The
  heading used to say "just now" and that was wrong, so I changed it.
- **Model controls.** Adding a provider, reordering the models or testing a
  key goes through local routes under `/api/models`, which need my keys.
  Neither copy of the page has a panel for them.

**The reason the whole thing can't just live on Vercel:** Instagram blocks
requests from data centre IP ranges. The browser trick works *because* it
runs unauthenticated from a normal home connection. Move it to a server and
you get the same 401s that killed every other approach. That isn't a Vercel
limitation, and no amount of code fixes it. So the reading happens on my
laptop and the result gets published.

## What only exists on localhost

Everything that touches a key, a browser, or a shell:

- Adding links and re-processing them
- Model management through the `/api/models` routes: add any provider,
  reorder a list, disable one, test a key before it's saved. There is no
  panel for these; they are called directly.
- Queueing a build, and the card that asks me which queued builds to run
- Claude's follow-up on each item (below), and the cards it leaves me
- Install previews with a Run button
- The Google Drive sync
- Live model health

I haven't moved these online because each one would mean putting my API keys
on a host I don't control, and I'd be building auth, rate limiting and
row-level security for an app with exactly one user. The static export gets
me the part worth sharing without any of that surface. If I ever want to add
links from my phone, the smallest honest version is a tiny authenticated
endpoint that only writes to a queue, and the laptop still does the work.

## Running it

```bash
pip install -r requirements.txt
playwright install chromium
python -m kiln.server
```

Then open http://127.0.0.1:7878 and paste a link.

You can add context on the same line if you want:

```
https://instagram.com/p/ABC/ | do: find the actual job posting | by: Oct 14 | !
https://github.com/x/y | note: is this worth installing?
```

The `!` marks it urgent. An urgent item, like anything I wrote a note or an
instruction on, gets the deep reading list, which has the pro model second,
and is always read twice with the two reads merged.

## Feeding it from Drive

I keep a doc in Drive and just paste links there. Kiln reads it and never
writes to it, so I can reorganise the doc however I want. It remembers each
link it has read, not each line, so a link added to an old line later still
gets read, and an instruction I write under a link after it was read still
reaches it.

The scheduled sync reads the doc through the Drive connector and saves a
copy of it for `scripts/daily.py` (next section). By hand, from a saved copy:

```bash
python scripts/sync_inbox.py inbox.txt
```

Safe to run twice, it skips any link it has read. It also retries failed
reads and runs the same Claude follow-up the scheduled sync runs. It does
not rebuild the site or touch the build queue; `scripts/daily.py` does.

## The twice-daily sync

A scheduled task on this laptop runs at nine in the morning and nine at
night. It saves the doc and runs

```bash
python scripts/daily.py data/inbox_snapshot.txt
```

Every pass does the same six stages, and prints each one: the inbox (new
links, plus another go at reads that failed), Claude's follow-up, the site
(rebuilt, audited, and pushed if it changed), the build queue, publishing
finished builds, and a check of its own work, which includes whether the
live site actually got the build. Questions waiting on me are printed
before any of that, and any raised during the pass are printed in full at
the end.

## Why a browser

Instagram's API doesn't give you other people's posts. I tried instaloader
and yt-dlp and both hit a login wall. Scraping the HTML gets you the first
slide and nothing else.

A headless browser just works. No login, so there's no account to ban. It
also has to rewind the carousel first, because a shared link opens on
whatever slide the person was looking at and if you only click forward you
silently lose the earlier ones. Took me a while to notice that.

## The part I actually use

Two things turned out more useful than I expected.

**Comment-gated links.** Loads of posts say "comment PDF and I'll send it".
The file isn't public so nothing can scrape it. Kiln spots the pattern and
tells me what word to comment, which at least turns a dead end into a thing
I can do in five seconds.

**Dead links.** It checks every link before showing it. On the first carousel
I ran, two of three links were already dead. Nice to know up front instead of
finding out later.

For anything I want to learn, it also writes a small project brief. Scope,
stack with versions, milestones. I can copy that prompt into any chat and get
a repo out of it, or queue it and have a sync build it once I say yes.

## From a saved post to a repo

A project brief has one button that does anything on this machine. Pressing
it puts the project in a queue. Pressing it again finds the job already
sitting there rather than writing a second copy of it, and that check is on
the item the brief came from, not on the file name, because the naming
scheme changed once and left me two files for one project.

Nothing builds on a schedule. It used to be three at a time on the nine in
the morning run, and whatever was queued got built whether or not I still
wanted it. Now every sync looks at the queue and, if anything is waiting,
puts one card at the top of the local page: each project numbered, what it
is, and roughly how long it takes to build and publish, from how long past
builds actually took here. I tick the ones I want, or take all or none, and
the next sync builds what I picked, three at a time, each one its own agent
in its own directory. None just means not now; the card comes back on the
next sync.

A finished build does not go straight out. A reviewer reads it, installs it,
runs whatever tests it has, fixes what it can and writes down whether the
thing actually works. Kiln then runs the tests itself and reads the exit
code, because the reviewer saying they pass is not the same as them passing.
Then a readme gets written and has to pass a check for writing that reads
like a machine wrote it. Build tooling is stripped and the history is
started clean. Only then is the repo created and pushed.

In the files themselves, two things stop a push and neither is a judgement
call: a banned character, and any line crediting a tool for the work. Wording I dislike in a docstring
is reported and left alone, because holding a working project back over one
word in a comment helps nobody.

Nobody is at the keyboard while a sync runs, so it cannot stop and ask me
anything. When it reaches something that is mine to decide it writes the
question down and carries on with the rest of the queue. An agent that was
rate limited or signed out is not the project failing, so that job stays
queued and is offered again on the next sync. A build that ran and broke
twice stops retrying and asks what I want to do about it. Open questions
show up as cards at the top of the local page. A run prints them before it
does anything else, and prints the ones it raised itself at the end.
After a push the run waits up to ten minutes for the project's own CI and
prints whether it passed, failed, or was still going when the wait ran
out. A red run is reported; the push has already happened by then.

```bash
python -m kiln.runner pending      # build up to three queued projects now, without asking
python -m kiln.runner ship         # review and publish up to three finished builds
python -m kiln.questions list      # what is waiting on me
python -m kiln.questions answer build-queue.queue some 1 3   # tick projects from a terminal
python scripts/dedupe_jobs.py      # one project, one job
```

## Models

Each task has a list of models, best first, and every read has to clear a
floor. A read of a post with pictures or video that comes back with no
sections and no on-screen text (and, for a video, no speech either) has not
been read, whatever the model said, so it counts as a failure and the next
one on the list is tried. The lite and local models are off the lists.
Every thin entry I ever got came off one of them, and a fallback that
quietly makes the work worse is not a fallback.

```
extract        gemini 3.8 flash -> 3.7 flash -> 3.6 flash -> 3.5 flash
extract_deep   3.8 flash -> 3.1 pro -> 3.7 flash -> 3.6 flash   (urgent, or anything I wrote on)
reason         3.8 flash -> 3.1 pro -> 3.7 flash -> 3.6 flash   (research and answering)
classify       3.5 flash -> 3.6 flash -> 3.7 flash              (search queries)
```

All of that is free tier. The pro rung and Gemini's own grounded search
mostly come back out of quota on a free key, and switching billing on needs
a card, so the research here is Kiln's own search and page fetch. Anything
past that is Claude's job (next section).

When every model on a list is out of quota or under the floor, the item is
not filed thin. It waits, and the next sync asks me whether Claude should
read it instead. A read turned away only because every model had used up
its free day does not count as one of the link's three tries.

You can add any provider through the local `/api/models` routes (OpenAI,
Groq, OpenRouter, DeepSeek, Anthropic, xAI, Mistral, Together, or anything
OpenAI-compatible). Keys are encrypted with DPAPI and nothing is saved until
a real test call succeeds.

There used to be a running cost figure in the sidebar. It was token counts
multiplied by a price list I had typed in by hand and never checked against
anything, and it counted free-tier calls at the paid rate, so it was a guess
wearing a dollar sign. I took it out. Token counts are still recorded per
call, which is the part that was ever true.

A couple of things I found out the hard way:

- Turning thinking on made extraction worse, not better. It reasons instead
  of transcribing and you get less text for more money. It's off for reading
  and only on for judgement calls.
- The same model on the same images gives different results run to run, so
  anything important gets read twice and the results merged.
- Local vision models can't do video at all, only frames.

## What Claude does after the free models

The free models do a first pass on everything. Then Claude looks at what
they produced and finishes whatever they could not: the PDF I asked for, the
links they said to check and could not reach, the part of my note they
skipped, a title that is only the post's clickbait. It does this every sync,
on its own, without asking.

A planner on Opus 5 at max effort reads each new item next to whatever I
wrote with it and decides whether anything is left to do. For an item I
wrote nothing on, the answer is usually no. When there is work, it splits
it into tasks and picks a model and an effort level for each one: Opus 5,
Opus 5.5, Sonnet or Haiku, anywhere from low to max. Never Fable, and that
is checked in code before anything runs rather than left to the prompt. The
tasks run three at a time, and a last step puts together what I see: the
answer, any document (turned into a PDF here), where the facts came from,
and a better title if the first one was bad. When the first pass researched
the wrong question, say a setup guide taken for a job posting, that research
comes off the page and the item's tag is corrected; it stays on this machine
with the reason. Whatever it learned about
handling a kind of post goes into a playbook, and the next post like it is
searched and planned with that in hand.

It also files things into sections I name myself. "make a new section called
to watch with subsections for types of videos" makes the section, works out
the types, and puts later videos into them as they arrive.

Every worker runs headless with no shell, and its file tools only reach its
own folder: I asked one to read a file one folder over and it was refused.
It sees the post's pictures and what the first pass found, and the web when
its task needs it. Safe mode matters for cost too: without it every call
loads my whole Claude setup first, about 183k tokens of it.

A sync follows up six items at most (`KILN_BRAIN_UNITS`), so one busy day
cannot turn into hours of Claude work, and the rest wait for the next one.
Items no free model could read go on a card first. One yes covers every
item on it, read six a sync.

```bash
python -m kiln.brain sweep        # follow up what is waiting, six at most
python -m kiln.brain run <id>     # one item, now; reads it too if no free model could
python -m kiln.brain show <id>    # what it did for that item
```

## Publishing

`python -m kiln.publish` builds a static copy into `public/`. It's a
whitelist, so only named fields get out. My notes and my file paths stay
here, and so does anything about how an answer was made.

`python scripts/audit_public.py` greps the build for anything that shouldn't
be there and exits non-zero if it finds something. It reads the text inside
every PDF as well, and fails if any eight words in a row of what I wrote
next to a link turn up anywhere in the build. A note of five to seven words
is looked for whole. One under five is not checked, because that few words
turn up in ordinary text. `scripts/test_audit.py` plants each kind of leak
in a throwaway copy to make sure the audit still catches it.
`scripts/publish_and_deploy.sh` runs the build and the audit and won't
deploy if the audit fails.

## Layout

```
kiln/
  config.py         paths and routing policy
  models.py         the router, quotas, JSON repair
  providers.py      provider adapters
  registry.py       which models exist and in what order
  secrets_store.py  API keys, encrypted with DPAPI
  search.py         web search and page fetch
  acquire.py        browser capture, PDF building
  extract.py        the multimodal read
  enrich.py         research, link checking, install previews
  brain.py          Claude's follow-up: plan, run, record
  claude_cli.py     how the follow-up runs Claude headless
  artifacts.py      documents kept per item, and turned into PDFs
  handoff.py        items no free model could read
  ingest.py         inbox parsing
  pipeline.py       ties it together
  store.py          sqlite, sections, the playbook
  questions.py      the cards that wait on me
  health.py         the run checking its own work
  jobs.py           build prompts and the queue
  runner.py         runs build agents, and the queue card
  ship.py           review, readme, push
  slop.py           the writing check
  server.py         stdlib http, no framework
  publish.py        static export
web/index.html      the whole UI, one file
```

No build step, no node_modules. It starts instantly and I'd like it to still
work in five years.

## Needs

Python 3.11+ and `pip install -r requirements.txt`, then `playwright install
chromium`. A `GEMINI_API_KEY`: every reading list is Gemini's free tier (see
Models). ffmpeg on the path, with the ffprobe that comes with it, because a
reel arrives as separate picture and sound and the follow-up takes frames
from it. The `claude` CLI, signed in, for the follow-up and for the review
and readme before a publish.

For builds, a coding CLI: codex, or gemini's. `claude` builds a job only
when I answer a card saying so. For publishing, `git` and `gh` signed in,
and pytest wherever a project's tests run (its own `.venv`, or Kiln's
Python), or a project that has tests will not publish.

Ollama is optional. Kiln finds its port on its own, because mine was on a
non-standard one, and it can be added as a provider, but no list uses it.
