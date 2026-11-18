# Swap three accents against one product-page baseline

Researched 2026-11-18.

## Strengths and best use

Holding the headline, layout, and base palette steady makes an accent swap easy to compare. The same headphone hero can test where visitors look and whether they recognize its primary action.

## Current checks

The base pair, `#111316` text on `#E9ECEF`, measures 15.69:1. For the accent fills, use the checked foreground below. White text fails the ordinary-text threshold on the lime and orange fills. Compare values before rounding. [WCAG text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

| Accent fill | Button text | Contrast |
| --- | --- | --- |
| Violet `#7B4DFF` | White `#FFFFFF` | 4.83:1 |
| Lime `#C2F23A` | Jet Black `#111316` | 14.23:1 |
| Orange `#FF5A1F` | Jet Black `#111316` | 5.97:1 |

## Project idea

Create three versions of one card with the same call to action and content. Check button labels, control boundaries, and keyboard focus against the rendered surfaces. Then compare first picks and task completion to see whether the accent changes behavior for your audience. [WCAG non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

## Reusable prompt

```text
Create three accent variants over one fixed layout. Use the verified text pairs, then test focus, hover, and adjacent surfaces. Give me a small comparison plan for which action people pick first.
```


## Original sources
- https://www.instagram.com/reel/DfeMVHnvzAK/