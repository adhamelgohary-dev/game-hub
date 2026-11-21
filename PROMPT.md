# BUILD PROMPT — GAME HUB v1 ("Previously On" — Game Memory)

You are the lead engineering team for **Game Hub**, a Windows desktop app (Python + PySide6, shipped as an `.exe`). The full product definition, scope, architecture and milestones are in **`STRUCTURE.txt`** in this folder. **Read it completely before doing anything.** It is the source of truth. If something there is ambiguous, write the question in `HANDOFF.md` under "Open questions for owner", make a reasonable default decision, log it in `DECISIONS.md`, and continue.

---

## 0. First thing to do (resume check)

1. If `PROGRESS.md` and `HANDOFF.md` already exist in the repo, **you are resuming work started by another AI**. Read `HANDOFF.md`, `PROGRESS.md`, `DECISIONS.md`, and `docs/design/README.md` first. Continue exactly from "Next step" in `HANDOFF.md`. Do not restart or redo finished milestones.
2. If they do not exist, start at **Milestone M0**.

---

## 1. Work as a multi-agent team (mandatory)

Do **not** work as a single agent. Set up the team below at the start and route all work through it. The owner must **not** be asked to copy messages between agents or tools.

- If your tool supports real parallel agents or subagents (for example Antigravity's Agent Manager, or Codex parallel tasks or subagents), **spawn them**.
- If it does not, **simulate the roles sequentially**. Each role works in its own clearly labeled section and writes its own output file or report. Never skip a role.

### 1.1 Build team

| Role | Responsibility |
|---|---|
| **Orchestrator (lead)** | Owns the plan. Splits milestones into tasks, assigns them to agents, merges results, keeps `PROGRESS.md` and `HANDOFF.md` updated, and calls the Review Council. |
| **Architect** | Finalizes the folder structure, module boundaries, event bus, DB schema, and capture-library choice. Writes the decisions to `DECISIONS.md`. |
| **Software Designer (pre-code)** | Does what a senior engineer does **before** writing code. Works with the Architect. It owns the requirements breakdown, use cases and user flows, UI and screen flow, the module structure and interfaces between modules, error handling, and the implementation plan. Writes everything into `docs/design/`. |
| **Data & Extensibility Designer (pre-code)** | Owns the data model: database schema, tables and fields, relations, indexes, migrations, and settings and file formats. Also owns the **extensibility plan**: how future features from the roadmap in `STRUCTURE.txt` will plug in without rewriting existing code (plug-in points, interfaces, config-driven behavior, versioned data). Writes into `docs/design/`. |
| **Implementer — Library** | Steam, Epic, Xbox, and manual detectors, plus their parsers and tests. |
| **Implementer — Sessions & Capture** | Process watcher, session state machine, screenshot service, ring buffer. |
| **Implementer — Audio, Notes & Hotkeys** | Recording and playback, end-of-session popup, global hotkeys. |
| **Implementer — UI** | Main window, library, game page, "Last time" card, timeline, controls card, settings, i18n/RTL. |
| **Tutor (Learning) agent** | Owns `LEARNING.md`. After each milestone it explains the new concepts in plain English, names the 3–5 files the owner should read first and in what order, and adds a short "try it yourself" exercise. It flags any code too clever for a student to follow and asks for it to be simplified. |
| **Security & Privacy agent** | Audits every milestone: secrets or personal data in git, fixtures, or logs; unsafe file handling; permissions; network calls; dependency licenses and known vulnerabilities. Reports to the Critic. |
| **UX & Accessibility agent** | Reviews every screen for clarity, keyboard use, DPI scaling, contrast, Arabic RTL layout, and error messages. Gives concrete fixes, not opinions. |
| **QA / Test agent** | Writes and runs pytest suites and keeps `docs/TESTING.md` (the manual checklist). Blocks a milestone if tests fail. |
| **Integration & Packaging agent** | Wires the modules together, handles PyInstaller, GitHub Actions, and release builds. |

Implementers should work in parallel where tasks do not depend on each other.

### 1.2 Review Council (mandatory quality gate)

Four independent reviewers. They run **(a) once on the overall plan before coding starts**, and **(b) at the end of every milestone** before it is marked done.

| Reviewer | Stance |
|---|---|
| **Advocate** | Argues for the current design or code: what works well and why it should be kept. |
| **Critic** | Actively attacks it: bugs, edge cases, performance, security, anti-cheat risk, UX problems, scope creep, missing tests. Must find real issues, not praise. |
| **Neutral Analyst** | Weighs both sides objectively against `STRUCTURE.txt` and the milestone "DONE WHEN" criteria. |
| **Judge** | Reads all three and issues a verdict: **APPROVE**, **APPROVE WITH CHANGES** (with a numbered list of required fixes), or **REJECT** (with reasons). |

Rules:
- Save each review to `docs/reviews/<milestone>-review.md` (for example `M3-review.md`) with all four sections.
- On **APPROVE WITH CHANGES** or **REJECT**, the build team fixes the issues and the Council re-reviews. There are **at most 2 re-review rounds**. After that, the Judge decides, and remaining issues go to `HANDOFF.md` as known issues.
- Reviewers judge against `STRUCTURE.txt`, not personal taste. Out-of-scope features are a Critic finding, not an improvement.

---

### 1.3 Design phase (mandatory, before any code: "Milestone D")

Before M0 starts, the two pre-code designers and the Architect do the full pre-coding work a professional programmer does. They write it as files in the repo, so the owner or any other AI can read the design without reading the code.

Create **`docs/design/`** with:

| File | Contents |
|---|---|
| `README.md` | Index of the design docs, plus a one-page summary of the whole design. **Read this first.** |
| `01-requirements.md` | Features from `STRUCTURE.txt` turned into numbered requirements (R1, R2, …), each with acceptance criteria. Also covers non-functional needs (performance, privacy, offline use, languages) and what is out of scope. |
| `02-user-flows.md` | Step-by-step flows for every main feature, edge cases, and error cases. Includes UI or screen sketches in text or Mermaid, where the project has a UI. |
| `03-architecture.md` | Layers and modules, what each one is responsible for, how they talk to each other (events, calls, messages), and folder structure. Includes a Mermaid component diagram and a data-flow diagram. |
| `04-data-model.md` | Database schema or storage layout: every table or key, fields, types, relations, and indexes, as a Mermaid ER diagram. Also covers settings and file formats, and the migration and versioning strategy, so data from older versions keeps working. |
| `05-interfaces.md` | Public interfaces between modules: function and class signatures, message or event types, plug-in interfaces, and config schema. Code must follow these. |
| `06-tech-stack.md` | Every library, tool, and engine, with the reason it was chosen, rejected alternatives, and license. |
| `07-extensibility.md` | For **every** roadmap item in `STRUCTURE.txt` (v2, v3, …), where and how it will plug in, and what existing code must **not** need to change. Lists the extension points. The rule: adding a small feature must never require rebuilding existing code. |
| `08-implementation-plan.md` | Milestones broken into ordered tasks, task dependencies, which agent does each task, and what can run in parallel. |
| `09-testing-and-debugging.md` | Test strategy per module (unit, integration, end-to-end), fixtures, the manual checklist, logging, and how to debug common failures. |
| `10-risks.md` | Technical risks and the mitigation for each. |

Rules:
- **No production code until Milestone D is approved.** The Review Council reviews the whole design, and the Judge must approve it. The Critic must specifically attack extensibility ("show me how v2 plugs in without rewrites") and the data model.
- The design is a **living document.** If implementation needs to change the design, update the design files **first**, log the change in `DECISIONS.md`, then change the code. Code and design must never disagree.
- Keep the docs clear and short, written for a student. Use diagrams where they help, and keep code out of the docs except for interface signatures.
- Add a `D` line to `PROGRESS.md` (Milestone D: Design) before M0.

---

## 2. Handoff and progress files (mandatory, keep short and current)

The owner may switch AI tools at any time, when credits or tokens run out. Any new AI must be able to continue **without re-reading the whole codebase**. Create these in the repo root at M0 and update them **after every completed task**, then commit.

### `PROGRESS.md`
- Milestone checklist (M0–M8): status ✅ done / 🔄 in progress / ⬜ todo
- Current milestone and current task
- What was completed last (2–5 bullet points, no long prose)
- Test status (passing or failing, and what)

### `HANDOFF.md` — written for the next AI
- **Design docs:** the location of `docs/design/README.md`. The next AI reads it before touching code.
- **Next step:** the exact next action (file, function, command)
- How to run the app and tests (exact commands)
- Project map: one line per important folder or file
- Known issues and blockers
- Open questions for the owner

### `DECISIONS.md`
One entry per decision: date, decision, reason, alternatives rejected.

### `LEARNING.md` — the owner is a student who wants to understand the code
For each milestone, a short plain-English explanation of the key concepts used (for example "how the process watcher works", "what a ring buffer is", "how RegisterHotKey works"), and which files to read to learn them. Keep it short and practical.

### `AGENTS.md`
A short copy of the working rules in this prompt (team, Review Council, handoff rules, constraints), so tools that auto-read `AGENTS.md` follow them.

**Logging style:** summarize what you did. Do not paste code or long explanations into these files.

---

## 3. Build order

First complete **Milestone D (Design)** from section 1.3. Then follow milestones **M0 → M8** exactly as defined in `STRUCTURE.txt` section 8. Each milestone is done only when:
1. Its "DONE WHEN" criteria are met,
2. Tests pass,
3. The Review Council's Judge says APPROVE (or approves after fixes),
4. `PROGRESS.md`, `HANDOFF.md`, and `LEARNING.md` are updated,
5. The work is committed with a clear message (for example `M3: screenshot ring buffer + tests`).

Work in small commits. Never leave the repo in a broken state at the end of a session.

---

## 4. Hard constraints

- **Platform:** Windows 10/11. **Language:** Python 3.12+, PySide6. **Output:** `GameHub.exe` built with PyInstaller.
- **Repository and deliverables (from M0, kept up to date):**
  - **README.md:** in English, with a short Arabic section. It must contain:
    - project name and one-line pitch
    - screenshots or GIFs, once there is UI
    - features, both current and planned
    - **download and install** steps for the release file. This section comes **right after the features, before "run from source"**, and needs **no terminal**: download from GitHub Releases, then a few clicks. "Run from source" is a later section, clearly labeled "for developers".
    - how to run from source, step by step
    - the **folder structure** as a tree with one line per folder
    - tech stack
    - roadmap
    - links to `docs/design/README.md`, `PROGRESS.md`, and `HANDOFF.md`
    - license, as **"All rights reserved, private for now"** until the owner decides on an open-source license; ask the owner before adding one
  - **Repo hygiene:** `.gitignore`, `.editorconfig`, `CHANGELOG.md` (updated every milestone), and GitHub issue and PR templates. The repo description and topics must be set via `gh repo edit`. The repo stays **PRIVATE**; the owner may make it public later, so write everything as if it will be public one day, with no secrets or personal data anywhere in the history.
  - **Release file:** `GameHub.exe` (PyInstaller) plus an installer (`GameHub-Setup.exe`, Inno Setup). Built by GitHub Actions on every milestone tag and attached to a GitHub Release. Each release includes notes taken from `CHANGELOG.md`. A ready-to-use release must exist from M0 onward, so a non-developer can always install the latest version without a terminal. Never commit build files to the repo.
- **GitHub: you handle git, and the repo is PRIVATE.** The owner wants you to run all git commands yourself and not ask them to type any.
  1. **At M0:** run `git init` with branch `main`, plus a proper `.gitignore`. Check `git --version` and `gh auth status`.
     - If the GitHub CLI is signed in: `gh repo create game-hub --private --source=. --remote=origin --push`.
     - If your tool has a GitHub connector instead, use it to create a **private** repo named `game-hub`.
     - If neither works, tell the owner once: install GitHub CLI and run `gh auth login`, or create an empty **private** repo named `game-hub` and send you the URL. Then add the remote yourself.
     - If a repo named `game-hub` already exists on the owner's account, connect to it. Do not create a duplicate.
  2. **Always private.** Never create a public repo, and never change visibility. Before the first push, and after any repo change, check with `gh repo view --json visibility` (it must say PRIVATE). If you can't check, say so in `HANDOFF.md`.
  3. **Commit after every completed task** (small, clear messages), and **push after every completed task or at least at the end of every session**. The remote must always hold the latest `PROGRESS.md` and `HANDOFF.md`, so another AI can resume from GitHub.
  4. **At the end of each milestone:** tag it (`m0`, `m1`, …) and push the tags. Release builds go up as GitHub Releases on the private repo, as artifacts only. Never commit build files.
  5. **On resume:** run `git pull` first. If local and remote differ, never force-push. Stop and explain in `HANDOFF.md`.
  6. **Safety:** never commit secrets, tokens, `.env`, personal data, user data, or large binaries. Check `git status` and the staged diff before every commit. If a secret is ever pushed, stop and tell the owner to rotate it.
  7. **Record:** write the repo URL and visibility in `HANDOFF.md`.
  8. **CI cost:** private repos have a limited free monthly quota of GitHub Actions minutes, and Windows runners use it faster. Keep CI lean: run tests on push, and build releases only on tags.
  - Never commit user data, media, builds, virtual environments, or secrets.
- **User data** goes in `%LOCALAPPDATA%\GameHub\`: SQLite plus a media folder. No cloud, accounts, telemetry, or paid APIs in v1. No network calls at all in v1.
- **Anti-cheat safety:** capture only through Windows Graphics Capture or DXGI duplication. **Never** inject into, hook, or read memory of game processes.
- **Performance:** about 0% CPU when idle. Capture only while a known game is in the foreground.
- **Robustness:** a missing launcher or a malformed file must never crash the app. Log it and continue.
- **Scope discipline:** build **only** what `STRUCTURE.txt` lists for v1. Ideas for later go to `HANDOFF.md` under "Future ideas".
- **UI:** Arabic and English with a full RTL layout for Arabic. Clean, simple, gamer-friendly look.

---

## 5. Start now

1. Run the resume check (section 0).
2. Set up the team (section 1).
3. Run **Milestone D (Design)** as described in section 1.3. Write `docs/design/`, then have the **Review Council review and approve the design**.
4. Begin M0, and only after the design is approved.

Report progress only through the handoff files and short status messages.

## 6. Keep going (autonomy)

Do **not** stop after a milestone to wait for approval. When a milestone is done (tests pass, the Judge approves, the work is committed, pushed, and tagged), **continue straight to the next milestone** in the same session.

Stop and wait for the owner **only** when one of these happens:
1. **An owner task blocks you.** Examples: saving fixture pages, creating a bot token, or signing in. While you wait, keep working on anything that doesn't depend on it.
2. **A decision can't be undone** and could reasonably go either way.
3. **All milestones are done.**
4. **Your tool forces the session to end,** for example because of a context or time limit. Before it ends, update `HANDOFF.md`, commit, and push, so that the owner only has to type "continue".

Write a 3–5 line status message at each milestone, then keep working. If the owner just says **"continue"**, resume from "Next step" in `HANDOFF.md`.

## 7. Switching AI tools or models safely (handoff protocol)

The owner may switch to a different AI or a weaker model mid-project, for example when limits run out. The next AI must be able to continue **without breaking or rewriting** the previous AI's work. Add these rules to `AGENTS.md` as well.

**Before you stop (the outgoing AI):**
1. Leave `main` **green**: tests pass and the build works. Never leave half-done work on `main`. Unfinished work goes on a branch named `wip/<task>`, pushed, and `HANDOFF.md` says so.
2. Update `HANDOFF.md`:
   - The exact next step: file, function, and what "done" means.
   - What you were in the middle of.
   - Anything fragile or surprising.
   - Commit and push.
3. Mark the difficulty of upcoming tasks in `PROGRESS.md`:
   - `[simple]` means safe for any model: tests, docs, small UI, following an existing pattern.
   - `[complex]` means it needs a strong model: architecture, data-model changes, tricky bugs, design changes.

**When you start (the incoming AI):**
1. Run `git pull`. Then read `AGENTS.md`, `HANDOFF.md`, `PROGRESS.md`, `DECISIONS.md`, and `docs/design/README.md`.
2. **Run the full test suite and build first.** If they're red, your first job is to fix that, in small steps, without redesigning.
3. **Respect existing work:**
   - Follow `docs/design/` and the existing code style and patterns exactly.
   - **Do not rewrite, refactor, rename, or restructure** code you didn't write unless the current task requires it and `DECISIONS.md` records why.
   - Never delete another agent's work to "start clean".
4. If something from the previous AI looks wrong, **don't silently change direction**. Write it in `HANDOFF.md` under "Open questions" or in `DECISIONS.md`, make the smallest safe fix, and keep going.
5. If you are a smaller or faster model and the next task is `[complex]`, do the `[simple]` tasks that are ready. Then note in `HANDOFF.md`: "complex task waiting: recommend a strong model".

**Always:**
- Make small commits with clear messages.
- Never force-push.
- Never commit with failing tests.
- Run the existing tests after every change, so that one model's change cannot silently break another's.
