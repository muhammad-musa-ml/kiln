# Weight-space programming: evaluate model edits and the Qwen looping result

Researched 2026-11-03.

## Read the reported experiments separately

The research team tested whether a general-purpose language model could inspect and modify another network's parameters. In a small identification experiment, GPT-6 Astra named the games associated with four policies after receiving their weights and a common interface description. The experiment used 17,253 parameters per policy. Separate experiments used tools to inspect and edit weights. [Authors' research report](https://rikiyat.github.io/blog/weight-space-programming/) - [Experiment logs](https://github.com/RikiyaT/lm_understand-logs)

## What changed in Qwen

The authors report that an edit to roughly 0.016% of Qwen3.5-0.8B's weights raised MATH-500 from 7.9% to 48.1% in their protocol. The full run used a Python harness, practice data, and up to 50 forward passes. It subtracted a direction associated with repetition from selected weights. Fewer answers exhausted the token budget. The team interprets the result as reducing looping so more answers could finish. Their Gemma 3 270M comparison showed little improvement. These are results from the reported settings and checkpoints. [Research report and controls](https://rikiyat.github.io/blog/weight-space-programming/) - [Original Qwen model card](https://huggingface.co/Qwen/Qwen3.5-0.8B)

Direction subtraction is related to a broader family of interpretability interventions. The Arditi et al. paper studies a direction associated with refusal behavior. It provides methodological context for comparing interventions, with a different outcome and experimental setting. [Direction-based intervention paper](https://arxiv.org/abs/2406.11717)

## Practice project

Use the published edited checkpoint and the original base revision to compare a small set of held-out math tasks, instruction following, and a general behavior slice. Pin the tokenizer, template, sampling configuration, seed protocol, and token budget. Record correct answers, truncated answers, and output length separately. Add a shorter-budget comparison and a matched-size control when feasible. Use the ablation log template to track the checkpoint and inference settings. The provided logs are useful for inspecting the actual intervention before attempting to reproduce it. [Published checkpoint](https://huggingface.co/RikiyaT/Qwen3.5-0.8B-weight-space-programming) - [Interactive demo](https://huggingface.co/spaces/ML-Intern-lab/weight-space-programming-demo) - [Experiment logs](https://github.com/RikiyaT/lm_understand-logs)

## Reusable prompt

```text
Design a paired evaluation for these two model revisions. Hold the prompt template and generation settings fixed, then compare correctness, looping, truncation, output length, and unintended regressions. Separate results from the paper, exact results reproduced locally, and hypotheses that still need evidence. Include controls that distinguish a repetition fix from a general capability change.
```


## Original sources
- https://www.instagram.com/reel/DfRtAp6MJcL/