# Mobile bottom navigation: labels, accessible targets and visual testing

Researched 2026-11-03.

## Start with clear destinations

The reel removes labels, darkens and enlarges the icons, floats the bar, highlights Home, adds a profile photo, and applies blur. The demo establishes an appearance change. For an interface that must work for first-time users, start with concise visible labels. Apple explicitly recommends labels for tab navigation. A plus button that opens a composer belongs to an action, while Home and Search are destinations. Give the profile destination a stable name even when the account has no avatar. [Apple tab bar guidance](https://developer.apple.com/design/human-interface-guidelines/tab-bars)

## Measure the control people actually hit

Separate icon size from control size. A 24-pixel glyph in a 44- or 48-pixel button is a reasonable prototype. WCAG 2.2 AA specifies a 24-by-24 CSS pixel pointer target, subject to its documented spacing and other exceptions. Mark the current page programmatically and use a visible shape or weight difference alongside color. WCAG's minimum contrast criterion generally calls for 4.5:1 for normal-size text. Required visual indicators and graphical objects generally use the applicable 3:1 non-text criterion. Measure the actual composited background if you add blur. [Target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) - [Text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) - [Non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

## Verify the layout in context

- Reserve enough scroll padding for the bar and safe area so the last item and focused control can clear it. Check small screens, landscape, zoom, and the on-screen keyboard.
- Compare a solid labeled baseline with a floating labeled variant. Change only one variable per comparison. Check bright, dark, and patterned content before trying a translucent surface.
- Ask users to open a saved item, return Home, and change the profile setting. Log the first tap, wrong turns, task completion, and any hidden content. Include keyboard and screen-reader passes and confirm that focus remains visible after route changes.

## Practice project

Build a three-destination prototype with an independent create action. Store paired observations in the navigation test template. Choose the visual variant after measuring task errors and accessibility regressions.

## Reusable prompt

```text
Audit this mobile navigation against its actual route model. Preserve concise labels, accessible names, current-page state, and focus visibility. Measure hit areas and contrast on the worst background. Check keyboard, small-screen, and safe-area behavior. Propose one controlled visual comparison and a manual task script with observable pass conditions.
```


## Original sources
- https://www.instagram.com/reel/DfRfBE_skb5/