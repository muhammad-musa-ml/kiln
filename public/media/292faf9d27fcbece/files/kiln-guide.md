# Replica skills: clean-room recon, rebuilding and verification

Researched 2026-10-12.

## Verified setup and scope
The [current repository](https://github.com/Jakeschincariol/replica-skill) documents a Claude Code plugin install and Python 3.8+ helper requirement. In the Claude Code session, the documented commands are:

```text
/plugin marketplace add Jakeschincariol/replica-skill
/plugin install replica-skill@replica-skill
```

Installed plugin skills are namespaced, for example `/replica-skill:replica-recon`. Review the repository and tools before installation. These commands are documented for copying; they were not run in this research. "Free skills" does not mean model usage, hosting or paid integrations are free.

## Turn the pitch into a useful build brief
1. Pick a small workflow whose behavior you can observe legitimately, such as a scheduling or study-planning flow.
2. Build a screen/flow inventory from public pages, documentation and an account you are permitted to use. Mark inferred backend behavior as inferred.
3. Specify your own data model, design tokens, copy, brand and assets. Preserve useful behavior without copying private code or proprietary content.
4. Define acceptance tests for the important flow before generating screens. Include errors, empty states, keyboard operation and authorization boundaries.
5. Implement the smallest vertical slice and compare it against the inventory. A screenshot similarity score cannot establish functional parity.
6. Review real-user complaints critically; turn them into testable improvements rather than copying an anecdotal roadmap.

## Boundaries and practical costs
Authentication, billing, migrations and deployment need separate verification. A generated test report is not proof that a real browser workflow passed. Do not connect live payments or publish a generated app merely because the final skill says to deploy. Review the actual result and the hosting configuration first.

## Project idea
Make an original appointment-request demo using local fixture data, one availability calendar and a clear rescheduling path. Deliver the recon brief, feature matrix, original design system, tested end-to-end flow and a limitations file. Keep real customer data, account credentials and third-party branding out of the fixture project.

## Reusable project prompt
```text
Build Original scheduling prototype. Fixture-only appointment flow with original design/brand and explicit feature acceptance tests. Read the linked official docs first. Use fixture data; keep credentials outside source control. Deliver tests, setup instructions, an evidence/limitations note and a small reproducible example. Do not claim a measurement you did not run. Milestones: Write recon and scope; Design original screens and schema; Implement one complete booking flow; Test error and rescheduling paths.
```

## Delivery and next step
The linked current sources were retrieved for this guide; the original dossier and its extraction caveats are retained in Sources. The guide and printable PDF are research deliverables. The proposed project has not been built. Start with the first milestone and verify its acceptance criteria before expanding the scope.


## Original sources
- https://www.instagram.com/reel/DeB6QU6N4Ec/