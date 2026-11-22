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
- 🔄 M10 — Game-aware lifecycle, protected-games catalog, Strict mode & borderless WGC (Part C) [complex]
- ⬜ Owner Gate 1 — Approve UI mockups (`docs/design/mockups/`) & `m0–m8` release cleanup plan [simple]
- ⬜ M11 — Fluent UI redesign (Dark/Light + Arabic RTL + covers + icon + branding) (Part D) [complex]
- ⬜ M12 — Public-readiness audit, MIT license, SignPath prep, SemVer CI & `v1.1.0-rc.1` (Parts E/F/G) [complex]
- ⬜ M13 — Final `v1.1.0` release after owner verification (Part G) [simple]

**Current task** — Starting M10 (Part C + WGC): bundled updatable `protected_games.json`, Schema v5 migration (`protection_mode`, `exit_after_launch`, `pending_notes`), passive basename-only Toolhelp detection (zero `OpenProcess` on protected games), Strict/Full/Forgetful/Play-through lifecycle, passive Windows toast notification (`ask_me`), and borderless WGC (`draw_border=False`).

**Last completed**
- Removed `QSystemTrayIcon`, tray menus, "Start with Windows" setting, and `winreg.SetValueEx` across `gamehub/`.
- Added `remove_legacy_startup_entry()` at startup and Inno Setup `deletevalue dontcreatekey` cleanup so upgrading from v1.0 removes the legacy `Run\GameHub` entry.
- Added `GameHubWindow.closeEvent` full teardown (`closeAllWindows()` + `quit()`), real subprocess exit verification (`tests/test_app.py`), and static packaging audits (`tests/test_packaging.py`).
- Passed M9 Review Council (`docs/reviews/M9-review.md`, Judge verdict: APPROVE).

**Tests** — 171 tests and Ruff passing.
