# OpenMontage: a sourced, budgeted video-production pilot

Researched 2026-11-07.

## Strengths and best use
OpenMontage organizes research, scripting, media selection, narration, editing, and composition into a production pipeline. Its current repository includes stock-footage and authored-video routes, provider configuration, and project artifacts. The practical strength is keeping those decisions and intermediate assets reviewable. [Official repository](https://github.com/calesthio/OpenMontage)

## Setup reference
The README lists Python 3.10+, Node.js 18+, FFmpeg, and a coding assistant. It documents the following Unix-style setup. Windows users can follow the repository's explicit PowerShell sequence when make is unavailable.
```sh
git clone https://github.com/calesthio/OpenMontage.git
cd OpenMontage
make setup
```

## Current checks
The repository lists AGPL-3.0 licensing. Optional media and voice providers have their own costs and credentials, and its Remotion composition path needs the applicable license. Its examples demonstrate production choices and reported costs, while a channel's monetization depends on the platform's current rules and actual audience response. [Remotion license](https://www.remotion.dev/docs/license/faq) - [YouTube monetization policies](https://support.google.com/youtube/answer/1311392?hl=en)

## First production exercise
Plan a 30-second explainer using owned or appropriately licensed media. Require a source sheet, script fact check, scene manifest, provider spending ceiling, caption review, and full audiovisual playback. Compare missing footage, incorrect pronunciation, and a provider failure with the happy path. Log all costs and manual corrections.

## Reusable prompt
```text
Create a small production plan with an evidence source sheet, licensed assets, provider choices, spending limits, and review checkpoints. Preserve editable intermediates. Show how a failed provider or missing asset changes the plan before producing the final deliverable.
```

## Project idea
Build a provider-and-asset manifest viewer that reports cost, provenance, missing approvals, and render status for one fictional production.


## Original sources
- https://www.instagram.com/reel/DfFEyZRxdX6/