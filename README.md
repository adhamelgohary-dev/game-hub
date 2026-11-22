# Game Hub

Pick up a Windows PC game after a break with the notes, screenshots, and controls you saved last time.

## Features

The app opens a local library and stays available in the Windows notification area. It discovers Steam, Epic Games Store, and supported local Xbox games. You can also add a game by selecting its executable. The tray watcher records play sessions, updates playtime, and captures the foreground game window every 30 seconds when supported. Select a game and open **Last moments** to see up to ten screenshots from its previous session. The v1 roadmap adds voice and text notes, a Last time card, pinned controls, a timeline, and an English/Arabic interface. [Launcher detection and limits](docs/launcher-detection.md)

[View the library with sample games](https://github.com/adhamelgohary-dev/game-hub/releases/download/m1/GameHub-Library.png).

## Download and install

Use Windows 10 version 1809 or later, or Windows 11, on a 64-bit PC.
Window screenshots require Windows 10 version 1903 or later, and Windows capture access for the game.

1. Sign in to GitHub with access to the [private releases](https://github.com/adhamelgohary-dev/game-hub/releases).
2. Open the latest milestone release and download **GameHub-Setup.exe** from **Assets**.
3. Double-click the download, follow the installer, then open **Game Hub** from the Start menu.

For a portable install, download **GameHub-Windows-x64.zip**, extract the entire folder, and double-click **GameHub.exe** inside it. Keep the runtime files alongside the executable.

## Run from source (for developers)

Install Python 3.12 x64, then run these commands in PowerShell from the repository root.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m gamehub.app
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

## Folder structure

```text
gamehub/                       Windows desktop application
  core/                        Shared game discovery and storage
    library/                   Steam, Epic and Xbox detectors and library service
    sessions/                  Windows process sampling and session tracking
    capture/                   Exact-window capture and screenshot scheduling
    storage/                   Versioned local SQLite database and repository
  ui/                          Library view and background task controller
tests/                         Automated test suite
  fixtures/                    Synthetic launcher manifests
docs/                          Windows manual checklist and project documentation
  design/                      Requirements and design contracts
  reviews/                     Review Council records
packaging/                     PyInstaller and Inno Setup configuration
.github/                       Contribution templates and GitHub Actions
```

## Tech stack

Python 3.12+, PySide6, pytest, Ruff, PyInstaller, Inno Setup, and GitHub Actions. Later v1 milestones use SQLite for local data and Windows Graphics Capture for screenshots.

## Roadmap

- **v1** — Game Memory for Windows 10 and 11.
- **v2** — Replay clips and optional Google Drive backups.
- **v3** — Local voice transcription and note search.
- **Later** — Launch Doctor and a mods and Arabic translations installer.

Read the [design](docs/design/README.md), [progress](PROGRESS.md), or [handoff](HANDOFF.md) for implementation details.

## العربية

يساعدك Game Hub على متابعة ألعابك ووقت اللعب. تعرض المكتبة الألعاب المكتشفة ويمكنك إضافة لعبة يدويًا. للتثبيت، افتح صفحة الإصدارات الخاصة على GitHub ونزّل GameHub-Setup.exe ثم شغّله.

## License

All rights reserved, private for now.
