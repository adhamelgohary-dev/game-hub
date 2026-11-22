# Progress

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

**Current task** — v1.0.0 complete (all milestones D and M0–M8 approved and published on the private repository). Ready for owner manual acceptance checks (`docs/TESTING.md`) or v2 roadmap planning (`docs/design/07-extensibility.md`).

**Last completed**

- Set `__version__ = "1.0.0"`, added static zero-network, no-injection, and packaging/license audits (`tests/test_packaging.py`), hardened `packaging/installer.iss` for clean upgrades (`_internal`) and uninstall (`Run` cleanup), filtered macOS `libportaudio.dylib`, and updated `THIRD_PARTY_NOTICES.txt`.
- Enhanced `.github/workflows/windows.yml` to verify portable startup, installed startup, in-place upgrade, silent uninstall, and user-data preservation with Python stripped from `PATH`.
- Published English `README.md` updates and full Arabic user guide (`docs/USER-GUIDE-AR.md`), passed the Council, and published the private `m8` (v1.0.0) installer and portable bundle.

**Tests** — 169 tests, Ruff, local zero-Python-`PATH` frozen startup, and tagged `m8` Windows CI (portable, install, upgrade, uninstall, and user-data preservation) all pass.

**Upcoming (optional post-v1)**

- ⬜ Owner manual acceptance walkthrough on Windows 10/11 (live launchers, exclusive fullscreen, 150%/200% DPI, screen reader, clean machine without Python) [simple]
- ⬜ v2 planning — Replay clips and optional Google Drive backup (`docs/design/07-extensibility.md`) [complex]
