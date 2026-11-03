# SupoClip: self-hosted clips, local inference and an output review

Researched 2026-11-02.

## What is current
SupoClip turns long recordings into suggested short clips with captions and reframing. The reel's "free alternative" describes access to self-hosted code, not zero hardware or inference cost. The [current repository](https://github.com/FujiwaraChoki/supoclip) offers a hosted app, self-hosting, an API and MCP integration, and lists AGPL-3.0 licensing. This guide independently checked upstream sources on November 2, 2026; it does not claim a successful local installation.

The [official self-hosting tutorial](https://www.supoclip.com/blog/self-host-supoclip-docker) now documents both hosted providers and local Whisper plus Ollama. Cloud transcription is not universally mandatory. A smaller Whisper model can be slower or less accurate depending on hardware and audio; AI segment selection and "virality" scores are suggestions, not performance guarantees.

## Minimal first run
Install Docker with Compose first. In a new directory:

```sh
git clone https://github.com/FujiwaraChoki/supoclip.git
cd supoclip
```

In Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Follow the [current configuration template](https://github.com/FujiwaraChoki/supoclip/blob/main/.env.example) rather than pasting a dossier's old provider IDs. For the default cloud path, configure the transcription and LLM provider credentials. For local analysis, set `TRANSCRIPTION_PROVIDER=whisper`, `WHISPER_MODEL_SIZE=base` as a small trial choice, and `LLM=ollama:<installed-model>` using the exact model already installed in Ollama. Inside Docker the documented host endpoint is `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`; verify reachability on the actual platform. `BACKEND_CPU_ONLY=true` is the template's CPU setting, not GPU acceleration.

```sh
docker compose up -d
docker compose logs -f
```

The README spells the legacy command `docker-compose`; the current tutorial also uses Compose V2 as above. Open localhost:3107, create an account and test a short recording you own. API documentation is at localhost:8000/docs. If a task remains queued, inspect worker/provider connectivity before submitting more videos.

## Check the output before publishing
Use one familiar recording with an interrupted sentence, a proper name and a wide shot. Verify the caption spelling, word timing, start/end context, face crop and downloaded file. Compare hosted and local providers on the same recording if cost or privacy drives the choice. Record elapsed time, provider cost and the fraction of clips needing manual correction. Optional B-roll, internet video downloads and publishing connections introduce services beyond local inference.

The tutorial notes that the Compose frontend defaults to development mode and explains production builds, origins, backend authentication and database configuration. Keep an initial evaluation local. Database password changes require checking the effective Compose values; setting one `.env` variable alone may not rotate an existing database password. Follow the current tutorial before hosting publicly.

## Reusable prompt
```text
Select short clips from this transcript. For each candidate, include exact
start/end timestamps, a self-contained premise, the opening hook and any
context a viewer would lose. Flag uncertain names and statements needing
fact checks. Prefer a coherent explanation over an attention score. Return
a review list; do not publish, connect accounts or claim guaranteed reach.
```

## Project idea
Make a clip-review scorecard with caption errors, cropping failures, lost context, render time and cost. A blank CSV is included. Run one owned recording first, then decide whether the quality and compute requirements justify processing the backlog. No provider accounts were connected and no video was posted during this research.


## Original sources
- https://www.instagram.com/reel/DfNimaIkaYQ/