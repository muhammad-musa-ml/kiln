# App polish: clear state, recovery and responsive interaction

Researched 2026-11-07.

## Strengths and best use
The checklist connects perceived responsiveness to concrete engineering choices. Cached content, clear pending states, larger hit areas, predictable back navigation, and stable numbers can reduce friction during repeated work. Its best use is a task audit where each addition serves an observed problem.

## Current checks
Skeletons work best when a layout is predictable. Optimistic updates need reconciliation and recovery when the server rejects an operation. An undo toast requires a reversible action. A client-side idempotency key also needs server-side persistence and replay handling. Accessibility checks should cover error identification and recovery. [WAI forms guidance](https://www.w3.org/WAI/tutorials/forms/validation/) - [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)

## Apply the checklist
1. Walk through first load, returning load, empty results, offline mode, validation failure, and a repeated submission.
2. Keep stale content recognizable while a refresh is pending. Show an error with a recovery action when the operation fails.
3. Check command menus, shortcut hints, mobile safe areas, keyboard navigation, and focus after dismissing a sheet.
4. Test motion interruptions and reduced-motion settings. Tune tabular numbers and headline wrapping on real narrow layouts. [Motion accessibility](https://motion.dev/docs/react-use-reduced-motion)
5. Record before/after task outcomes for the three most disruptive problems.

## Reusable prompt
```text
Audit this task across loading, stale, empty, error, offline, and repeated-submit states. Choose three improvements grounded in observed friction. Include rollback for optimistic updates, accessible errors, focus restoration, and server-side duplicate handling. Report the behavior actually checked.
```

## Project idea
Create a UI state gallery with delayed responses, failures, and duplicate requests. Use the worksheet to compare completion, recovery, and accidental repeat actions.


## Original sources
- https://www.instagram.com/reel/DfQczY4FE9Z/
