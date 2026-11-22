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
- 🔄 M8 — Packaging and release [complex]

**Current task** — M8 v1.0.0 release verification on tagged Windows CI.

**Last completed**

- Set `__version__ = "1.0.0"`, added static zero-network, no-injection, and packaging/license audits (`tests/test_packaging.py`), hardened `packaging/installer.iss` for clean upgrades (`_internal`) and uninstall (`Run` cleanup), filtered macOS `libportaudio.dylib`, and updated `THIRD_PARTY_NOTICES.txt`.
- Enhanced `.github/workflows/windows.yml` to verify portable startup, installed startup, in-place upgrade, silent uninstall, and user-data preservation with Python stripped from `PATH`.
- Published English `README.md` updates and full Arabic user guide (`docs/USER-GUIDE-AR.md`), and verified local zero-Python-`PATH` frozen startup (`exit: 0`).

**Tests** — 169 tests, Ruff, and local zero-Python-`PATH` frozen startup pass. Tagged `m8` (v1.0.0) CI verification is pending.
