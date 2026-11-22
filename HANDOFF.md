# Handoff

## Design docs

Read [docs/design/README.md](docs/design/README.md) before implementation.

## Next step

Wait for owner approval at **Owner Gate 1**, then execute in order:
1. **M11 (Part D — Fluent UI redesign)** `[complex]` once owner approves `docs/design/mockups/` (or requests tweaks):
   - Implement Windows 11 / Fluent QSS theme engine (`gamehub/ui/theme.py` for Dark, Light, and System themes, live theme switching wired to `SettingsChanged`), persistent sidebar navigation, responsive cover-art Library grid (discovering local Steam `appcache/librarycache` and Epic covers with stylized placeholders), redesigned Game page, Last-time card, Note prompt, and Settings view, smooth transitions (`QGraphicsOpacityEffect` / `QPropertyAnimation`), multi-size app icon (`packaging/assets/GameHub.ico`), and Inno Setup wizard branding BMPs.
   - Update README screenshots with real captured app screens, run full tests + Review Council (`docs/reviews/M11-review.md`), tag plain internal git tag `m11`.
2. **M12b (Parts F & G — Release cleanup + `v1.1.0-rc.1`)** `[complex]`:
   - Once owner gives `"OK"` on the `m0–m8` release cleanup list: convert `m8` release to `v1.0.0` (keep `m8` tag) and delete GitHub Releases `m0–m7` (keep tags `m0–m7`).
   - Update `gamehub/__init__.py` (`__version__ = "1.1.0-rc.1"`), `CHANGELOG.md` (`## v1.1.0-rc.1` with Added/Changed/Fixed/Security), and `tests/test_packaging.py`; push tag `v1.1.0-rc.1` so Windows CI builds and publishes `GameHub-Setup-v1.1.0-rc.1.exe`, `GameHub-Portable-v1.1.0-rc.1.zip`, and `SHA256SUMS.txt`.
   - Download/copy `GameHub-Setup-v1.1.0-rc.1.exe` to owner's Desktop (`%USERPROFILE%\Desktop\`) and provide the 10-item click-only test checklist in Egyptian Arabic.
3. **M13 (Part G — Final `v1.1.0`)** `[simple]`: After owner replies `"verified"`, update `__version__ = "1.1.0"` and `CHANGELOG.md` (`## v1.1.0`), tag and publish `v1.1.0`.

## In progress

Paused cleanly on green `main` at **Owner Gate 1** (mockups + `m0–m8` cleanup approval). `D-v1.1`, `M9`, `M10`, and `M12a` are complete, reviewed, committed, and pushed. Repository is now **PUBLIC**.

## Fragile spots

- `gamehub/app.py`: Keep `watcher.start()` strictly after all `EventBus.subscribe(...)` calls, and keep `SingleInstance` anchored on `effective_default` so data-folder relocation never permits a second concurrent instance.
- `gamehub/core/i18n/catalog.py`: Never place Unicode BiDi isolate characters (`\u2066`/`\u2069`) inside `QFileDialog` glob parentheses `(*.exe)` / `(*.png ...)` — `tests/test_i18n_and_settings_ui.py` enforces both AST `.tr()` parity and `QDir.match` validity.
- `gamehub/core/storage/media.py` and `location.py`: Preserve Windows directory pinning, `lstat()` reparse-point checks, and `PRAGMA user_version` verification for all managed media and store moves.
- `packaging/gamehub.spec`, `packaging/installer.iss`, and `packaging/THIRD_PARTY_NOTICES.txt`: Keep `PySide6-Addons`, `third-party/FFmpeg/LGPL-2.1.txt`, `[InstallDelete]` on `{app}\_internal`, and `[Registry]` `uninsdeletevalue` cleanup intact.

Last worked on by: Gemini 4 Neon (High), 2026-11-23

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
