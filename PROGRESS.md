# Progress

- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- ✅ M2 — Session tracking [complex]
- ✅ M3 — Screenshots [complex]
- ✅ M4 — Notes [complex]
- ✅ M5 — Last time card and Play [complex]
- ✅ M6 — Controls card and timeline [simple]
- 🔄 M7 — Settings and Arabic/English [complex]
- ⬜ M8 — Packaging and release [complex]

**Current task** — M7 Settings service, hotkey rebinding, Windows startup registration, managed data-folder relocation, and English/Arabic RTL UI localization.

**Last completed**

- Added schema v4 `controls` table migration, `ControlsRepository` (with sanitized WebP image import and orphan recovery), paginated `MemoryRepository.timeline()`, `Ctrl+Alt+C` foreground pinning, and `GamePage` with Controls and Timeline tabs.
- Addressed all six Review Council Critic blockers (shared single `VoicePlayer`, Timeline voice Stop-button state across switches/pagination, durable `ControlsController` shutdown, cross-game draft isolation, `MemoryChanged` publication from `NotesController`, and localized controller errors).
- Passed the Council and published the private `m6` installer and portable bundle.

**Tests** — 158 tests, Ruff, native `Ctrl+Alt+C` / persistence checks, and both tagged Windows startup checks pass. M7 settings, startup, relocation, and English/Arabic RTL are next.
