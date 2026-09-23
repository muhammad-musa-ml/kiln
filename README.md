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

**Works there:** browsing everything, filtering by tag, search, every
carousel slide, the PDFs, the full write-up for each item, the project
briefs, and the copy-the-prompt button. That last one works because the
prompt ships inside the data, so it needs no server.

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
- **Model controls.** The panel lists which providers I hold keys for. That's
  information about my setup, so it's local only.
- **Cost meter.** Nobody needs to know what my week cost.

**The reason the whole thing can't just live on Vercel:** Instagram blocks
requests from data centre IP ranges. The browser trick works *because* it
runs unauthenticated from a normal home connection. Move it to a server and
you get the same 401s that killed every other approach. That isn't a Vercel
limitation, and no amount of code fixes it. So the reading happens on my
laptop and the result gets published.

## What only exists on localhost

Everything that touches a key, a browser, or a shell:

- Adding links and re-processing them
- Model management: add any provider, reorder the fallback ladder, disable
  one, test a key before it's saved
- Build jobs: queue one, or run it here in a directory I pick
- Install previews with a Run button
- The Google Drive sync
- Live model health and spend

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

The `!` means urgent, which bumps it to the better model.

## Feeding it from Drive

I keep a doc in Drive and just paste links there. Kiln reads it and never
writes to it, so I can reorganise the doc however I want. It remembers what
it has already done by hashing each line.

```bash
python scripts/sync_inbox.py inbox.txt
```

Safe to run twice, it skips anything it has seen.

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
a repo out of it, or queue it and run it here.

## Models

It tries a list per task and takes the first one that answers. If something
runs out of quota it drops to the next one instead of failing.

```
extract   gemini flash-lite -> flash-lite older -> ollama cloud -> local qwen3-vl
reason    gemini flash -> kimi -> gpt-oss -> local qwen3
```

You can add any provider from the API (OpenAI, Groq, OpenRouter, DeepSeek,
Anthropic, xAI, Mistral, Together, or anything OpenAI-compatible). Keys are
encrypted with DPAPI and nothing is saved until a real test call succeeds.

Most items cost a cent or two. Often nothing, if a free tier picks it up.

A couple of things I found out the hard way:

- Turning thinking on made extraction worse, not better. It reasons instead
  of transcribing and you get less text for more money. It's off for reading
  and only on for judgement calls.
- The same model on the same images gives different results run to run, so
  anything important gets read twice and the results merged.
- Local vision models can't do video at all, only frames.

## Publishing

`python -m kiln.publish` builds a static copy into `public/`. It's a
whitelist, so only named fields get out. My notes, what things cost, and my
file paths stay here.

`python scripts/audit_public.py` greps the build for anything that shouldn't
be there and exits non-zero if it finds something. `scripts/publish_and_deploy.sh`
runs both and won't deploy if the audit fails.

## Layout

```
kiln/
  config.py     paths and routing policy
  models.py     the router, quotas, JSON repair
  providers.py  provider adapters
  registry.py   which models exist and in what order
  search.py     web search and page fetch
  acquire.py    browser capture, PDF building
  extract.py    the multimodal read
  enrich.py     research, link checking, install previews
  jobs.py       build prompts
  ingest.py     inbox parsing
  pipeline.py   ties it together
  store.py      sqlite
  server.py     stdlib http, no framework
  publish.py    static export
web/index.html  the whole UI, one file
```

No build step, no node_modules. It starts instantly and I'd like it to still
work in five years.

## Needs

Python 3.11+, playwright, Pillow, trafilatura, yt-dlp. A `GEMINI_API_KEY`
(the free tier is plenty) or Ollama running locally. Ollama's port gets
auto-detected because mine was on a non-standard one.
