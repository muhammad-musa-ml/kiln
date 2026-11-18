# Three palettes with measured text and button contrast

Researched 2026-11-18.

## Strengths and best use

The three palettes have strong headline pairs. By explicitly choosing a dark label for each bright accent, you can keep the visual identity and make the primary action readable.

## Current checks

| Theme | Headline on page | Label on accent fill |
| --- | --- | --- |
| Lavender and purple | `#351078` on `#F2ECFF`, 12.17:1 | `#351078` on `#CBFF00`, 11.92:1 |
| Blue and yellow | `#FFFFFF` on `#02167F`, 14.75:1 | `#02167F` on `#FFD014`, 10.03:1 |
| Cream and soft lavender | `#210D35` on `#FFF7F3`, 16.91:1 | `#210D35` on `#D0ADFF`, 9.46:1 |

White on those three bright accents measures 1.18:1, 1.47:1, and 1.89:1, respectively. The audited text pairs meet their contrast thresholds. Also test focus, control boundaries, user-selected themes, and state cues on the finished page. [WCAG text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) - [Non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

## Project idea

Represent each color with four semantic tokens for page, ink, button fill, and button label. Make a preview that includes a hero, disabled and focused controls, and an error message. Use the worksheet to record every tested pair and its applicable criterion. [Design Tokens Community Group format](https://www.designtokens.org/tr/2025.10/format/)

## Reusable prompt

```text
Map these three themes to semantic tokens. Measure text and control contrast in every important state and show which cues communicate focus, errors, and selection beyond color.
```


## Original sources
- https://www.instagram.com/reel/DfUJpcvh4tm/