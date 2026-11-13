# Three AI engineering projects with measurable deliverables

Researched 2026-11-12.

## Strengths and best use

The sequence turns an AI engineering portfolio into three demonstrations: retrieval quality, tool control and serving reliability. Each project can start small enough to reproduce from a README.

## Current checks

For RAG, keep document citations and separate retrieval quality from answer quality. Ragas provides evaluation components, while human inspection and labeled examples remain important. For agents, record tool traces and test timeouts, denials and invalid arguments. For serving, vLLM and SGLang document their environments and supported model configurations. Measure time to first token, throughput, error rate and hardware cost before interpreting latency.

## Serving example

The vLLM quickstart documents a model argument to the serving command. Replace the placeholder with a model that fits the target hardware and whose license permits your use.

```sh
vllm serve <supported-model-id>
```

## Sources checked

[Ragas](https://docs.ragas.io/en/stable/) - [vLLM quickstart](https://docs.vllm.ai/en/latest/getting_started/quickstart/) - [SGLang](https://docs.sglang.io/) - [LangSmith evaluation](https://docs.langchain.com/langsmith/evaluation) - [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/)

## Project idea

Build a question-answer service over 30 public documents and score retrieval on a labeled set. Add a bounded read-only tool workflow with deterministic fixtures and an explicit budget. Deploy a small model on documented hardware or compare a hosted baseline. Publish exact model settings, reproduction commands, failure cases and what each metric measures.

## Reusable prompt

```text
Design three small repositories for RAG, a bounded tool agent and model serving. For each, specify a baseline, representative failure cases, a measurement method, and a reproducible README.
```


## Original sources
- https://www.instagram.com/reel/DfEsrlDNQGt/