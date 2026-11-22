# Learning guide

## D — Design

A requirement describes what someone can verify. A module boundary says who owns the work and what information crosses that boundary. A database transaction updates related rows together, while staged media writes let the app recover when Windows closes it between a file move and a DB update.

Read in this order:

1. [Design summary](docs/design/README.md)
2. [Requirements](docs/design/01-requirements.md)
3. [Architecture](docs/design/03-architecture.md)
4. [Data model](docs/design/04-data-model.md)
5. [Interfaces](docs/design/05-interfaces.md)

Try it yourself. Trace what happens when a game closes while a voice note is still recording. Identify who owns the session ID and what should happen if the note cannot be written.

## M0 — Setup

Qt's event loop handles clicks, timers and incoming local messages. Closing the window can hide it while the tray keeps the app running. A lock elects the first instance, and a local signal lets later launches ask it to reopen. PyInstaller bundles Python and Qt with the application, and the installer copies the bundle into a per-user folder.

Read [app.py](gamehub/app.py), [single_instance.py](gamehub/single_instance.py), [test_app.py](tests/test_app.py), then the [Windows workflow](.github/workflows/windows.yml).

Try it yourself. Follow the close event through the window and explain why the Quit tray action uses a different path.

## M1 — Library detection

A detector turns launcher-specific metadata into the same kind of game record. The database uses the launcher and its stable game ID to recognize a game on the next refresh. A partial scan can update valid entries without marking unseen games uninstalled. The library controller runs scans on a worker so Qt keeps handling input.

Read [steam.py](gamehub/core/library/steam.py), [models.py](gamehub/core/library/models.py), [library.py](gamehub/core/storage/library.py), and [library_controller.py](gamehub/ui/library_controller.py).

Try it yourself. Add one broken manifest to a synthetic library fixture and check which entries remain after refresh.

## M2 — Session tracking

Windows can reuse process IDs. Pairing the ID with the creation time tells the watcher which specific process it saw. A session can span several matching processes, and a brief permission error leaves the last reliable checkpoint intact. The event bus sends committed changes to Qt so the worker never updates widgets directly.

Read [processes.py](gamehub/core/sessions/processes.py), [tracker.py](gamehub/core/sessions/tracker.py), [session storage](gamehub/core/storage/sessions.py), and [events.py](gamehub/core/events.py).

Try it yourself. Change a synthetic sample so a previous PID appears with a different creation time. Predict the event sequence and check it with pytest.

## M3 — Screenshots

A foreground capture request binds a window handle to the watched process and session. It expires quickly and is checked again when a frame arrives. A ring keeps the newest images by evicting older entries as new ones are saved. The file is staged before SQLite references it, and startup recovery removes abandoned managed files.

Read [service.py](gamehub/core/capture/service.py), [windows.py](gamehub/core/capture/windows.py), [screenshots.py](gamehub/core/storage/screenshots.py), and [last_moments.py](gamehub/ui/last_moments.py).

Try it yourself. Change the buffer size in a test, save two additional frames, and verify which images remain when the session closes.

## M4 — Notes and shortcuts

Windows posts a message to the app when a registered shortcut is pressed. The recorder opens one input stream, copies a bounded number of audio samples, and encodes them when the user stops. The note keeps the session ID chosen at the start. If saving fails, the encoded audio can be retried without recording again.

Read [hotkeys](gamehub/core/hotkeys/windows.py), [recorder.py](gamehub/core/audio/recorder.py), [notes_controller.py](gamehub/modules/memory/notes_controller.py), and [note storage](gamehub/core/storage/notes.py).

Try it yourself. Follow the code from Ctrl+Alt+N to a saved note, then run the test that switches foreground games before stopping the note.

## M5 — Last time card and Play

Reading related tables inside a single SQLite `BEGIN DEFERRED` snapshot keeps the Last time card consistent even while background workers write new sessions. Instead of passing file paths directly to a media decoder, Game Hub validates the managed path and ownership in SQLite, reads bounded bytes, and hands Qt Multimedia an in-memory buffer. Launching from **Play** records a short-lived launch attempt ID that the process watcher consumes on the matching start so the user never sees two cards or hears autoplay twice.

Read [memory.py](gamehub/core/storage/memory.py), [launcher.py](gamehub/core/library/launcher.py), [player.py](gamehub/core/audio/player.py), [last_time_card.py](gamehub/modules/memory/last_time_card.py), and [last_time_controller.py](gamehub/modules/memory/last_time_controller.py).

Try it yourself. Trace what happens when you click **Play**, then **Launch**, and the watcher observes the game start 5 seconds later versus 95 seconds later.

## M6 — Controls card and timeline

Schema migrations upgrade an existing database safely by writing a consistent backup (`gamehub.db-v3.bak`) before applying DDL and bumping `PRAGMA user_version` inside the same transaction. Uploaded user images are never copied raw: Game Hub reads bounded bytes, restricts Pillow to explicit image formats, applies EXIF orientation, strips original metadata, and writes managed WebP files under `media/<game_id>/controls/`. Sharing one `CaptureScheduler` worker and one `VoicePlayer` across features prevents overlapping native captures and overlapping audio clips.

Read [controls.py](gamehub/core/storage/controls.py), [controls_controller.py](gamehub/modules/memory/controls_controller.py), [game_page.py](gamehub/ui/game_page.py), and [memory.py](gamehub/core/storage/memory.py).

Try it yourself. Open a game's page, delete one voice note file from disk while keeping the database row, and verify that the rest of the session timeline stays usable.

## M7 — Settings and Arabic/English

Changing OS-backed settings like global hotkeys or Windows startup requires coordinating external side effects with SQLite so a failure never leaves the app half-configured. A two-phase probe-and-rebind lets users swap two shortcuts cleanly while guaranteeing that a conflict with another application never unregisters a working shortcut. For offline data-folder moves, pausing background workers, copying via SQLite's online backup API into a pinned staging directory, verifying schema and media sizes, and only then replacing `store-location.json` keeps user data intact even if a move fails mid-way.

Read [settings.py](gamehub/core/settings.py), [location.py](gamehub/core/storage/location.py), [windows.py](gamehub/core/hotkeys/windows.py), [i18n](gamehub/core/i18n/__init__.py), and [settings_view.py](gamehub/ui/settings_view.py).

Try it yourself. Run `tests/test_i18n_and_settings_ui.py` after adding a new `self.tr(...)` string to any widget and see how the AST parity test immediately reports the missing Arabic entry.

## M8 — Packaging and release

Shipping a desktop app means verifying more than the first install: in-place upgrades must clear stale runtime libraries from `_internal` without touching `%LOCALAPPDATA%\GameHub\`, and uninstalling must remove the optional per-user Windows startup entry while leaving user history intact. Stripping Python from `PATH` and clearing `PYTHONHOME`/`PYTHONPATH` during smoke tests proves the frozen PyInstaller bundle is self-contained, and static AST checks ensure offline and non-invasive boundaries hold across every release.

Read [gamehub.spec](packaging/gamehub.spec), [installer.iss](packaging/installer.iss), [windows.yml](.github/workflows/windows.yml), [test_packaging.py](tests/test_packaging.py), and [USER-GUIDE-AR.md](docs/USER-GUIDE-AR.md).

Try it yourself. Run `python -m pytest tests/test_packaging.py` and trace how the test suite statically enforces zero network imports, zero game-injection Win32 calls, and full third-party license coverage.
