# Archived link-first workflow

This folder records the implementation before the October 2026 Muse README migration. It is retained locally and on GitHub for history and recovery. See the [current workflow](../../README.md).

## How it worked

1. Read the shared Google Doc named **links**, keeping URL-adjacent instructions.
2. Parse/deduplicate inbox lines against previously seen hashes.
3. Acquire Instagram, YouTube and web resources directly. Instagram depended on local authenticated sessions; downloads could fail or be incomplete.
4. Extract carousel images or sampled video frames with vision models; transcribe sound locally when needed.
5. Enrich extracted notes with online research, commands, resources, applications and project ideas.
6. Run the follow-up worker for missing detail, creator gates, documents and requests; retry failed reads on later passes.
7. File individual post tiles, rebuild/audit/publish the static site, process owner-consented builds and self-check.

## Preserved files

- [Original project README](ORIGINAL-README.md).
- `kiln/ingest.py`, `acquire.py`, `extract.py`, `listen.py`, `pipeline.py`: original parsing, acquisition, visual/audio extraction and processing.
- `scripts/sync_inbox.py`, `daily.py`: original orchestration.
- `web/index.html`: original interface.

These are reference snapshots, **not a standalone runnable checkout**: they depend on other modules and the private machine environment. No credentials, database, raw inbox or media are archived in Git.

## Compatibility

The active repository retains legacy modules for existing artifacts and deliberate URL processing:

```powershell
python scripts/sync_inbox.py data/inbox_snapshot.txt --legacy-links
python scripts/daily.py data/inbox_snapshot.txt --legacy-links --builds no
```

The authenticated compatibility route is `POST /api/legacy/add`. `POST /api/add` now explains that a Muse README is required. The ordinary import form and scheduled routine never start URL acquisition.

Existing posts, downloads and answers remain in the private database. Consolidation retains original rows and resolves old item URLs to the combined guide. Local **Organize → Restore separate sources** undoes membership without deleting evidence.

## Why the default changed

Media scraping and transcription duplicated the first reading Muse supplies through its Instagram-connected workflow. A preserved Markdown dossier is easier to retry, audit and compare. Kiln now focuses on current verification and practical outputs. The [current README](../../README.md#why-muse-supplies-the-initial-readme) cites Meta's documentation and explains the limits of that reasoning.
