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

## D-v1.1 — Anti-cheat research, zero-background design, and license hygiene

Kernel anti-cheat drivers (such as Vanguard, Easy Anti-Cheat, BattlEye, RICOCHET, and EA Javelin) use `ObRegisterCallbacks` to monitor every `OpenProcess` handle opened to a game, and heuristically watch for unsigned binaries combining screen capture, global hotkeys, and topmost (`WS_EX_TOPMOST`) windows. Designing Game Hub v1.1 to detect protected games purely by `CreateToolhelp32Snapshot` process basenames—without ever calling `OpenProcess` on a protected game—and defaulting them to Strict mode or auto-exit removes that risk. Checking third-party licenses early also paid off: avoiding `PySide6-Fluent-Widgets` (GPLv3/commercial) in favor of pure PySide6 + custom Fluent QSS keeps Game Hub MIT-licensed and eligible for SignPath Foundation free code signing.

Read in this order:

1. [Anti-cheat research](docs/research/anti-cheat.md)
2. [v1.1 Architecture](docs/design/03-architecture.md)
3. [v1.1 Data model (Schema v5)](docs/design/04-data-model.md)
4. [v1.1 Tech stack & license choices](docs/design/06-tech-stack.md)
5. [Fluent UI mockups](docs/design/mockups/index.html)

Try it yourself. Open `docs/design/mockups/index.html` in a browser and toggle between Dark/Light and English/Arabic (RTL) to see how layout direction, badges, and BiDi-isolated shortcuts adapt across all five screens.

## M9 — Zero background and clean process exit

Desktop apps that hide in the system tray or register themselves in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` stay alive even when the user thinks they closed them. Removing `QSystemTrayIcon`, calling `closeAllWindows()` and `quit()` in `GameHubWindow.closeEvent`, and verifying full process teardown in a real subprocess guarantees that closing the window releases every hotkey, thread, and lock cleanly. Removing old v1.0 autostart entries requires handling both installed upgrades (Inno Setup `ValueType: none; Flags: deletevalue dontcreatekey`) and portable users (`remove_legacy_startup_entry()` on startup).

Read [app.py](gamehub/app.py), [startup.py](gamehub/core/startup.py), [installer.iss](packaging/installer.iss), and [test_app.py](tests/test_app.py).

Try it yourself. Run `python -m pytest tests/test_app.py -k residual` and follow how the test launches a real `GameHubWindow`, closes it via a timer, and confirms with `psutil.pid_exists` that zero processes remain.

## M10 — Game-aware lifecycle, passive protection, and borderless capture

Separating **what** games are protected (`protected_games.json`) from **how** the app reacts (`LifecycleCoordinator`) lets users or maintainers update the anti-cheat catalog without changing Python code. Inside `ProcessProbe`, checking `CreateToolhelp32Snapshot` basenames first lets Game Hub detect Valorant, Fortnite, or any Strict-mode title and immediately skip `OpenProcess` so zero process handles ever touch protected games. For borderless Windows Graphics Capture (`draw_border=False`), native Rust/WinRT errors can surface asynchronously when `control.wait()` joins the capture thread, so catching and caching a fallback to `draw_border=None` keeps screenshots reliable across Windows 10 and Windows 11 builds.

Read [protected_games.json](gamehub/core/protection/protected_games.json), [catalog.py](gamehub/core/protection/catalog.py), [lifecycle.py](gamehub/core/protection/lifecycle.py), [processes.py](gamehub/core/sessions/processes.py), and [windows.py](gamehub/core/capture/windows.py).

Try it yourself. Run `python -m pytest tests/test_protection_and_lifecycle.py -k never_opens` to see how the test asserts that `VALORANT-Win64-Shipping.exe` is detected passively while `inspect()` (the `OpenProcess` wrapper) is never called for its PID.

## M12a — Public-readiness audit, EXE metadata, and SignPath signing

Before making a private repository public, scanning only the working tree is not enough—deleted secrets still live inside historical git blobs. Running `gitleaks detect` across every commit and scanning all historical blobs verifies the entire history is clean. Embedding a Windows `VSVersionInfo` resource and an `asInvoker` + `PerMonitorV2` application manifest into `GameHub.exe` gives Windows and antivirus scanners transparent publisher/version metadata, while preparing a SignPath Foundation workflow step lets reproducible GitHub Actions releases earn trusted Authenticode signatures for free once approved.

Read [LICENSE](LICENSE), [SECURITY.md](SECURITY.md), [SIGNPATH-APPLICATION.md](docs/SIGNPATH-APPLICATION.md), [version_info.txt](packaging/version_info.txt), and [windows.yml](.github/workflows/windows.yml).

Try it yourself. Right-click a built `dist/GameHub/GameHub.exe` → **Properties → Details** to see the embedded Product Name, File Version, Description, and MIT copyright fields populated from `packaging/version_info.txt`.

## M11 — Fluent UI, real local cover art, and visual verification

Styling a Qt desktop app cleanly with QSS requires watching two subtle widget defaults: `QLabel.setPixmap(...)` inflates a widget's `sizeHint` unless its horizontal size policy is `Ignored`, and `QScrollArea` content widgets inside `QTabWidget` fall back to the OS light palette unless styled explicitly (`#tabSurface`). Visually inspecting real captured Dark, Light, Game Page, and Arabic RTL screenshots caught both defects before release. Discovering game covers locally from Steam's `appcache/librarycache` (supporting both flat `<appid>_*.jpg` files and modern `<appid>/` / hashed subdirectories) gives users rich library artwork while staying 100% offline.

