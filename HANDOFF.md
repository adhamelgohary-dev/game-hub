# Handoff

## Design docs

Read [docs/design/README.md](docs/design/README.md) before implementation.

## Next step

Wait at **Owner Gate (v1.2 RC2)** after publishing GitHub pre-release `GameRewind v1.2.0-rc.2` (with `GameRewind-Setup-v1.2.0-rc.2.exe`, `GameRewind-Portable-v1.2.0-rc.2.zip`, and `SHA256SUMS.txt` attached, and installer copied to `C:\Users\adham\Desktop`):
- If the owner reports any bug or polish request on `v1.2.0-rc.2`: fix with small commits + regression tests, bump to `v1.2.0-rc.3`, verify, review, and publish.
- Once the owner replies `"verified"`: execute **M21** `[simple]` (bump `gamehub/__init__.py` to `1.2.0`, add `## v1.2.0` to `CHANGELOG.md`, run full tests/lint/build/Council review, tag `v1.2.0`, and publish final `GameRewind v1.2.0`).

## In progress

Paused cleanly on green `main` at **Owner Gate (v1.2 RC2)**. `m19a` (GameRewind rename + custom-folder installer), `m20` (Translations & Mods), and **M20b (`v1.2.0-rc.2` Security Hardening)** are complete, Council-approved (`docs/reviews/M20b-v1.2.0-rc.2-review.md`), tagged (`v1.2.0-rc.2`), and pushed. Repository is **PUBLIC** (`adhamelgohary-dev/game-rewind`).

## Fragile spots

- `gamehub/app.py`: Keep `ProtectionGuard.self_check()` strictly BEFORE `SingleInstance.claim_or_activate()`, legacy data migration, and any window creation or DB writes; keep startup TOCTOU `check_once()` before `mods_engine.recover_incomplete()`, hotkey binding, and `watcher.start()`; never show a modal `QMessageBox` on startup refusal or runtime fail-closed; keep `wait=False` and `os._exit(...)` (`hard_exit_on_emergency=True`) on emergency shutdown; keep `CaptureScheduler` paused unless a Full-mode game is active.
- `gamehub/core/sessions/processes.py` & `tests/test_packaging.py`: `psutil` is permanently banned (including in tests and `gamerewind.spec` `excludes=['psutil']`); `OpenProcess` is allowed ONLY in `processes.py` with `PROCESS_QUERY_LIMITED_INFORMATION` (`0x1000`) and never on `DEFAULT_NEVER_OPEN_EXES`, catalog/protected exes, or launchers.
- `gamehub/core/i18n/catalog.py`: Never place Unicode BiDi isolate characters (`\u2066`/`\u2069`) inside `QFileDialog` glob parentheses `(*.exe)` / `(*.png ...)` and never reintroduce `&` mnemonic ampersands in `.tr(...)` labels — `tests/test_i18n_and_settings_ui.py` enforces AST `.tr()` parity, mnemonic-free labels, and `QDir.match` validity.
- `gamehub/core/protection/catalog.py`, `guard.py` & `protected_games.json`: Keep `sys._MEIPASS` resolution in `_default_bundled_catalog_path()`, `strict_load=True` fail-closed loading, strictly additive override merging, `QueryUnbiasedInterruptTime` sleep-safe watchdog clock, and exclusion of persistent `EAAntiCheatService` / `vgc` (`vgc.exe`) from startup refusal while keeping Riot Client in `always_strict_launchers`.
- `gamehub/modules/mods/`: Keep case-insensitive `.casefold()` conflict/backup keys, relative `storage_dir`/`backup_path` under `<data_root>/mods`, PE header (`MZ`+`PE\0\0`) rejection, verify-before-replace SHA-256 atomic writes, deep `install_dir` protected-game scan, and `data_root` overlap rejection.
- `gamehub/core/storage/media.py` and `location.py`: Preserve Windows directory pinning, `lstat()` reparse-point checks, and `PRAGMA user_version` verification for all managed media and store moves.
- `packaging/installer.iss`: Preserve `IsForbiddenDestination`, non-empty folder check, `IsDirWritable`, and `RunValidatedQuietUninstaller` (`InstallLocation` + `unins*.exe` validation).

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

