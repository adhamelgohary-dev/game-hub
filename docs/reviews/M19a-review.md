# Review Council — M19a (GameRewind Rename, Data Migration & Custom-Folder Installer)

**Date:** 2026-11-24  
**Scope:** Full rename to **GameRewind**, automatic `%LOCALAPPDATA%\GameHub` → `%LOCALAPPDATA%\GameRewind` migration, custom-folder per-user Inno Setup installer (`DisableDirPage=no`, `UsePreviousAppDir=no`, writable check, desktop shortcut task, legacy Game Hub cleanup), GitHub repository rename to `adhamelgohary-dev/game-rewind`, and updated Windows CI tests.

## Advocate
- Every user-facing string, window title, About page, Arabic/English UI catalog, icon, manifest (`GameRewind.manifest`), `version_info.txt`, PyInstaller spec (`gamerewind.spec`), installer (`installer.iss`), wizard banner (`wizard-sidebar.bmp`), docs, and GitHub repo (`game-rewind`) now cleanly reflect **GameRewind**.
- `migrate_legacy_data_root()` uses read-only SQLite backup + integrity verification + reparse-point checks + atomic staging, preserves custom `store-location.json` pointers without copying media unnecessarily, runs strictly AFTER `ProtectionGuard.self_check()` so blocked startups still perform zero writes, and leaves `%LOCALAPPDATA%\GameHub` intact as a fallback.
- `packaging/installer.iss` always displays the destination folder page (`DisableDirPage=no`, `UsePreviousAppDir=no`), validates destination writability without admin elevation (`PrivilegesRequired=lowest`), adds an optional desktop shortcut checkbox, silently removes legacy Game Hub shortcuts/files/uninstall entries, and cleans up previous GameRewind directories when the user changes folders on upgrade.

## Critic
- Local machine lacks Inno Setup 6 (`ISCC.exe`), so the compiled installer wizard and upgrade/folder-change scripts will be executed end-to-end on the `windows-2025` GitHub Actions runner during release (`M22`) and inspected by Red-Team Agent G (`M21`).
- Static AST and packaging tests (`tests/test_packaging.py`) and 213 unit/UI tests + `ruff check .` all passed cleanly.

## Neutral Analyst
- Internal Python package name `gamehub` was deliberately preserved per `DECISIONS.md` to avoid high-risk import churn while delivering 100% user-facing `GameRewind` branding.
- All 5 installer/migration requirements (custom folder, writable validation, optional desktop shortcut, legacy Game Hub cleanup, data preservation & automatic migration) are covered by unit tests and CI workflow checks.

## Judge Verdict
**APPROVED** — Commit, tag `m19a`, push to `adhamelgohary-dev/game-rewind`, and proceed directly to **M20 (Simplified Translations & Mods)**.
