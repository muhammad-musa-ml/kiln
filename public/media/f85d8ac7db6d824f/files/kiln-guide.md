# Code-driven documentaries: evidence, storyboard and a reviewed render

Researched 2026-11-07.

## Strengths and best use
HyperFrames gives coding agents an editable HTML-based route to graphics and video composition. A documentary workflow benefits from versioned scenes, reusable typography, and reproducible renders. The current CLI supports local preview, environment checks, validation, and export. [CLI documentation](https://github.com/heygen-com/hyperframes/blob/main/packages/cli/README.md)

## Current setup reference
The documented prerequisites are Node.js 22+ and FFmpeg. For a new test project, the current CLI documents this development loop.
```sh
npx hyperframes doctor
npx hyperframes init documentary-test
cd documentary-test
npx hyperframes check
npx hyperframes preview
```
After reviewing the composition, the documented local export route is:
```sh
npx hyperframes render --output documentary-test.mp4
```

## Produce a bounded sample
Write a 30-second script with a source for every factual statement. Assign each scene an original asset, licensed footage, or a clearly labeled illustration. Review a map or chart against its underlying data. Confirm captions, pronunciation, music provenance, audio levels, and the entire video in playback. Renderer licensing, model usage, footage, and optional voice services belong in separate cost entries. [HyperFrames repository](https://github.com/heygen-com/hyperframes)

## Reusable prompt
```text
Plan a short documentary sample with a fact-and-source sheet and a scene manifest. Use supported facts and approved assets. Keep graphics editable, validate the composition, and supply frame, caption, audio, and full-playback checks before final export.
```

## Project idea
Build a documentary source map connecting each narration sentence to evidence, a scene, and an asset. Test a missing source and an unavailable font.


## Original sources
- https://www.instagram.com/reel/DexBgdGKrrI/