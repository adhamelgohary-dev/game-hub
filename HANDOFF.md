# Handoff

## Design docs

Read [docs/design/README.md](docs/design/README.md) before implementation.

## Next step

M4 local tests, native Ctrl+Alt+N with generated audio, and packaged audio startup pass. Verify the tagged `m4` installer and portable package, then close the Council review and start M5 Last time.

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

- GitHub repository [game-hub](https://github.com/adhamelgohary-dev/game-hub) is verified PRIVATE. Local Git is initialized on main with origin connected.
- [M0 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m0) passed native tray and tagged Windows CI with both release packages smoke-tested.
- [M1 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m1) passed tagged Windows CI with both release packages smoke-tested.
- [M2 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m2) passed tagged Windows CI with both release packages smoke-tested.
- [M3 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m3) passed tagged Windows CI with both release packages smoke-tested.
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
