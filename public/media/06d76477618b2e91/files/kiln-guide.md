# A tested violet, lavender, and coral color system

Researched 2026-11-18.

## Strengths and best use

Lavender, violet, and coral can give surfaces, actions, and highlights recognizable roles. Assign a foreground to each fill so the same palette works for a button, a badge, and body text.

## Current checks

The reel labels `#84CC16` Electric Violet. Tailwind's published v3 palette lists that hex under lime-500. `#7C3AED` is a violet replacement chosen for this guide. White on the supplied lime measures 1.98:1, white on `#7C3AED` reaches 5.70:1, and white on hover violet `#6D28D9` reaches 7.10:1. [Tailwind v3 color values](https://github.com/tailwindlabs/tailwindcss/blob/v3.4.17/src/public/colors.js)

Dark `#1A0B2E` on lavender `#DCD4FF` measures 13.18:1. The same dark text on coral `#FF6B6B` measures 6.69:1. White on coral measures 2.78:1. Violet text `#7C3AED` on lavender measures 4.04:1, below the 4.5:1 minimum for ordinary text. [WCAG text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

## Project idea

Make a product-card prototype with a lavender surface, a violet primary action, and a coral badge with dark text. Add default, hover, and focus states. Evaluate the border and focus indicator against adjacent surfaces, then test a dark theme separately. [WCAG non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

## Reusable prompt

```text
Apply the tested violet palette to one card. Specify text and surface tokens for every interactive state. Calculate contrast before deciding whether each pair meets its applicable threshold. Record remaining checks on the rendered page.
```


## Original sources
- https://www.instagram.com/reel/DfAPe9bpWlJ/