Read [theme.py](gamehub/ui/theme.py), [covers.py](gamehub/ui/covers.py), [library_view.py](gamehub/ui/library_view.py), [game_page.py](gamehub/ui/game_page.py), and [last_time_card.py](gamehub/modules/memory/last_time_card.py).

Try it yourself. Switch the theme between Dark and Light and the language between English and Arabic in **Settings** and watch `apply_theme` and `apply_language` re-polish every card, badge, and RTL sidebar live without restarting.

## M12b — SemVer releases, checksums, and release-candidate gates

Shipping a public desktop release safely separates internal milestone git tags (`m0–m11`) from public SemVer GitHub Releases (`v1.0.0`, `v1.1.0-rc.1`, `v1.1.0`). Publishing a pre-release (`-rc.1`) first triggers the exact Windows CI packaging, upgrade, uninstall, and checksum pipeline (`SHA256SUMS.txt`) so real-machine verification happens on the identical installer binary users will download before promoting to a final release.

Read [CHANGELOG.md](CHANGELOG.md), [windows.yml](.github/workflows/windows.yml), [installer.iss](packaging/installer.iss), and [M12b-review.md](docs/reviews/M12b-review.md).

Try it yourself. Run `Get-FileHash GameHub-Setup-v1.1.0-rc.1.exe -Algorithm SHA256` in PowerShell and compare the output against the corresponding line in `SHA256SUMS.txt` from the GitHub Release.

## M12c — RC2 catalog verification and clean Qt button typography

In Qt, putting `&` inside button or label strings (such as `&Refresh` or `&Play…`) creates keyboard mnemonics that draw visible underlines on Windows whenever accelerators are shown, and `QDialogButtonBox.StandardButton.Close` inserts a built-in `&Close` automatically. Removing `&` from `.tr()` keys—and enforcing it in the AST i18n parity test—keeps modern Fluent buttons clean while keeping English and Arabic catalogs synchronized. For bundled data files like `protected_games.json`, checking `sys._MEIPASS` explicitly in frozen PyInstaller builds ensures runtime catalog matching matches the source tree across every release candidate.

Read [protected_games.json](gamehub/core/protection/protected_games.json), [catalog.py](gamehub/core/protection/catalog.py), [i18n catalog](gamehub/core/i18n/catalog.py), and [test_protection_and_lifecycle.py](tests/test_protection_and_lifecycle.py).

Try it yourself. Run `python -m pytest tests/test_protection_and_lifecycle.py -k elden_ring` to see how `ProtectedGamesCatalog` routes Elden Ring and Armored Core VI to **Strict** while keeping Dark Souls III in **Full** mode.

## D-v1.2 — Zero-Presence anti-cheat design, real-PC diagnostics, and Part 6 Mods design

Testing assumptions directly against a real Windows 11 machine caught three critical truths before writing a single line of v1.2 code: (1) WMI `Win32_ProcessStartTrace` requires Administrator privileges (`AccessDenied`), whereas direct `CreateToolhelp32Snapshot` basename scanning takes ~11 ms with zero handles opened; (2) `EAAntiCheatService` stays `Running` in the background even when EA FC is closed, unlike on-demand `EasyAntiCheat_EOS`, `BEService`, and `vgc` services; and (3) the modern per-user Epic Games Launcher registers games under `HKCU\...\Uninstall\EpicGames-*` (`EpicAppId`) instead of legacy `ProgramData` `.item` manifests.

