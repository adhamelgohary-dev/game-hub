# Game Hub

Pick up a Windows PC game after a break with the notes, screenshots, and controls you saved last time.

## Features

The app opens a local library and stays available in the Windows notification area. It discovers Steam, Epic Games Store, and supported local Xbox games. You can also add a game by selecting its executable. The tray watcher records play sessions, updates playtime, and captures the foreground game window every 30 seconds when supported. Select a game and choose **Play** (or start a tracked game externally, or press **Ctrl+Alt+L**) to open the **Last time** card with prior play summary, voice note playback, text note, recent screenshots, and pinned controls before launching. Open any game to pin controls images (via **Ctrl+Alt+C** in-game or local image upload), save strategy notes, and browse its full chronological session timeline. Save a voice or text note from the game's close prompt, or press **Ctrl+Alt+N** during a tracked game to start or stop a voice note. Open **Settings** to switch between English and Arabic (with RTL layout), customize capture limits, hotkeys, and Windows startup, or move the local data folder safely. [Launcher detection and limits](docs/launcher-detection.md)

[View the library with sample games](https://github.com/adhamelgohary-dev/game-hub/releases/download/m1/GameHub-Library.png).

## Default shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+Alt+N` | Start or stop a 60-second voice note for the focused tracked game |
| `Ctrl+Alt+L` | Reopen the Last time card |
| `Ctrl+Alt+C` | Pin a controls screenshot of the focused tracked game |

All shortcuts can be customized or disabled in **Settings**. For games that run in exclusive fullscreen, use **Play** inside Game Hub to review your Last time card before launching, or press `Alt+Tab` and `Ctrl+Alt+L`.

## Download and install

Use Windows 10 version 1809 or later, or Windows 11, on a 64-bit PC. No Python installation is required.
Window screenshots require Windows 10 version 1903 or later, and Windows capture access for the game.

1. Sign in to GitHub with access to the [private releases](https://github.com/adhamelgohary-dev/game-hub/releases).
2. Open the latest milestone release and download **GameHub-Setup.exe** from **Assets**.
3. Double-click the download, follow the per-user installer (no administrator rights required), then open **Game Hub** from the Start menu.

For a portable install, download **GameHub-Windows-x64.zip**, extract the entire folder, and double-click **GameHub.exe** inside it. Keep the `_internal` runtime folder alongside the executable.

To upgrade, run the newer **GameHub-Setup.exe** over your existing installation; your local data under `%LOCALAPPDATA%\GameHub\` (or your chosen data folder) is preserved. To uninstall, remove **Game Hub** from Windows Settings → Installed apps.

## Privacy and local data

- Game Hub v1 runs **100% offline** with zero network requests, no accounts, and no telemetry.
- Game Hub never injects overlays, hooks games, or reads game memory; it uses public Windows process metadata and exact-window Windows Graphics Capture.
- All library records, session history, screenshots, voice notes, controls, and logs remain in your local data folder (`%LOCALAPPDATA%\GameHub\` by default) and can be moved safely from **Settings**.

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
  core/                        Shared game discovery, settings, localization, and storage
    library/                   Steam, Epic and Xbox detectors, launcher dispatch and library service
    sessions/                  Windows process sampling and session tracking
    capture/                   Exact-window capture and screenshot scheduling
    audio/                     Local microphone recording, Ogg encoding and voice playback
    hotkeys/                   Windows shortcut registration and atomic batch rebinding
    i18n/                      English and Arabic translation catalog and RTL switching
    storage/                   Versioned SQLite database, media safety, and store relocation
    settings.py                Validated settings service and change notifications
    startup.py                 Per-user Windows startup registration
  modules/                     Feature modules
    memory/                    Last time card, session notes, controls pinning and memory flows
  ui/                          Library, Game page, Settings, and background task controller
tests/                         Automated test suite
  fixtures/                    Synthetic launcher manifests
docs/                          Manual checklist, Arabic user guide, and project documentation
  design/                      Requirements and design contracts
  reviews/                     Review Council records
packaging/                     PyInstaller, Inno Setup, and third-party license notices
.github/                       Contribution templates and GitHub Actions
```

## Tech stack

Python 3.12+, PySide6 (Essentials + Qt Multimedia), SQLite, Windows Graphics Capture, Pillow, PortAudio (`sounddevice`), libsndfile (`soundfile`), psutil, vdf, pytest, Ruff, PyInstaller, Inno Setup, and GitHub Actions.

## Roadmap

- **v1** — Game Memory for Windows 10 and 11.
- **v2** — Replay clips and optional Google Drive backups.
- **v3** — Local voice transcription and note search.
- **Later** — Launch Doctor and a mods and Arabic translations installer.

Read the [design](docs/design/README.md), [progress](PROGRESS.md), or [handoff](HANDOFF.md) for implementation details.

## العربية

يساعدك **Game Hub** على متابعة ألعابك ووقت اللعب وتذكّر آخر ملاحظاتك الصوتية والنصية ولقطات الشاشة وبطاقة التحكم قبل استئناف اللعب—بشكل محلي كامل دون إنترنت. للتثبيت، افتح صفحة الإصدارات الخاصة على GitHub ونزّل `GameHub-Setup.exe` ثم شغّله، ويمكنك تحويل واجهة التطبيق إلى العربية من **الإعدادات**.

اقرأ [دليل المستخدم الكامل بالعربية](docs/USER-GUIDE-AR.md).

## License

All rights reserved, private for now.
