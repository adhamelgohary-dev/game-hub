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
- ⬜ M9 — Zero background & clean process exit (Part B) [complex]
- ⬜ M10 — Game-aware lifecycle, protected-games catalog, Strict mode & borderless WGC (Part C) [complex]
- ⬜ Owner Gate 1 — Approve UI mockups (`docs/design/mockups/`) & `m0–m8` release cleanup plan [simple]
- ⬜ M11 — Fluent UI redesign (Dark/Light + Arabic RTL + covers + icon + branding) (Part D) [complex]
- ⬜ M12 — Public-readiness audit, MIT license, SignPath prep, SemVer CI & `v1.1.0-rc.1` (Parts E/F/G) [complex]
- ⬜ M13 — Final `v1.1.0` release after owner verification (Part G) [simple]

**Current task** — Starting M9 (Zero background & clean process exit): remove system tray icon, remove "Start with Windows" setting & registry creation, clean legacy v1.0 `Run` key on upgrade/startup, and verify zero remaining `GameHub` processes after window close.

**Last completed**
- Completed Part A anti-cheat research (`docs/research/anti-cheat.md`) with official citations across 20+ games and all 7 major PC launchers.
- Updated `AGENTS.md`, `DECISIONS.md`, and all `docs/design/` specifications for v1.1 (zero background, passive basename-only protection, Schema v5, custom Fluent QSS preserving MIT license, borderless WGC, SemVer releases).
- Created interactive HTML (`docs/design/mockups/index.html`) and 11 rendered 1280×800 PNG mockups across all 5 screens in Dark, Light, and Arabic RTL.
- Passed Review Council (`docs/reviews/D-v1.1-review.md`, Judge verdict: APPROVE).

**Tests** — Baseline 169 tests, Ruff, and frozen PyInstaller smoke test all passing.
