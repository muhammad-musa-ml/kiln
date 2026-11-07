# brag launch videos: choose the current slim or HyperFrames route

Researched 2026-11-07.

## Strengths and best use
brag packages product inspection, a scene plan, music, motion, and share copy into a repeatable launch-video workflow. It is especially useful when a project already has a clear interaction and approved screenshots. The upstream repository includes both the original HyperFrames route and a newer slim route. [brag repository](https://github.com/latent-spaces/brag)

## Current checks and setup
The current README says `/brag` hands off to `/brag-slim` on Opus 5.5. Use `/brag --full` to request the classic HyperFrames workflow. This changes the older dossier's assumption that every run uses HyperFrames. Inspect the installed skill and runtime requirements before choosing a route. [Classic skill](https://github.com/latent-spaces/brag/blob/main/skills/brag/SKILL.md) - [Slim skill](https://github.com/latent-spaces/brag/blob/main/skills/brag-slim/SKILL.md)

The documented Claude Code install and invocation are reference commands.
```text
/plugin marketplace add latent-spaces/brag
/plugin install brag@brag
/brag --full
```

## Make the first result reviewable
Use a small project with original assets. Write the product's audience, one supported promise, and the interaction that proves it. Review the storyboard, sampled frames, captions, audio, and the final output. Record coding-agent usage, rendering costs, and optional media-provider charges separately. Keep soundtrack and font provenance with the scene manifest.

## Reusable prompt
```text
Create a launch-video brief from this project's real behavior and approved assets. Show three scenes that demonstrate the product. Record every factual claim and asset source. Compare the classic and slim paths using the installed versions and available tools before selecting a renderer.
```

## Project idea
Build a launch-brief worksheet that connects each scene to a product action, evidence, asset, and review result. Start with a ten-second sample.


## Original sources
- https://www.instagram.com/reel/Dezc4qeimex/