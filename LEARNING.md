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
