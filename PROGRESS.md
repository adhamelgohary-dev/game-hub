# Progress

- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- ✅ M2 — Session tracking [complex]
- 🔄 M3 — Screenshots [complex]
- ⬜ M4 — Notes [complex]
- ⬜ M5 — Last time card and Play [complex]
- ⬜ M6 — Controls card and timeline [simple]
- ⬜ M7 — Settings and Arabic/English [complex]
- ⬜ M8 — Packaging and release [complex]

**Current task** — M3 exact-window eligibility, Windows Graphics Capture, and persisted last moments.

**Last completed**

- Added the Windows process observer and three-second background watcher.
- Persisted session transitions and recovered abandoned checkpoints.
- Updated the tray and library from typed events on the Qt thread.
- Verified 0.69% watcher CPU on one logical core and 0.066% app CPU across the machine.
- Passed the Council and published the private m2 installer and portable bundle.

**Tests** — 61 tests, Ruff, native session and tray behavior, 120-second CPU validation, and hosted m2 installed and portable startup pass. M3 capture checks are pending.
