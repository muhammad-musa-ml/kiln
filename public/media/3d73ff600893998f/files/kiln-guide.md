# Assisted video editing: timestamped cuts and visual review

Researched 2026-11-07.

## Strengths and best use
The proposed editing workspace turns reusable choices into an explicit production system. Separating source footage, working files, and exports makes retries and review easier. A style sheet can capture caption size, framing, pacing, and sound levels without depending on a long chat history.

## Current checks
FFmpeg provides media editing primitives. Whisper supplies transcription, while HyperFrames renders authored motion graphics. These components have different setup and verification requirements. Reference material should be used with documented permission and described through general editing attributes. The creator's gated prompt pack was unavailable for independent review. [FFmpeg](https://ffmpeg.org/ffmpeg.html) - [Whisper repository](https://github.com/openai/whisper) - [HyperFrames](https://github.com/heygen-com/hyperframes)

## Build an auditable first edit
1. Use an owned recording and preserve the original. Write a brief naming the audience, desired duration, and intended message.
2. Transcribe and manually correct names and important statements. Keep transcript timestamps tied to source clips.
3. Draft an edit decision list before rendering. Mark cuts that remove context or change a speaker's meaning.
4. Add caption and graphic layers separately. Preview early, middle, and transition frames, then watch the full export with audio.
5. Record export settings, corrections, elapsed work, and service charges.

```sh
ffmpeg -version
ffprobe -v error -show_format -show_streams final.mp4
```

## Reusable prompt
```text
Plan a short edit from these owned sources. Produce a timestamped edit list and caption corrections. Keep source, work, and export folders separate. Explain each removed segment and flag changes to meaning. Supply frame, audio, and full-playback review checks.
```

## Project idea
Create a local production manifest joining clips, timestamps, captions, asset rights, render settings, and reviewer notes. Test a failed render and a corrected transcript.


## Original sources
- https://www.instagram.com/reel/DfYBF8ySvpx/