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

**Current task** — M7 release verification on tagged Windows CI.

**Last completed**

- Built `SettingsService`, two-phase batch hotkey rebinding, per-user Windows `StartupRegistration`, verified offline `StoreLocation` relocation with `store-location.json`, 216-entry English/Arabic `QTranslator` catalog with RTL layout and `QLocale` switching, and `SettingsView`.
- Addressed all six Review Council Critic blockers (ASCII `QFileDialog` globs in Arabic, off-UI-thread relocation with paused workers and split-brain prevention, `lstat`/pinned/schema-verified storage move, batch hotkey swap + `Shift`-only alphanumeric rejection, `effective_default` single-instance lock, and full `.tr()` + `QLocale` + `GamePage` summary coverage).
- Verified native Windows `RegisterHotKey` conflict preservation, Arabic RTL switching, and data-folder relocation.

**Tests** — 167 tests, Ruff, and native hotkey conflict / Arabic RTL / relocation checks pass. Tagged `m7` CI verification is pending.
