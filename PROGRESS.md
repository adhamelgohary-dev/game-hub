# Progress

## v1.0.0 (Completed)
- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- ✅ M2 — Session tracking [complex]
- ✅ M3 — Screenshots [complex]
- ✅ M4 — Notes [complex]
- ✅ M5 — Last time card and Play [complex]
- ✅ M6 — Controls card and timeline [simple]
- ✅ M7 — Settings and Arabic/English [complex]
- ✅ M8 — Packaging and release [complex]

## v1.1 ("Zero background + anti-cheat safe + clean UI + public-ready")
- ✅ D-v1.1 — Anti-cheat research, v1.1 design docs & Fluent UI mockups [complex]
- ✅ M9 — Zero background & clean process exit (Part B) [complex]
- ✅ M10 — Game-aware lifecycle, protected-games catalog, Strict mode & borderless WGC (Part C) [complex]
- 🔄 M12a — Public-readiness audit, MIT license, SECURITY/CONTRIBUTING, EXE metadata & SignPath prep (Part E/F prep) [complex]
- ⬜ Owner Gate 1 — Approve UI mockups (`docs/design/mockups/`) & `m0–m8` release cleanup plan [simple]
- ⬜ M11 — Fluent UI redesign (Dark/Light + Arabic RTL + covers + icon + branding) (Part D) [complex]
- ⬜ M12b — Switch repo PUBLIC (if not yet switched), apply approved `m0–m8` cleanup, publish `v1.1.0-rc.1` & Desktop installer (Parts E/F/G) [complex]
- ⬜ M13 — Final `v1.1.0` release after owner verification (Part G) [simple]

**Current task** — Running Part E public-readiness audit (full git-history secret & PII scan, third-party licenses, MIT `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, SignPath Foundation prep, EXE version-info & manifest) and preparing Owner Gate 1 (UI mockups + `m0–m8` release cleanup proposal).

**Last completed**
- Added bundled updatable `gamehub/core/protection/protected_games.json` (34 anti-cheat titles) + `ProtectedGamesCatalog` with local `%LOCALAPPDATA%\GameHub\protected_games_override.json` support.
- Upgraded SQLite to Schema v5 (`games.protection_mode`, `games.exit_after_launch`, `pending_notes`, legacy `app.start_with_windows` cleanup) with automatic `gamehub.db-v4.bak` backup.
- Updated `ProcessProbe` and `SessionWatcher` so protected/strict games are tracked passively by Toolhelp basename with **zero `OpenProcess` handles**, emitting `ProtectedGameDetected` / `ProtectedGameExited`.
- Implemented `LifecycleCoordinator`, `GlobalHotkeys.suspend/resume`, `WindowsNotifier`, `--play` & Play-through minimize/exit flow, deferred `pending_notes`, per-game GamePage & Settings controls, Arabic catalog parity, and WGC `draw_border=False` with sync/async fallback.
- Passed M10 Review Council (`docs/reviews/M10-review.md`, Judge verdict: APPROVE).

**Tests** — 182 tests and Ruff passing.
