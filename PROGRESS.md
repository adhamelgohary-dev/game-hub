# Progress

- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- ✅ M2 — Session tracking [complex]
- ✅ M3 — Screenshots [complex]
- ✅ M4 — Notes [complex]
- 🔄 M5 — Last time card and Play [complex]
- ⬜ M6 — Controls card and timeline [simple]
- ⬜ M7 — Settings and Arabic/English [complex]
- ⬜ M8 — Packaging and release [complex]

**Current task** — M5 Last time context, Ogg playback, and preview-before-launch.

**Last completed**

- Added session-bound voice and text notes and a persistent close-prompt preference.
- Verified native Ctrl+Alt+N on a synthetic foreground window, with an Ogg note stored under the correct session.
- Added queue cancellation and a retry for encoded clips whose save fails.
- Passed the Council and published the private m4 installer and portable bundle.

**Tests** — 110 tests, Ruff, native shortcut, generated Ogg persistence, and both tagged Windows startup checks pass. M5 playback and live Steam launch are pending.
