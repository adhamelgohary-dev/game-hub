# Progress

- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- ✅ M2 — Session tracking [complex]
- ✅ M3 — Screenshots [complex]
- 🔄 M4 — Notes [complex]
- ⬜ M5 — Last time card and Play [complex]
- ⬜ M6 — Controls card and timeline [simple]
- ⬜ M7 — Settings and Arabic/English [complex]
- ⬜ M8 — Packaging and release [complex]

**Current task** — Complete the M4 Council re-review and packaged audio verification.

**Last completed**

- Added session-bound voice and text notes and a persistent close-prompt preference.
- Verified native Ctrl+Alt+N on a synthetic foreground window, with an Ogg note stored under the correct session.
- Added queue cancellation and a retry for encoded clips whose save fails.

**Tests** — 110 tests, Ruff, native shortcut and session persistence with generated audio, and frozen PortAudio/Vorbis startup passed. The tagged Windows packages are pending.
