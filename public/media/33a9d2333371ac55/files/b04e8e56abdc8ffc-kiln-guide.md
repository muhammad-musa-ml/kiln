# Two base colors and one accent for a clearer next action

Researched 2026-11-18.

## Strengths and best use

Two base colors can do most of the work of grouping information. A spare accent gives the next action a distinct visual cue. Reserve it for actions or highlights that have a meaningful role in the page.

## Current checks

- Lime `#C6F432` with black `#0B0B0C` measures 15.35:1. On white the lime measures 1.28:1.
- Coral `#FF6B5B` with navy `#14213D` measures 5.71:1. White on coral measures 2.80:1. Use a boundary where the fill alone fails to identify the control against the surrounding surface.
- Purple `#8B5CF6` against forest green `#1F3D2B` measures 2.82:1. For a purple button with white text, `#5B21B6` reaches 8.98:1. Check the control against its surrounding surface separately.

WCAG addresses text, essential visual cues, and information conveyed by color. Give the action a label and give selected, error, and focus states a visible cue beyond hue. [Text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) - [Non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) - [Use of color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)

## Project idea

Try the same checkout or signup page with and without the accent, while keeping the copy and layout fixed. Ask viewers to identify the next action. Check focus and error states using a keyboard.

## Reusable prompt

```text
Propose two base colors and one accent for this screen. Name each color's role, verify the actual foreground and background pairs, and make focus, errors, and the primary action clear without relying on hue alone.
```


## Original sources
- https://www.instagram.com/reel/DfScZgPSqc1/