Read [anti-cheat.md](docs/research/anti-cheat.md), [11-v1.2-plan.md](docs/design/11-v1.2-plan.md), [12-mods-and-arabizations.md](docs/design/12-mods-and-arabizations.md), and [D-v1.2-review.md](docs/reviews/D-v1.2-review.md).

Try it yourself. Open `docs/design/mockups/mods-arabizations.html` in a browser and toggle between English (LTR) and Arabic (RTL) to preview the Mafia II Arabization-vs-Mod conflict resolution design.

## M14 — Zero-Presence anti-cheat guard, fail-closed watchdog, and emergency teardown

Running the real dummy-process lab caught a subtle latency hazard: during normal exit, `LibraryController.close()` waited for a background PowerShell `XboxDetector` scan (~7 seconds), which would delay exiting when a protected game launches. Passing `wait=False` on emergency protection exits dropped full shutdown latency from ~7.9 s to well under 500 ms. Ordering the startup protection check *before* `SingleInstance.claim_or_activate()` guarantees that even clicking a desktop shortcut while a protected game runs refuses immediately without activating or writing to disk.

Read [guard.py](gamehub/core/protection/guard.py), [catalog.py](gamehub/core/protection/catalog.py), [protected_games.json](gamehub/core/protection/protected_games.json), and [test_zero_presence_guard.py](tests/test_zero_presence_guard.py).

Try it yourself. Run `python -m pytest tests/test_zero_presence_guard.py -v` to watch the real Windows dummy-process lab test `FortniteBootstrapper.exe`, `FortniteLauncher.exe`, `VALORANT.exe`, `EasyAntiCheat_EOS.exe`, and `RiotClientServices.exe`.


## M15 — Multi-launcher discovery, Scan Folders, and real-PC drive diagnostics

Validating detectors against a real Windows PC revealed two subtle environment behaviors that synthetic fixtures alone can miss: Steam's `libraryfolders.vdf` retains both disconnected drive letters (`DRIVE_NO_ROOT_DIR = 1`) and mapped network drives (`DRIVE_REMOTE = 4`), so skipping non-fixed drive letters while still rejecting UNC shares and reparse points eliminates false partial-scan banners without weakening path validation. Separating user-reviewed Scan Folders into a dedicated `FolderDetector` backed by SQLite `scan_folders` and `scan_folder_choices` keeps manual folder games cleanly reconciled alongside 9 read-only launcher detectors.

Read [epic.py](gamehub/core/library/epic.py), [steam.py](gamehub/core/library/steam.py), [riot.py](gamehub/core/library/riot.py), [folder_scanner.py](gamehub/core/library/folder_scanner.py), [scan_folders_dialog.py](gamehub/ui/scan_folders_dialog.py), and [test_v12_detectors_and_scan_folders.py](tests/test_v12_detectors_and_scan_folders.py).

Try it yourself. Click **Scan folder…** in the Library header on any folder containing games and helpers (`unins000.exe`, `vc_redist.x64.exe`), untick one item, save, and rescan to see the unticked item stay remembered.


## M16 — Landscape-first cover discovery, zero-stretch cropping, and WebP thumbnail caching

Setting `QLabel.setScaledContents(True)` on responsive grid cards stretches images whenever a card grows wider than its initial pixmap. Replacing it with a resize-aware `CoverLabel` that re-crops with `KeepAspectRatioByExpanding` and backing `load_cover_pixmap` with an atomic on-disk WebP cache under `<data_root>/cache/covers/` eliminates distortion at every window width while keeping redraws instant. Searching wide assets (`header.jpg`, `library_header.jpg`, `library_hero.jpg`) across flat, per-AppID, and hashed Steam `librarycache` directories before falling back to vertical capsules improved real-PC landscape cover coverage to 26/26 Steam titles.

Read [steam.py](gamehub/core/library/steam.py), [covers.py](gamehub/ui/covers.py), [storage/covers.py](gamehub/core/storage/covers.py), [steamgriddb.py](gamehub/core/library/steamgriddb.py), and [test_v12_covers.py](tests/test_v12_covers.py).

Try it yourself. Click the `⋯` button on any game card → **Change cover…**, pick a local PNG/JPG/WebP image, refresh the library, and confirm your custom cover stays preserved (`custom_cover = 1`) until you choose **Reset cover**.


## M17 — Plain-language grouped Settings, opt-in network isolation, and Reset to defaults

