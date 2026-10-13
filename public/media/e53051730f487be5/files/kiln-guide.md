# A critical-advisor prompt: useful skepticism without false certainty

Researched 2026-10-12.

## Source limitation
Muse explicitly says the carousel's images could not be downloaded and that slide descriptions came from semantic analysis. Preserve that caveat: the seven directives are a reconstruction, not the creator's guaranteed verbatim prompt. No secret DM prompt was recovered or claimed.

## Better objective
Replace "always hold your ground" with "revise when evidence changes." A stubborn model can sound independent while remaining wrong. [Anthropic's hallucination guidance](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations) recommends allowing uncertainty, grounding claims and checking citations; it also acknowledges that these measures do not eliminate errors.

## A reusable prompt written for this guide
```text
Act as a careful technical reviewer. State the strongest supported answer
first. Separate observed facts, reasonable inferences and open questions.
Challenge assumptions only when you can name a concrete reason. For current
claims, inspect an authoritative source and cite the exact supporting page.
If evidence is missing, say what is unknown and what would resolve it.
Do not invent URLs, measurements or quotes. If I provide new evidence,
re-evaluate your answer and explain any correction. Prefer a useful test
over a confident adjective. Be direct and respectful.
```

This is an original adaptation, not a recovered slide transcription. Use it in a test conversation first. For persistent app preferences, use the settings actually exposed by the current app; labels can change. For repository work, keep relevant project instructions in the supported workspace instruction file rather than assuming chat preferences configure the CLI.

## Evaluate whether it helps
1. Prepare examples with known answers, one unsupported premise and one genuinely uncertain case.
2. Compare the default prompt with this adaptation using the same questions.
3. Add both valid and misleading pushback. Score whether the model changes position for evidence rather than for user confidence.
4. Inspect whether cited pages really support claims. A confidence label alone earns no correctness credit.
5. Track unnecessary contrarianism and usability as well as factual errors.

## Project idea and limits
A small prompt-evaluation notebook or static report can show baseline/candidate answers, evidence checks and correction behavior. Keep an editable rubric and a few counterexamples. Do not turn self-reported certainty into a numeric probability or advertise a prompt as a truth guarantee.

## Reusable project prompt
```text
Build Evidence-first prompt eval. Known-answer cases, valid/misleading pushback and source-support scoring. Read the linked official docs first. Use fixture data; keep credentials outside source control. Deliver tests, setup instructions, an evidence/limitations note and a small reproducible example. Do not claim a measurement you did not run. Milestones: Write a grounded case set; Compare default and critical prompts; Score corrections and false certainty; Publish the rubric and limitations.
```

## Delivery and next step
The linked current sources were retrieved for this guide; the original dossier and its extraction caveats are retained in Sources. The guide and printable PDF are research deliverables. The proposed project has not been built. Start with the first milestone and verify its acceptance criteria before expanding the scope.


## Original sources
- https://www.instagram.com/p/DeG5wEzEpfR/