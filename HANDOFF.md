# Handoff

## Design docs

Read [docs/design/README.md](docs/design/README.md) before implementation.

## Next step

Wait at **Owner Gate (v1.2-rc.2)** after delivering `GameRewind-Setup-v1.2.0-rc.2.exe` and `Sample-Translation-Pack.zip` on `C:\Users\adham\Desktop` and publishing GitHub pre-release `GameRewind v1.2.0-rc.2`:
- If the owner reports any bug or polish request on `v1.2.0-rc.2`: fix with small commits + regression tests, bump to `v1.2.0-rc.3`, publish, and repeat.
- Once the owner replies `"verified"`, execute **M23** `[simple]`:
  1. Bump `gamehub/__init__.py` `__version__` from `"1.2.0-rc.2"` to `"1.2.0"`, promote the `## v1.2.0` section in `CHANGELOG.md`, run full `pytest -q`, `ruff check .`, and Review Council gate (`docs/reviews/M23-review.md`).
  2. Commit, tag `v1.2.0`, push to `origin` (`adhamelgohary-dev/game-rewind`), verify Windows CI publishes final `GameRewind v1.2.0` with `GameRewind-Setup-v1.2.0.exe`, `GameRewind-Portable-v1.2.0.zip`, and `SHA256SUMS.txt`.
  3. Copy verified `GameRewind-Setup-v1.2.0.exe` to Desktop and confirm completion to the owner in Egyptian Arabic.

## In progress

Paused cleanly on green `main` at **Owner Gate (v1.2-rc.2)**. Milestones `D-v1.2-rc2`, `M19a` (GameRewind rename + data migration + custom-folder installer), `M20` (Simplified Translations & Mods), `M21` (8-agent Red-Team Security Re-Audit — 0 open findings), and `M22` (`v1.2.0-rc.2` pre-release) are complete, Council-approved, tagged (`m19a`, `m20`, `m21`, `v1.2.0-rc.2`), and pushed. Repository is **PUBLIC** at `https://github.com/adhamelgohary-dev/game-rewind`.

## Fragile spots

- `gamehub/app.py`: Keep `ProtectionGuard.self_check()` strictly BEFORE `migrate_legacy_data_root()`, `SingleInstance.claim_or_activate()`, and before any window creation or DB writes; keep startup TOCTOU `protection_guard.check_once()` before `mods_engine.recover_incomplete()`, hotkeys, and `watcher.start()`; keep 200 ms daemon `os._exit` failsafe armed on guard trigger/failure when `hard_exit_on_emergency=True`; close `instance` first in `finally:`.
- `gamehub/core/sessions/processes.py` & `gamehub/core/capture/windows.py`: `psutil` is strictly banned (`tests/test_packaging.py` + `excludes=['psutil']` in `packaging/gamerewind.spec`). `OpenProcess` is allowed ONLY in `processes.py` with `_QUERY_LIMITED_INFORMATION = 0x1000` on verified non-protected Full-mode targets; `WindowProbe.foreground()` must always gate on `allowed_pids` (`tracker.active_pids()`).
- `gamehub/core/protection/catalog.py` & `protected_games.json`: Keep `strict_load=True`, additive-only `protected_games_override.json` (using `.setdefault()` and forcing new overrides to `strict`), and keep `vgk`, `vgtray.exe`, `vgm.exe`, idle `vgc`/`vgc.exe`, and `EAAntiCheatService` out of active blocklists while keeping all Riot Client binaries (`Riot Client.exe`, `RiotClientServices.exe`, etc.) and Valorant/LoL/2XKO binaries strictly enforced.
- `gamehub/modules/mods/`: Keep case-insensitive `.casefold()` conflict/backup keys, streaming arbitrary-offset PE detection (`_StreamingPeDetector`), `require_child=True` on `remove_item`, relative DB `storage_dir`/`backup_path` (surviving `StoreLocation.move()`), reparse-safe `os.scandir` cleanup, and permanent protected-game lock even if `protection_mode='full'`.
- `packaging/installer.iss`: Keep `DisableDirPage=no`, `UsePreviousAppDir=no`, `PrivilegesRequired=lowest`, `ValidateInstallDir` called in BOTH `NextButtonClick` and `PrepareToInstall` (for `/VERYSILENT` safety), and `RunValidatedQuietUninstaller` validating `IsLocalDrivePath` + exact parent-dir match before `FileExists`.
- `gamehub/core/i18n/catalog.py`: Never place Unicode BiDi isolate characters inside `QFileDialog` glob parentheses `(*.exe)` / `(*.zip)` and never reintroduce `&[A-Za-z]` mnemonic ampersands in `.tr(...)` labels.

Last worked on by: Gemini 4 Neon (High), 2026-11-24

## Run the app and tests

From the PowerShell repository root:

```powershell
.\.venv\Scripts\python.exe -m gamehub.app
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging/gamerewind.spec
```

## Project map

- `docs/design/` — requirements, flows, architecture, storage, interfaces, v1.2 plan, simplified Mods spec, and mockups.
- `docs/reviews/` & `docs/reviews/security/` — Council deliberations, verdicts, and 8-agent Red-Team security audit reports.
- `docs/SECURITY-AUDIT-v1.2.md` & `docs/SECURITY-AUDIT-v1.2-AR.md` — consolidated English and Egyptian Arabic v1.2 security audit reports.
- `docs/TESTING.md` & `docs/USER-GUIDE-AR.md` — Windows manual acceptance checklist and Arabic user guide.
- `gamehub/app.py` and `gamehub/single_instance.py` — desktop entry point, zero-background window, and local instance control.
- `gamehub/core/protection/` — fail-closed `ProtectionGuard`, `ProtectedGamesCatalog`, `protected_games.json`, and `LifecycleCoordinator`.
- `gamehub/core/library/` and `gamehub/core/storage/` — read-only launcher detectors, scan folders, cover cache, SQLite Schema v7, and automatic `GameHub` → `GameRewind` data migration.
- `gamehub/core/sessions/` and `gamehub/core/capture/` — pure Win32 process probing (zero `psutil`), session state, and foreground-only WGC.
- `gamehub/modules/memory/` and `gamehub/modules/mods/` — voice/text notes, Last time card, Controls, and crash-safe Translations & Mods engine.
- `packaging/` and `.github/workflows/windows.yml` — `gamerewind.spec`, `GameRewind.manifest`, `version_info.txt`, custom-folder `installer.iss`, and SHA-pinned Windows CI release workflow.
- `DECISIONS.md` — decisions and rationale.
- `LEARNING.md` — milestone learning notes.

## Known issues and blockers

- GitHub repository [game-rewind](https://github.com/adhamelgohary-dev/game-rewind) is verified PUBLIC (renamed from `game-hub` in M19a; GitHub preserves redirects).
- Local development host has Kaspersky active (WinDefend stopped) and lacks local Inno Setup 6 (`ISCC.exe`), so installer compilation, custom-folder fresh/legacy-upgrade/folder-change/uninstall testing, and `MpCmdRun.exe` Defender scanning execute automatically on the isolated `windows-2025` GitHub Actions runner before publishing release assets.
- Code signing via SignPath Foundation is scaffolded in `.github/workflows/windows.yml` (`SIGNPATH_ENABLED`), awaiting SignPath project approval.

## Open questions for owner

- Verify all 10 items in the `GameRewind v1.2.0-rc.2` Egyptian Arabic click checklist and reply `"verified"` when ready to cut final `GameRewind v1.2.0`.

## Future ideas

See [extensibility](docs/design/07-extensibility.md) for the specified roadmap.
