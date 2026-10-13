# One Obsidian vault across assistants: bridges and reliable handoffs

Researched 2026-10-12.

## The missing step in the reel
Muse describes switching assistants while continuing a project from one vault. "Connect every AI" hides the actual integration work. A model cannot read local files merely because a path appears in a prompt. Check the selected app's actual file tools and permissions; a manual attachment is a snapshot, not live synchronization.

## Official starting points
Install Obsidian using its [official download page](https://obsidian.md/download). The [current CLI documentation](https://obsidian.md/help/cli) describes setup through Settings -> General -> Command line interface and notes installer requirements. The app must be running; re-open the terminal after registration.

```sh
obsidian help
obsidian vault="Research" search query="project handoff"
```

Replace `Research` with the vault's actual name. The second command is a documented syntax adaptation, not a claim that such a vault already exists.

## Suggested file contract
Use `index.md` as the entry map, one project folder with `status.md`, `decisions.md` and `open-questions.md`, and append-only dated session notes. The status file should include the current objective, verified state, relevant file links, last successful check, blockers and next action. Keep secrets elsewhere.

## Choose a bridge per assistant
- Manual paste/upload: portable and easy to review, but stale after edits and limited by context size.
- A local filesystem-capable assistant: can use an explicitly selected workspace; scope it to the vault instead of the whole home directory.
- An authenticated connector: use only documented capabilities and check whether it reads snapshots or live files. A community MCP server is a separate program to inspect, not an automatic feature of the vault.

## Avoid two-writer damage
Assign one writer at a time, review a diff and keep recovery/version history. Ask the assistant to read the current status before writing. Persist new decisions before a handoff; record contradictions rather than overwriting older evidence silently.

## Test the promise
Give assistant A a small project, save a structured handoff, then ask B to continue using only the permitted notes. Score factual omissions, unresolved decisions and repeated explanation. Repeat after a file edit and permission denial. The investment example in the reel is just demonstration content; this guide does not adopt an assumed return as a forecast.

## Reusable project prompt
```text
Build Assistant handoff vault. A small shared project vault with explicit bridges, revision history and a handoff fidelity checklist. Read the linked official docs first. Use fixture data; keep credentials outside source control. Deliver tests, setup instructions, an evidence/limitations note and a small reproducible example. Do not claim a measurement you did not run. Milestones: Define status and decision templates; Test one assistant bridge; Test a second assistant with only saved context; Add single-writer and recovery rules.
```

## Delivery and next step
The linked current sources were retrieved for this guide; the original dossier and its extraction caveats are retained in Sources. The guide and printable PDF are research deliverables. The proposed project has not been built. Start with the first milestone and verify its acceptance criteria before expanding the scope.


## Original sources
- https://www.instagram.com/reel/DeD8QJ6jd7j/