Grouping settings into five task-oriented sections with one-line muted helper text under every control makes technical options like screenshot ring sizes, global shortcuts, and per-launcher anti-cheat toggles self-explanatory in both English and Arabic. Keeping the optional SteamGridDB cover fetcher strictly disabled by default, password-masking the user's API key, and disabling the fetch trigger until both opt-in and key are provided ensures users never trigger unexpected outbound requests. Pairing `SettingsService.reset_to_defaults()` with `LibraryRepository.reset_protection_defaults()` restores every safety default cleanly without touching saved gameplay history.

Read [settings_view.py](gamehub/ui/settings_view.py), [settings.py](gamehub/core/settings.py), [USER-GUIDE-AR.md](docs/USER-GUIDE-AR.md), and [test_v12_settings.py](tests/test_v12_settings.py).

Try it yourself. Open **Settings → About and privacy** and click **Reset to defaults**, confirm the dialog, and verify that theme, capture interval, launcher toggles, and per-game protection return to their safe defaults while your library remains intact.


## M18 — `v1.2.0-rc.1` verification, frozen smoke test, and pre-release gate

Shipping a multi-pillar release safely combines automated static invariants (`tests/test_packaging.py`), live real-PC verification (Steam 26/26 wide covers, Epic 3, Riot 1, EA 2 with zero false partial banners), a local Python-free `PATH` PyInstaller smoke test (`FROZEN_SMOKE_EXIT=0`), and a full Windows CI Inno Setup install/upgrade/uninstall pipeline producing `SHA256SUMS.txt`. Publishing `-rc.1` first lets the owner validate the exact installer binary on their machine and decide on irreversible items (brand rename variant and Part 6 Mods scope) before cutting final `v1.2.0`.

Read [CHANGELOG.md](CHANGELOG.md), [M18-review.md](docs/reviews/M18-review.md), [11-v1.2-plan.md](docs/design/11-v1.2-plan.md), and [12-mods-and-arabizations.md](docs/design/12-mods-and-arabizations.md).

Try it yourself. Run `Get-FileHash "$env:USERPROFILE\Desktop\GameHub-Setup-v1.2.0-rc.1.exe" -Algorithm SHA256` and confirm it matches `SHA256SUMS.txt` on the `v1.2.0-rc.1` GitHub pre-release.


## M19a — Rename to GameRewind, Automatic Data Migration & Custom-Folder Installer
When you rename a desktop application that real players already have installed, the hardest part is not changing the window title — it is making the upgrade invisible and lossless. `migrate_legacy_data_root()` runs strictly after the zero-presence anti-cheat check passes, backs up `%LOCALAPPDATA%\GameHub\gamehub.db` through SQLite's online backup API into a staged directory under `%LOCALAPPDATA%\GameRewind`, checks `PRAGMA quick_check` and `PRAGMA foreign_key_check`, copies media/overrides safely (skipping symlinks/junctions), or carries over `store-location.json` if the player already relocated their store. On the installer side, setting `DisableDirPage=no` and `UsePreviousAppDir=no` with a Pascal `[Code]` writability probe lets players pick any writable folder (including Desktop or another drive) without ever requesting administrator privileges, while `PrepareToInstall` quietly runs any legacy Game Hub uninstaller so old Start Menu shortcuts and duplicate Add/Remove entries disappear cleanly without touching user data.

Try it yourself. Run `.\.venv\Scripts\python.exe -m pytest tests/test_store_location.py tests/test_packaging.py -q` to verify both automatic legacy data migration and all GameRewind packaging invariants.


## M20 — Simplified Translations & Mods with Crash-Safe Journal
Good mod managers fail players in two ways: either they bury people under load-order priority numbers and jargon, or they crash halfway through copying files and leave a game folder broken. GameRewind's `ModsEngine` avoids both. Packages are strictly declarative `.zip` archives verified against SHA-256 checksums before a single byte is extracted, with zero scripts, executables, symlinks, or `..` traversal allowed. Before modifying a game folder, the engine writes an `in_progress` row to `mod_journal`, backs up every original file atomically into `%LOCALAPPDATA%\GameRewind\mods\backups\<game_id>\`, and replaces files via temp-file + `fsync` + atomic rename. If power fails mid-operation, `recover_incomplete()` reconciles the game folder back to a clean consistent state on the next launch. Protected/online games remain permanently locked at both UI and engine layers even if a user overrides per-game protection settings, and any running game blocks all file mutations.

Try it yourself. Run `.\.venv\Scripts\python.exe -m pytest tests/test_mods.py -q` to verify manifest rejection, conflict winner switching, crash-safe journal recovery, and protected-game locks.
