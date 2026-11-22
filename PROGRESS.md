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

**Current task** — M6 Controls card, Ctrl+Alt+C foreground pin, image upload/text notes, and full chronological game page timeline.

**Last completed**

- Built transactional Last time snapshot queries, bounded Qt Multimedia Ogg playback, `Ctrl+Alt+L` target resolution, and validated Play preview with 90-second launch deduplication.
- Addressed all six Review Council Critic blockers (startup subscriber ordering, `BEGIN DEFERRED` snapshot reads, COM STA around `ShellExecuteW`, 200% DPI clamping, LGPL-2.1 FFmpeg notices, and keyboard accessibility).
- Passed the Council and published the private `m5` installer and portable bundle.

**Tests** — 149 tests, Ruff, native `Ctrl+Alt+L` and Ogg playback checks, and both tagged Windows startup checks pass. M6 controls storage/UI and timeline are next.
