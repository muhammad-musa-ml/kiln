# Kiln

Saved ideas, researched into something useful.

[Public library](https://kiln-by-m.vercel.app) · [Source](https://github.com/muhammad-musa-ml/kiln) · [Previous workflow](archive/link-first/README.md)

Kiln starts with a **Muse-produced Markdown dossier**, researches the practical next steps against current sources, and turns overlapping reels into one topic with guides, source links, prompts, commands, PDFs and project ideas. Every original URL remains attached.

## Before and now

Previously, a scheduled run read URLs and instructions from a Google Doc named **links**. Kiln downloaded the post, extracted carousel text or video frames, transcribed audio locally, enriched the extraction and asked its follow-up worker to finish missing research. Instagram authentication, scraping failures, frame selection and transcription were part of intake.

Now **Muse does the first reading**. Its README contains the original URL, transcript/visual observations, named tools, claims and gaps. The shared **To-Do AI / researched** folder is the primary inbox. Kiln consumes these READMEs and concentrates on verification, practical instructions and deliverables. The URL identifies evidence; it is no longer the extraction input.

The [archived implementation](archive/link-first/README.md) includes the original README, extraction/orchestration modules and UI. URL acquisition remains an explicit compatibility option, never the default scheduled path.

## Why Muse supplies the initial README

Meta describes Muse as a personal agent with user-controlled service connections, including Instagram, and gives the example of turning a saved recipe reel into a grocery list. This makes Muse a practical first reader in this owner's Instagram workflow. The benefit is an inference from that integration and Kiln's acquisition failures; it does not imply unrestricted access to every post. [Meta launch announcement](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/), [Muse product](https://ai.meta.com/muse/), [Meta security design](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse).

Meta's model API separately documents reading video visuals and embedded audio together, including transcription. Capturing what the reel shows and says before handing a stable dossier to Kiln avoids repeating fragile media extraction. Model API capabilities do not guarantee identical access or transcription quality in the personal agent. The documentation also notes model-specific audio limitations. [Video and audio documentation](https://dev.meta.ai/docs/video-understanding).

Checked **October 12, 2026**. Muse's “verified” labels, reconstructed transcripts, prices and claims remain source evidence. Kiln independently checks current sources and records uncertainty. Muse/Instagram credentials and raw dossiers are never published.

## Exact workflow

1. **Capture:** Muse writes a `.md` dossier into `To-Do AI / researched`. Put the original Instagram or YouTube URL near the top. Transcript, visual notes, tools, links, prompts and gaps can use ordinary Markdown headings, tables and fenced code.
2. **Stage:** the connected local routine downloads exact UTF-8 content and a private manifest of Drive file IDs, names and parents. Local upload/paste also works. Kiln saves a SHA-256-addressed revision before changing the database. Re-importing the same completed revision is idempotent; changed revisions become pending.
3. **Parse:** recognize headings outside code fences; distinguish original URLs from resource URLs; preserve tables, code, transcript attribution and reusable prompts. Source text is evidence, never permission to execute commands.
4. **Research now:** search and fetch current sources, preferring official docs and repositories. Explicit links and documented resource seeds help when search fails. Separate creator claims, corroborated facts and gaps. Find supported setup/run steps, prerequisites, missing application/resource links, limitations, prompts and feasible projects. Ingestion never executes commands.
5. **Create files:** write a practical Markdown guide and printable PDF with citations. Missing evidence, incomplete research or a failed PDF leaves the dossier pending with a retryable error; the source is retained.
6. **Compare:** retrieve library candidates by specific title terms, tools/repositories and original URLs, then compare purpose and subject. Exact sources or sufficiently confident specific matches are synthesized. A broad shared category is insufficient. Ambiguous comparisons stay in the local research inbox. Every successfully researched source is checked.
7. **Unify:** synthesize one task-oriented guide, retaining distinct methods and disagreements. Keep every original URL, transcript and download. Original database rows remain intact; old item URLs resolve to the combined topic. Local **Organize → Restore separate sources** reverses membership. Updating a member refreshes its unified guide.
8. **Organize:** edit public tags and select replacement sections locally, allowing moves or multiple placements. Sections support two levels. **Ready → In progress → Made** tracks the owner's outcome; research completion alone never means a project was built. **Set aside** preserves an unused topic.
9. **Publish:** whitelist safe fields/artifacts into `public/`, strip tracking tokens, secrets and local paths, run the privacy audit, then commit/push the audited snapshot. Both surfaces use the same HTML, JavaScript and CSS source.
10. **Verify live:** wait for the exact JSON snapshot and compare every deployed file's SHA-256 against the export. Only a matching release issues publication receipts. An export or push alone does not complete a dossier.
11. **Clear completed inputs:** the connected routine re-reads the Drive file and checks its digest, moves it from `researched` into sibling **Kilned** while preserving unrelated parents, verifies the move, and confirms local cleanup. Remove only handled original-URL paragraphs from the **links** Doc using a fresh revision. Keep pending URLs, requests and unrelated text. Local files move from `data/research/incoming` into `data/research/Kilned`; attachments stay intact.
12. **Build separately:** copy project prompts or queue builds locally. Building/review/shipping still uses the owner's queue decision; research never starts every suggested project automatically.

## Using the website

- Search titles, research, source URLs, tags, prompts and commands. Combine search with section/tag/action/platform and **Contains** filters: project, prompt, commands, PDF, transcript or research.
- Sort by recent research, title or source count; filter outcome progress; star browser-local bookmarks.
- Tiles show contents before opening. Drawers have Overview, Research, Prompts & tools, Files, Sources and Related tabs, plus local Organize. Heading jump links and collapsible sections help with long guides.
- Share a direct topic or filtered library URL. Original item URLs continue to resolve after merging.
- Open **How Kiln works** on either website for the workflow and public/local explanation.

| Capability | Public website | Local workspace |
| --- | --- | --- |
| Search, filters, guides, sources, prompts, commands, downloads | Yes | Yes |
| Published outcome progress | View | Edit |
| Stars | This browser only | This browser only |
| README import, research and retries | No | Yes |
| Tags, sections, merge/split | View published result | Edit |
| Build queue, decision cards, shell operations | No | Yes |
| Raw dossiers, personal notes, credentials, Drive cleanup | No | Private |

The public deployment is a **static snapshot** with no write API or access to the owner's computer. Shared UI, topic/filter links, downloads and live verification bridge the surfaces; private operations stay local. Local edits appear after publishing.

## Run locally

Python 3.11+, pip and Chromium for PDF rendering. The dependencies also support optional legacy extraction. Publishing needs Git/GitHub authentication. Model credentials stay in private storage/environment. No JavaScript build step is needed.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m kiln.server
```

Open [localhost](http://127.0.0.1:7878). The default bind is loopback; mutation routes require the local token and a validated host. Only the local page receives that token.

```powershell
# Research staged READMEs; never build their proposed projects automatically.
python scripts/research_sync.py import data/research/incoming
python scripts/research_sync.py retry

# Full scheduled cycle, using only owner-consented builds.
python scripts/daily.py data/research/incoming --builds ask

# Build/audit before committing and pushing the intended changes.
python -m kiln.publish
python scripts/audit_public.py

# After deployment: verify all live files and obtain cleanup receipts.
python scripts/research_sync.py verify-live --attempts 30
python scripts/research_sync.py cleanup-plan
# Only after the connector verifies that exact Drive file was moved:
python scripts/research_sync.py confirm-cleanup SOURCE_ID SHA256
```

Drive reads/moves and Google Docs edits use the local routine's authenticated connector. `data/research/drive-manifest.json` is a list of `{id,name,parents}` records next to `incoming`. Account-specific IDs, raw dossiers and credentials are not committed. The routine needs a connected Drive account and running machine; local file upload alone cannot move a remote file.

## Code map and validation

| Location | Responsibility |
| --- | --- |
| `kiln/readme.py` | Dossier parsing, immutable revisions, current research and cleanup states |
| `kiln/topics.py` | Candidate comparisons, coherent synthesis, reversible membership, aliases |
| `kiln/store.py`, `pipeline.py` | SQLite/FTS, facets, states and search indexing |
| `kiln/search.py`, `models.py` | Retrieval and configured provider fallback |
| `kiln/artifacts.py` | Safe document rendering and file index |
| `kiln/server.py`, `web/` | Local API and shared responsive UI |
| `kiln/publish.py`, `release.py` | Whitelisted export and live file verification |
| `kiln/jobs.py`, `runner.py`, `ship.py` | Owner-consented builds, review and shipping |
| `scripts/daily.py`, `research_sync.py` | Scheduled orchestration and connector handoff |
| `scripts/audit_public.py` | Privacy, tracking-token, artifact and shared-UI checks |
| `archive/link-first/` | Original implementation snapshot and explanation |

Private state lives under ignored `data/`. Only audited `public/` is served by Vercel. A database backup and source revisions precede this migration. Run `python scripts/test_readme.py` for the lifecycle/merge regressions and `python scripts/test_server.py` for local API checks; other suites are in `scripts/test_*.py`.
