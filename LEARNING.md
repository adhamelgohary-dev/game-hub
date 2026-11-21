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
