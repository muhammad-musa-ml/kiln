# Interface animation: continuity, interruption and reduced motion

Researched 2026-11-07.

## Strengths and best use
The reel gives an actionable vocabulary for improving interface feedback. Trigger-aligned entrances, interruptible motion, and shared-element transitions can explain where an object came from and where it went. Motion supports layout transitions and configurable springs, while Radix exposes a dropdown transform origin. [Motion layout](https://motion.dev/docs/react-layout-animations) - [Radix dropdown](https://www.radix-ui.com/primitives/docs/components/dropdown-menu)

## Current checks
The 150-250 ms duration, 30 ms stagger, 0.97 press scale, and 12% stretch are tuning suggestions. A larger animation budget does not establish better task performance. The source dossier could not establish authorship of the advice. Credit the reel's creator for its presentation and cite the implementation documentation for supported behavior.

## Try a focused comparison
1. Pick a dropdown, a list update, and a detail transition. Record the action each animation should clarify.
2. Animate opacity and transform first. Keep the object responsive when the user reverses direction or acts twice quickly.
3. Honor reduced-motion preferences and preserve focus. WCAG describes ways to disable interaction-triggered motion when it is unnecessary. [Reduced-motion hook](https://motion.dev/docs/react-use-reduced-motion) - [WCAG guidance](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html)
4. Compare task time, wrong clicks, motion discomfort, and frame timing against a minimal-motion baseline.

## Reusable prompt
```text
Review these three interactions. State what each motion communicates, propose a restrained baseline, and test interruption, focus, reduced motion, and slow-device behavior. Record observations before choosing timing values.
```

## Project idea
Build an interaction comparison page with a reduced-motion toggle and a worksheet of task errors, response delay, and dropped frames. Begin with three components and fictional content.


## Original sources
- https://www.instagram.com/reel/DfXKRDQRBS_/