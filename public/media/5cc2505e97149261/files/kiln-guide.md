# Three complete product palettes with tested button colors

Researched 2026-11-18.

## Strengths and best use

The reel shows how color roles apply to whole product pages. A warm keyboard hero, a dark audio hero, and a soft speaker hero can share the same layout hierarchy while using different colors. Keep the product, action, and label clear in each version.

## Current checks

| Example | Surface and headline | Button fill and label | Button contrast |
| --- | --- | --- | --- |
| Warm keyboard | `#EEE5D4` / `#1D4A35` | `#F2462E` / `#111316` | 5.04:1 |
| Dark audio | `#241B3A` / `#B9A7E6` | `#E8FF3A` / `#241B3A` | 14.54:1 |
| Soft speaker | `#F1E4DC` / `#4A2E22` | `#2456CC` / `#FFFFFF` | 6.41:1 |

White on the original tomato red `#F2462E` measures 3.69:1. White on the original blue `#2E6BFF` measures 4.5033:1 for flat, opaque sRGB colors. The darker blue above gives the label more margin. Test opacity, gradients, and appearance over imagery in the rendered page. [WCAG contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

## Project idea

Build three versions of a product hero using semantic CSS variables for surface, text, action, and action label. Check each on a narrow viewport with real copy. Record the text contrast, focus visibility, and whether viewers identify the first action. [CSS custom properties](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Cascading_variables/Using_custom_properties)

## Reusable prompt

```text
Create three product hero themes from these color roles. Keep content and layout fixed. Show the default, hover, and focus color pairs, calculate their contrast, and record where the render needs manual checks.
```


## Original sources
- https://www.instagram.com/reel/DflEGyfuojv/