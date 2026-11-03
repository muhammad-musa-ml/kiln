# Voice agents: first-audio latency, turn detection and reliable barge-in

Researched 2026-11-02.

## Latency and interruption are separate problems
The reel describes a voice agent taking four seconds to respond and failing to stop when interrupted. Its salary and interview-failure statistics are unverified rhetoric. Under 300 milliseconds is an example first-audio target, not a measured result or a universal production requirement. This guide checked current primary documentation on November 2, 2026; no live call or audio benchmark was run.

A streaming pipeline can overlap speech recognition, language generation and synthesis, but it still needs sound turn detection. A fixed 150ms silence threshold can cut off hesitant speakers. [LiveKit's turn-handling documentation](https://docs.livekit.io/agents/logic/turns/) covers endpointing, interruption and conversation-state handling; [Pipecat's speech-input guide](https://docs.pipecat.ai/pipecat/learn/speech-input) provides another implementation reference. [Silero VAD](https://github.com/snakers4/silero-vad) detects speech activity; it is not by itself a complete conversational turn detector.

## Instrument the whole path
Record user speech end, final/usable transcript, LLM first token, TTS first audio, transport delivery and actual playback start. Use a monotonic clock for intervals within one process; synchronize or correlate clocks before subtracting timestamps across machines. Report the user's end-of-speech to audible response separately from model TTFT and full-reply duration. Streaming partial output only helps if the downstream components consume it promptly.

When a real interruption occurs, cancel or pause generation as appropriate, stop synthesis, clear queued playback and update conversation state to reflect what the user actually heard. Cancelling the LLM alone can leave previously buffered audio speaking. Conversely, stopping audio for every background sound makes a fast agent frustrating. Test backchannels such as "uh-huh," deliberate interruptions, hesitation and noise separately.

## Current starter route
The [LiveKit Python starter](https://github.com/livekit-examples/agent-starter-python) currently documents the following Windows CLI installation and project creation. Check current provider/service charges and install uv as required by the starter. These commands are references; Kiln did not execute them or create a cloud project.

```powershell
winget install LiveKit.LiveKitCLI
```

```sh
lk --version
lk cloud auth
lk agent init my-agent --template agent-starter-python
```

The current starter requires CLI 2.18.8 or later. In the generated project, follow its configuration instructions, then use:

```sh
lk agent console
lk agent dev
```

Console is a terminal interaction route; dev connects the local agent to the configured LiveKit service. Do not substitute old model IDs from an earlier tutorial. The [voice-agent quickstart](https://docs.livekit.io/agents/start/voice-ai/) and generated environment template are the current setup references.

## Reusable prompt
```text
Review this voice-agent trace. Identify the slowest measured stage without
guessing missing timings. Separate end-of-turn detection from inference
and playback buffering. Propose one change at a time and acceptance tests
for true barge-in, backchannels, hesitation, noisy input and cancellation.
Verify that conversation history contains only the audio actually heard.
Report p50/p95 first-audio latency and false interruptions together.
```

## Project idea and next action
Build a voice-turn test bench using fictional or consented recordings and a blank timing ledger. Include latency, stop-audio delay, false interruption, incomplete utterance and transcript-state checks. Start with a small set of scripted conversations and a baseline before tuning thresholds. This tile stays separate from the broader Jarvis architecture guide because its purpose is measurable voice-pipeline behavior.


## Original sources
- https://www.instagram.com/reel/De3aRzHArun/