# Milestone D-v1.1 Review Council — Game Hub v1.1 Design, Anti-Cheat Research & UI Mockups

**Date:** 2026-11-23  
**Scope:** Part A research (`docs/research/anti-cheat.md`), v1.1 design suite (`docs/design/`), `DECISIONS.md`, `AGENTS.md`, and Part D UI mockups (`docs/design/mockups/index.html` + 11 rendered 1280×800 PNGs).

---

## Round 1

### Advocate
- `docs/research/anti-cheat.md` surveys all requested titles (Valorant, LoL, Fortnite, Deadlock, CS2, Apex Legends, Call of Duty, Rainbow Six Siege, PUBG, Rust, EA FC) plus additional kernel/user-mode anti-cheat titles across all 7 major PC launchers with official vendor links, dates, feature-by-feature risk ratings, comparison against OBS/Discord/Game Bar/NVIDIA/Steam, and honest acknowledgment of heuristic uncertainty for unsigned binaries.
- Zero-background lifecycle cleanly removes the system tray, "Start with Windows", and legacy v1.0 `Run` registry entries (both at installer upgrade and portable startup).
- Piggybacking passive basename-only detection on `CreateToolhelp32Snapshot` achieves **zero `OpenProcess` handles** on protected/strict games without adding a second process scanner or CPU overhead.
- Selecting pure PySide6 + custom Windows 11 / Fluent QSS over `PySide6-Fluent-Widgets` avoids a GPLv3/commercial dual-license conflict, preserving the owner's MIT license and SignPath Foundation eligibility.
- Schema v5 (`games.protection_mode`, `games.exit_after_launch`, `pending_notes`) cleanly upgrades v1.0 (`user_version = 4`) databases with an automatic `gamehub.db-v4.bak` backup.
- All 5 UI screens (Library, Game page, Last-time card, Note prompt, Settings) are mocked in Dark, Light, and Arabic RTL as both interactive HTML and crisp verified 1280×800 PNGs.

### Critic
1. **Strict-mode Play tracking when a launcher game has no assigned `.exe`:** A Strict-mode launcher game (e.g., *Fortnite* or *Elden Ring*) might only have a URI launch target and no explicit `game_targets` exe path. If the user keeps Game Hub minimized rather than exiting immediately after launch, `SessionWatcher` needs a way to detect exit without `OpenProcess`. **Fix needed:** Specify that Strict-mode passive tracking unions `game_targets` basenames with the matched `ProtectedGameEntry.exe_names`.
2. **Immediate safety during `ask_me` notification:** When `protection.external_behavior == "ask_me"`, waiting for the user to respond to a Windows notification while hotkeys and WGC remain active would expose the user during the decision window. **Fix needed:** Specify that `ask_me` immediately suspends hotkeys and pauses capture as a precaution before emitting the passive Windows notification (with zero `powershell.exe` flash and zero topmost window over the game).
3. **Owner gates must not be bypassed:** Part D implementation (`M11`) must wait until the owner reviews `docs/design/mockups/`, and old GitHub Releases (`m0–m8`) must not be deleted until the owner approves the cleanup list.

### Neutral Analyst
- All v1.1 Parts A–G map cleanly onto Milestones `D-v1.1` through `M13` with explicit `[complex]`/`[simple]` tags and Council gates.
- Critic findings 1 and 2 are concrete architectural safeguards that take one targeted update in `docs/design/03-architecture.md`. Finding 3 is already encoded as `Owner Gate 1` in `docs/design/08-implementation-plan.md`.
- Visual inspection of rendered PNGs confirmed Dark, Light, and Arabic RTL rendering with real Windows fonts (`Segoe UI` / `Tahoma`) and zero glyph defects.

### Judge — Round 1 Verdict: **APPROVE WITH CHANGES**
Required changes:
1. Update `docs/design/03-architecture.md` to specify Strict-mode basename union (`game_targets` + `ProtectedGameEntry.exe_names`) and immediate precautionary Strict-mode suspension before emitting the `ask_me` passive Windows notification.

---

## Round 2 (Verification)

- **Architect:** Updated `docs/design/03-architecture.md` with both required clarifications (Strict-mode basename union and immediate precautionary suspension before `ask_me` passive Windows toast notification).
- **Critic:** Confirmed both required changes are reflected clearly and enforce zero `OpenProcess` handles and zero topmost popups over protected games.
- **Judge — Final Verdict:** **APPROVE**

Milestone `D-v1.1` is approved. Proceed to **M9 (Zero background & clean exit)** and **M10 (Game-aware lifecycle, protection & borderless WGC)**; pause before **M11 (UI Redesign)** and **m0–m8 release deletion** to present the mockups and release cleanup list to the owner.
