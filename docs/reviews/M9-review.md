# Milestone M9 Review Council — Zero Background & Clean Exit (Part B)

**Date:** 2026-11-23  
**Scope:** Removal of `QSystemTrayIcon`, tray menu, "Start with Windows" setting & registry creation; legacy v1.0 `Run` cleanup on startup and installer upgrade; clean full-process exit on main window close with subprocess verification and static guardrails.

---

## Round 1

### Advocate
- `QSystemTrayIcon`, tray menus, and minimize-to-tray logic are completely removed from `gamehub/app.py`.
- `app.start_with_windows` is removed from `SettingsService`, `SettingsView`, and `AR_CATALOG`, while legacy v1.0 DB rows are safely ignored on read.
- `gamehub/core/startup.py` now only deletes any legacy v1.0 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\GameHub` entry via `remove_legacy_startup_entry()` (never calling `winreg.SetValueEx` or creating keys), and `packaging/installer.iss` deletes the same value on install/upgrade (`ValueType: none; Flags: deletevalue uninsdeletevalue dontcreatekey`).
- `tests/test_app.py` verifies in a real subprocess that closing `GameHubWindow` cleanly terminates the process with exit code 0 and zero residual processes.
- `tests/test_packaging.py` statically forbids `QSystemTrayIcon`, `SetValueEx`, and invasive Win32 process/hook symbols across `gamehub/`.

### Critic
1. **Secondary unparented window keeping Qt event loop alive on main window close:** `LastTimeCard` is created with `parent=None`, so if it is open when the user closes `GameHubWindow`, Qt's `quitOnLastWindowClosed` alone would not terminate `app.exec()` until the card was also closed. **Fix required:** Override `GameHubWindow.closeEvent` to call `self._app.closeAllWindows()` and `self._app.quit()`.
2. **Stale `"startup_unavailable"` key and unused tray translations:** Clean out leftover `startup_unavailable` message mapping in `SettingsView` and obsolete tray/startup entries in `AR_CATALOG`.

### Neutral Analyst
- Both Critic items are concrete, low-risk fixes that directly enforce Part B's "Closing the main window = the process fully exits" invariant and keep the codebase tidy.
- All 171 automated tests and Ruff checks pass after applying both fixes.

### Judge — Round 1 Verdict: **APPROVE WITH CHANGES**
Required changes:
1. Ensure `GameHubWindow.closeEvent` closes all secondary windows and quits `QApplication`.
2. Remove dead `"startup_unavailable"` code and obsolete tray/startup catalog entries.

---

## Round 2 (Verification)

- **UI & Architect:** Applied `GameHubWindow.closeEvent` (`event.accept()`, `closeAllWindows()`, `quit()`) and removed dead startup/tray strings.
- **QA:** Confirmed full test suite (`171 passed`) and Ruff (`All checks passed!`) pass cleanly, including the real subprocess close-exit verification.
- **Judge — Final Verdict:** **APPROVE**

Milestone M9 is approved. Tag `m9` as an internal plain git tag and proceed directly to **M10 (Game-aware lifecycle, protected-games catalog, Strict mode & borderless WGC)**.
