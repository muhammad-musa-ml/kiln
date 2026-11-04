# Research problem discovery: from peer-review objections to a testable study

Researched 2026-11-03.

## Turn peer reviews into a testable candidate

Use a 15-minute scan to find candidates. Read the current paper and any public reviews and rebuttal. Record each recurring objection, its evidence, the affected benchmark or population, and the author's response. Count distinct reviewers and check what revisions and newer studies already address.

## Worked example using VoiceAgentBench

VoiceAgentBench v3 reports over 6,000 synthetic queries across English and six Indic languages. Its evaluation omits background noise and live tool interactions, with incomplete multi-turn coverage beyond Hindi. OpenReview blocked verification of the review count and venue outcome. [Paper](https://arxiv.org/html/2510.07978v3) - [Dataset](https://huggingface.co/datasets/krutrim-ai-labs/VoiceAgentBench) - [Code](https://github.com/ola-krutrim/VoiceAgentBench)

τ-Multilingual already evaluates full-duplex calls in Hindi and other languages. A narrower candidate compares synthetic audio with consented recordings for the same tool tasks, holding the transcript fixed and prespecifying noise conditions. Verify that this exact comparison is still open. [τ-Multilingual](https://arxiv.org/abs/2609.35820)

## Practice project

Test 20 matched utterance pairs for one language in separate clean and noisy slices. Freeze mock tool schemas, model settings, and scoring. Measure exact argument accuracy, completion, and transcription errors. Report paired differences with uncertainty and use the pilot to plan a larger study. Log feasibility and stop conditions in the research gap template.

## Reusable prompt

```text
Extract evidence-backed limitations from this paper, public reviews, and rebuttal. Identify gaps that later work already covers. Propose one falsifiable comparison with fixed baselines, estimated costs, and a stop criterion. Mark inaccessible reviews and uncertain novelty.
```


## Original sources
- https://www.instagram.com/reel/DfP5RTdTEpj/