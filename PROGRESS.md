# Progress

- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- 🔄 M2 — Session tracking [complex]
- ⬜ M3 — Screenshots [complex]
- ⬜ M4 — Notes [complex]
- ⬜ M5 — Last time card and Play [complex]
- ⬜ M6 — Controls card and timeline [simple]
- ⬜ M7 — Settings and Arabic/English [complex]
- ⬜ M8 — Packaging and release [complex]

**Current task** — Verify M2 native Windows process and idle performance, then run the Council and release gates.

**Last completed**

- Added the Windows process observer and 2.5-second background watcher.
- Persisted session transitions and recovered abandoned checkpoints.
- Updated the tray and library from typed events on the Qt thread.

**Tests** — 59 native-privilege tests and source smoke pass. M2 live process, idle CPU, and tagged release checks are pending.
