# AI model-name comedy: distinguish real models, derivatives and invented labels

Researched 2026-10-20.

## Read this as comedy
The Muse dossier identifies a deadpan skit that mixes real model terminology with invented or garbled names. It contains no usable installation demonstration. An auto-transcript can also turn a joke into a plausible URL, so the spoken names are not a shopping list.

## The real concepts behind the names
[Microsoft's Phi-4 model card](https://huggingface.co/microsoft/phi-4) documents a real base model. [Heretic's upstream repository](https://github.com/p-e-w/heretic) describes automated removal of refusal behavior through model modification. These sources establish those concepts; they do not authenticate every model label, quantization, performance claim or invented website in the reel.

A reduction in refusals is different from stronger reasoning, factual accuracy or better coding. A modified checkpoint can perform differently from its base model and has its own provenance and license obligations. This guide does not recommend a particular derivative or repeat the dossier's unverified free-gateway model IDs and rate limits.

## A practical verification checklist
Before evaluating any named model, locate a maintainer-owned repository or publisher model card. Record the exact repository, revision, base model, license, intended use, file format and expected memory requirement. Separate the model author from a quantization uploader. Check whether a benchmark describes the same revision and inference configuration you would run.

If the only evidence is a comedy transcript, label the name unresolved. Do not invent a download link by combining fragments of the audio. No need to visit a guessed domain just to prove it does not exist.

## What to compare
Use ordinary benign tasks with known answers: a short coding exercise with tests, a document extraction fixture and a factual question set where unsupported answers are counted. Keep the same prompt, context and sampling configuration for both checkpoints. Record correctness, latency, memory use and abstention quality. A refusal count alone does not measure useful capability.

This is an evaluation plan, not a claim that a small local model beats a frontier model or runs on a specified laptop. Actual hardware requirements depend on parameter count, precision, context and runtime.

## Reusable prompt
```text
Turn this model-name list into an evidence table.
For each entry, distinguish an official release, a third-party derivative,
a transcription uncertainty and a fictional name.
Use publisher sources and model cards; do not guess domains or downloads.
Propose benign repeatable tasks and compare accuracy, latency and resources.
Keep unavailable measurements blank and make no installation changes.
```

## Optional project: model provenance cards
Build a small static catalog whose records contain source URL, revision, base model, license, format, verification date and an evidence note. Add a field for "unresolved" so the interface does not force a fake product match. The first version only needs local JSON, filtering and links to original model cards.

## Limits and next action
The original transcript remains attributed to Muse and may contain mishears. This research did not run a model, modify weights, install a runtime or validate the skit's invented names. Next: use the provenance checklist on one real publisher model rather than chasing the entire joke list.


## Original sources
- https://www.instagram.com/reel/DeevahVsCTK/