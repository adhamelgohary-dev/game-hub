# Handoff

## Design docs

Read [docs/design/README.md](docs/design/README.md) before implementation.

## Next step

Wait at **Owner Gate (v1.2)** after delivering `GameHub-Setup-v1.2.0-rc.1.exe` on `C:\Users\adham\Desktop` and publishing GitHub pre-release `v1.2.0-rc.1`:
- If the owner reports any bug or polish request on `v1.2.0-rc.1`: fix with small commits + regression tests, bump to `v1.2.0-rc.2`, publish, and repeat.
- Once the owner replies `"verified"` and chooses a **Part 5 Rename variant** (`GameRewind`, `Rewind Games`, `PlayRewind`, or keep `Game Hub`), execute **M19** `[simple]` (apply rename if selected, bump version to `1.2.0`, run full verification + Council review, and publish final `Game Hub v1.2.0`).
- Once the owner approves `docs/design/12-mods-and-arabizations.md` + `docs/design/mockups/mods-arabizations.html`, execute **M20 (Part 6 — Mods & Arabizations)** `[complex]`.

## In progress

Paused cleanly on green `main` at **Owner Gate (v1.2)**. All v1.2 RC1 implementation milestones (`D-v1.2`, `M14`, `M15`, `M16`, `M17`, `M18`) are complete, Council-approved, tagged (`m14`–`m18`, `v1.2.0-rc.1`), and pushed. Repository is **PUBLIC** (`adhamelgohary-dev/game-hub`).

## Fragile spots

- `gamehub/app.py`: Keep `ProtectionGuard.self_check()` strictly BEFORE `SingleInstance.claim_or_activate()` and before any window creation or DB writes; keep `watcher.start()` strictly after all `EventBus.subscribe(...)` calls; pass `wait=False` during emergency shutdown teardown.
- `gamehub/core/i18n/catalog.py`: Never place Unicode BiDi isolate characters (`\u2066`/`\u2069`) inside `QFileDialog` glob parentheses `(*.exe)` / `(*.png ...)` and never reintroduce `&` mnemonic ampersands in `.tr(...)` labels — `tests/test_i18n_and_settings_ui.py` enforces AST `.tr()` parity, mnemonic-free labels, and `QDir.match` validity.
- `gamehub/core/protection/catalog.py` & `protected_games.json`: Keep `sys._MEIPASS` resolution in `_default_bundled_catalog_path()` and `strict_load=True` fail-closed loading; never add persistent `EAAntiCheatService` to `anti_cheat_services`.
- `gamehub/core/storage/media.py` and `location.py`: Preserve Windows directory pinning, `lstat()` reparse-point checks, and `PRAGMA user_version` verification for all managed media and store moves.
- `tests/test_packaging.py`: Static AST/regex security scan enforces Layer 1 anti-cheat invariants (`OpenProcess` only in `processes.py`, zero `SendInput`/`SetWindowsHookEx`/`ReadProcessMemory`, `asInvoker`, `upx=False`) and offline boundaries (update allowlist cleanly when adding strictly opt-in `steamgriddb.py` in M16).

Last worked on by: Gemini 4 Neon (High), 2026-11-24

## Run the app and tests

From the PowerShell repository root:

```powershell
.\.venv\Scripts\python.exe -m gamehub.app
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging/gamehub.spec
```

## Project map

- `docs/design/` — requirements, flows, architecture, storage, interfaces and implementation plan.
- `docs/reviews/` — Council deliberations and verdicts.
- `docs/TESTING.md` — Windows manual acceptance checklist.
- `gamehub/app.py` and `gamehub/single_instance.py` — desktop entry point, tray, and local instance control.
- `gamehub/core/library/` and `gamehub/core/storage/` — detector adapters, source models, and SQLite.
- `gamehub/core/sessions/` and `gamehub/core/events.py` — process identity, session state, and Qt event delivery.
- `gamehub/core/capture/` and `gamehub/core/storage/screenshots.py` — foreground privacy checks, WGC and the screenshot ring.
- `gamehub/core/audio/`, `gamehub/core/hotkeys/` and `gamehub/modules/memory/` — voice capture, global shortcuts and the session note prompt.
- `gamehub/ui/library_view.py` — library table and manual executable actions.
- `tests/test_app.py` — window, local activation, and entry point tests.
- `packaging/` and `.github/workflows/windows.yml` — Windows bundle, installer, and release workflow.
- `DECISIONS.md` — decisions and rationale.
- `LEARNING.md` — milestone learning notes.

## Known issues and blockers

- GitHub repository [game-hub](https://github.com/adhamelgohary-dev/game-hub) is verified PUBLIC (switched in M12a after clean full-history `gitleaks 8.30.1` and 561-blob PII audit). Local Git is on `main` with `origin` connected.
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
