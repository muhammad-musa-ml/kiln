# Interface polish under slow networks and input errors

Researched 2026-11-12.

## Strengths and best use

This source repeats the existing 20-item polish checklist. Its strongest ideas address how a screen behaves when data is delayed, an input is wrong, or a user needs to undo an action. Test those states before tuning visual details.

## Current checks

View transitions need a working fallback and reduced-motion behavior. Android predictive back depends on the platform and app setup. BlurHash represents an image preview. Stripe idempotency is an API mechanism for safe retries. Its UI counterpart is showing request state and preventing an accidental duplicate submission. Confirm suitable target size, focus visibility and contrast in the actual interface.

## Sources checked

[WCAG contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) - [WCAG target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) - [View Transition API](https://developer.mozilla.org/en-US/docs/Web/API/View_Transition_API) - [Motion reduced-motion hook](https://motion.dev/docs/react-use-reduced-motion) - [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests) - [Android predictive back](https://developer.android.com/guide/navigation/custom-back/predictive-back-gesture) - [Wolt BlurHash](https://github.com/woltapp/blurhash)

## Project idea

Pick one interaction, such as saving a setting. Capture first load, latency, failure, retry and undo. Test keyboard and touch, narrow layouts and reduced motion. Give the user status feedback and check that retrying a request has the intended server effect.

## Reusable prompt

```text
Audit one settings flow. Provide a state matrix and test loading, duplicate clicks, keyboard focus, touch, rollback and reduced motion. Explain which checks require a server or mobile device.
```


## Original sources
- https://www.instagram.com/reel/De7aochhik3/
