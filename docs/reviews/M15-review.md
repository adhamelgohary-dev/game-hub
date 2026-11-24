# Review Council — M15 (Part 2: Find All Games — Launchers, Scan Folders & Plain Scan Warnings)

**Date:** 2026-11-24  
**Test verification:** `204 passed in 13.93s`, `ruff check .` clean (0 errors).

## Advocate
- Fixed both real-PC root causes verified live on this Windows 11 machine:
  - **Epic Games (`epic.py`):** Scans legacy `ProgramData\...\Manifests\*.item`, modern per-user `HKCU\...\Uninstall\EpicGames-*` (`EpicAppId`), and `LauncherInstalled.dat`. Live PC check now discovers all 3 Epic titles (`Death Stranding`, `Fortnite`, `Hue`) with `state=complete, diag=()`.
  - **Steam (`steam.py`):** Skips offline/unmounted/removable/mapped-network drive letters (`GetDriveTypeW` in `{1, 2, 4, 5}`) in `libraryfolders.vdf` without false `steam_index_invalid` warnings while still rejecting UNC paths, symlinks, and inaccessible fixed-drive entries. Live PC check now discovers all 26 Steam titles with `state=complete, diag=()`.
- Added read-only detector plugins for **Riot Games**, **GOG**, **EA app**, **Ubisoft Connect**, **Battle.net**, **itch.io**, and improved **Xbox** (`ShellVisuals` cover discovery), plus **Scan Folders** (`folder_scanner.py` + `FolderDetector` + `ScanFolderDialog`) with helper-exe filtering, symlink safety, depth limits, and persisted include/ignore choices.
- Live PC check discovered **VALORANT** (`riot`, `complete`) and **EA SPORTS FC 27 / FC 26** (`ea`, `complete`) automatically.
- Upgraded `LibraryService` (`ScanIssue`) and `LibraryView` to display plain-language EN & AR scan banners with **Retry** and **Learn more** buttons and zero raw diagnostic codes.

## Critic
- Checked security boundaries: all new detectors are strictly read-only (SQLite `?mode=ro`, `winreg.KEY_READ`, `local_path`/`contained_file` reparse-point checks), no network calls, and `tests/test_packaging.py` static AST security scan still passes cleanly.
- Checked i18n parity: all 11 `GameSource` labels and all new Scan Folder / warning strings passed `test_arabic_catalog_has_full_key_and_placeholder_parity` and zero-mnemonic checks.

## Neutral Analyst
- All 204 unit and UI tests pass, including synthetic fixtures for every new detector, offline-drive Steam VDF handling, Scan Folder helper filtering & persistence, and plain scan banners.

## Judge
**Verdict: APPROVE.** Merge `wip/v1.2-recovery` into `main`, tag `m15`, and proceed immediately to **M16 (Part 3 — Cover Art That Fits)**.
