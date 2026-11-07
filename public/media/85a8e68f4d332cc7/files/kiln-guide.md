# Sleep continual learning: retention, consolidation and matched baselines

Researched 2026-11-07.

## Strengths and best use
Sleep addresses a concrete continual-learning problem by separating fast memory from slower consolidation. The researchers describe knowledge seeding and a synthetic-practice phase, then evaluate retention and new-knowledge incorporation. This offers a research design for testing how learning changes over time. [Paper](https://arxiv.org/html/2606.03979v2) - [Google Research overview](https://research.google/blog/the-sleep-framework-a-new-way-for-llms-to-retain-knowledge-in-continual-learning/)

## Independent checks
The paper's factual-incorporation table reports 31.9% for the base model and 48.9% for Sleep on the single-passage SQuAD setting. Removing dreaming gives 35.7% in that comparison. Those are separate experimental conditions that should retain their labels. The blog describes an offline process within human-defined training rules. HOPE is related architecture research, while Sleep specifies a consolidation and rehearsal lifecycle. [HOPE and Nested Learning](https://arxiv.org/abs/2512.24695)

## Plan a small reproduction
1. Pin the paper version, model revision, data sequence, memory capacity, and training budget.
2. Evaluate old knowledge and new knowledge after every stage, including a held-out transfer slice.
3. Compare sequential training, replay, consolidation, and a consolidation-without-dreaming ablation under matched resources.
4. Measure forgetting, accuracy, compute, storage growth, and variance across seeds.
5. Keep synthetic curriculum generation separate from the held-out evaluation set. A budgeted pilot can test the method before attempting the full architecture.

## Reusable prompt
```text
Turn this continual-learning result into a reproduction plan. Preserve dataset, model, and evaluation labels. Specify matched-budget baselines, retention after every stage, a dreaming ablation, seed variation, and compute and storage accounting. Mark implementation details that the available source does not resolve.
```

## Project idea
Build a continual-learning evaluation notebook with a retention matrix, baseline comparison, and resource ledger. Start with a small synthetic task sequence and fixed held-out questions.


## Original sources
- https://www.instagram.com/reel/DfZuDIUOGJZ/