- `docs/design/` — requirements, flows, architecture, storage, interfaces, v1.2 plan, and Mods design.
- `docs/reviews/` and `docs/reviews/security/` — Council deliberations, verdicts, and Red-Team security audit reports.
- `docs/TESTING.md` — Windows manual acceptance checklist.
- `gamehub/app.py` and `gamehub/single_instance.py` — desktop entry point, zero-presence lifecycle, and local instance control.
- `gamehub/core/library/` and `gamehub/core/storage/` — read-only launcher detectors (Steam, Epic, Riot, GOG, EA, Ubisoft, Battle.net, itch, registry-only Xbox, Scan Folders), cover store, and SQLite Schema v7.
- `gamehub/core/protection/` — fail-closed `ProtectionGuard`, `ProtectedGamesCatalog`, `protected_games.json`, and `LifecycleCoordinator`.
- `gamehub/core/sessions/` and `gamehub/core/events.py` — Win32 `GetProcessTimes` process probe, passive watcher, session state, and Qt event delivery.
- `gamehub/core/capture/` and `gamehub/core/storage/screenshots.py` — foreground privacy checks, borderless WGC, and the screenshot ring.
- `gamehub/core/audio/`, `gamehub/core/hotkeys/` and `gamehub/modules/memory/` — voice capture, global shortcuts, Last-time card, controls, and session notes.
- `gamehub/modules/mods/` and `gamehub/ui/mods_view.py` — declarative Translations & Mods engine, crash-safe journal, and plain-language UI.
- `packaging/` and `.github/workflows/windows.yml` — PyInstaller (`gamerewind.spec`), Inno Setup (`installer.iss`), and SHA-pinned Windows release workflow.
- `DECISIONS.md` — decisions and rationale.
- `LEARNING.md` — milestone learning notes.

## Known issues and blockers

- GitHub repository [game-rewind](https://github.com/adhamelgohary-dev/game-rewind) (renamed from `game-hub` in M19a) is verified PUBLIC. Local Git is on `main` with `origin` connected.
- [M0 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m0) passed native tray and tagged Windows CI with both release packages smoke-tested.
- [M1 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m1) passed tagged Windows CI with both release packages smoke-tested.
- [M2 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m2) passed tagged Windows CI with both release packages smoke-tested.
- [M3 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m3) passed tagged Windows CI with both release packages smoke-tested.
- [M4 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m4) passed tagged Windows CI with both release packages smoke-tested.
- [M5 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m5) passed tagged Windows CI with both release packages smoke-tested.
- [M6 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m6) passed tagged Windows CI with both release packages smoke-tested.
- [M7 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m7) passed tagged Windows CI with both release packages smoke-tested.
- [M8 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m8) (`1.0.0`) passed tagged Windows CI including Python-free `PATH` portable & installed startup, in-place upgrade, silent uninstall, and user-data preservation.
- Native Windows hotkey conflict preservation (`code=1409`), verified `StoreLocation` relocation, and live Arabic RTL layout switching passed locally; 150%/200% DPI visual inspection and Windows screen-reader traversal remain manual acceptance checks.
- Native `Ctrl+Alt+C` binding and uploaded controls/timeline persistence across reopen were verified locally; live in-game `Ctrl+Alt+C` capture remains part of manual game capture acceptance.
- Native `Ctrl+Alt+L`, Last time card rendering, and Qt Multimedia Ogg Vorbis playback were verified locally alongside Steam discovery and registered `steam://` URI handler; live interactive Steam game launch and exclusive fullscreen switching remain manual acceptance items.
- Native WGC accepted 12 frames from a synthetic Windows 11 test window, retained and displayed the newest ten, and skipped unfocused and minimized cases. Protected games and Windows 10 capture hardware remain unverified.
- Native Ctrl+Alt+N and the stored Ogg note were verified with generated audio. Microphone denial and recording limits were exercised with input doubles.
- The M2 native watcher produced one completed session row and matching tray states. The final 120-second run measured 0.69% of one core for the watcher and 0.066% of total CPU capacity for the app.
- Live Steam entries loaded and persisted. Epic manifests were unavailable and no accessible Xbox titles were found on this machine. Fixture coverage verified those adapters. [Launcher limitations](docs/launcher-detection.md)
- Windows capture and installer behavior need real-machine verification in their assigned milestones.

## Open questions for owner

- Which Windows 10/11 installations and real launchers can be used for manual acceptance? Keep automated fixtures synthetic in the meantime.
- Which local alternative data folder should be used to verify relocation? Default to the specified LocalAppData path and use a disposable temporary profile for development checks.

## Future ideas

See [extensibility](docs/design/07-extensibility.md) for the specified roadmap.
