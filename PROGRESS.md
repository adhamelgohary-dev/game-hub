# Progress

- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- ✅ M2 — Session tracking [complex]
- ✅ M3 — Screenshots [complex]
- ✅ M4 — Notes [complex]
- ✅ M5 — Last time card and Play [complex]
- 🔄 M6 — Controls card and timeline [simple]
- ⬜ M7 — Settings and Arabic/English [complex]
- ⬜ M8 — Packaging and release [complex]

**Current task** — M6 release verification on tagged Windows CI.

**Last completed**

- Added schema v4 `controls` table migration, `ControlsRepository` (with sanitized WebP image import and orphan recovery), paginated `MemoryRepository.timeline()`, `Ctrl+Alt+C` foreground pinning, and `GamePage` with Controls and Timeline tabs.
- Addressed all six Review Council Critic blockers (shared single `VoicePlayer`, Timeline voice Stop-button state across switches/pagination, durable `ControlsController` shutdown, cross-game draft isolation, `MemoryChanged` publication from `NotesController`, and localized controller errors).
- Verified native `Ctrl+Alt+C` registration and persistence of controls and timeline across restart.

**Tests** — 158 tests, Ruff, and native `Ctrl+Alt+C` / persistence checks pass. Tagged `m6` CI verification is pending.
