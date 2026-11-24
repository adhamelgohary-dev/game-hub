# Changelog

## v1.2.0-rc.3

### Changed
- **59% smaller shipped bundle (`302 MiB -> 123 MiB` unpacked, `121 MiB -> 51 MiB` portable `.zip`):** Removed unused OpenCV (`opencv-python` / `cv2`, ~126 MiB) via a minimal in-memory `cv2` stub for `windows_capture`'s unused `save_as_image()` helper, dropped `opengl32sw.dll` (~20 MiB), unused Qt QML/Quick/VirtualKeyboard/OpenGL/SVG DLLs, unused Qt plugins/translations, and Pillow's unused `_avif` codec while retaining `upx=False`, all license notices, and clean-Windows Ogg Vorbis audio playback.
- Added an automated CI bundle size and forbidden-binary gate in `.github/workflows/windows.yml` failing builds if unpacked size exceeds `200 MiB`, portable `.zip` exceeds `70 MiB`, or any `cv2`/`opencv`/`psutil`/`opengl32sw`/`Qt6Qml`/`Qt6Quick` binary appears.

### Performance
- **>4× faster, UI-thread-independent anti-cheat exit latency (240 real frozen trials):** Moved emergency `os._exit` directly onto the `protection-guard` daemon thread (eliminating the `QueuedConnection` UI-thread wait and 200 ms fallback timer) with precomputed O(1) trigger maps and `kernel32.K32EnumProcesses` fast PID-diff checks at 80 ms. Frozen `GameRewind.exe` now exits in **75–87 ms average** (`P95 <= 171 ms`, `max <= 180 ms`) for Fortnite, Valorant, and EA SPORTS FC — both normally and under active UI scrolling load.
- **4.0× lower idle CPU (`5.65% -> 1.43%` of 1 core; `0.119%` total system CPU):** `K32EnumProcesses` skips redundant `CreateToolhelp32Snapshot` scans when no PIDs change while running immediate full scans on any new process and unconditional 2 s full audits + 240 ms read-only SCM checks.
- **Faster startup & smooth 100-game library:** Lazily initialized `VoicePlayer` (`PySide6.QtMultimedia`), `PIL.Image`, and secondary startup wiring after `window.show()` (keeping `ProtectionGuard.self_check()` strictly first); moved cover thumbnail decoding, cropping, and WebP caching onto a background worker pool with viewport-aware lazy loading (`33%` faster cold frozen startup, `4.0×–4.6×` faster 20/100-game cold library draws, `5.0×` faster Translations & Mods page opening).

### Fixed
- **EA SPORTS FC & multi-launcher detection:** Added Epic Games Store `epic_app_names`, EA app slugs (`fc-24`/`fc-25`/`fc-26`/`fc-27`), Steam FC 25 Showcase (`3103970`), Xbox `ElectronicArts.EASPORTSFC`, trial/showcase executables, conservative normalized title matching (`title_aliases`), and bounded depth-3 nested executable discovery in `EpicDetector`.
- **2026 anti-cheat catalog coverage:** Added **Grand Theft Auto V / GTA V Enhanced** (BattlEye), **Marvel Rivals** (NetEase/ACE), **Wuthering Waves** (ACE), **Roblox** (Hyperion), **Dota 2** (VAC), Battlefield 6 binaries/IDs, Call of Duty Battle.net IDs, and Epic/EA/Xbox identifiers across existing online entries.
- Invalidated `ProtectionGuard` PID-diff state in `unignore_pid()` and added a 15-second TTL to `ModsEngine`'s UI protection cache (keeping all mutating `_assert_not_protected()` checks uncached).

### Security
- **Fresh 4-domain independent Red-Team re-check (`v1.2.0-rc.3`) — 0 open findings:** Re-verified anti-cheat/launchers, network/websites, local safety/mods/CI, and trimmed frozen packaging (`docs/reviews/security/rc3/` and updated `docs/SECURITY-AUDIT-v1.2.md` / `docs/SECURITY-AUDIT-v1.2-AR.md`).
- **Windows DPAPI encryption for optional SteamGridDB API key:** Encrypted `covers.steamgriddb_api_key` at rest in SQLite using user-scoped `crypt32.CryptProtectData` / `CryptUnprotectData` (`gamehub/core/secrets.py`), keeping SteamGridDB strictly off by default and offline-safe.
- **Hardened SteamGridDB HTTP client:** Rejected URL userinfo and non-443 ports, bound explicit `ssl.create_default_context()` alongside disabled redirects, enforced CRLF/ASCII validation on `api_key`, and validated PNG/JPEG/WebP magic headers before returning downloaded image bytes.

## v1.2.0-rc.2

### Added
- **GameRewind Brand & Custom-Folder Installer (M19a):**
  - Renamed the application, executable (`GameRewind.exe`), portable archive (`GameRewind-Portable-vX.Y.Z.zip`), installer (`GameRewind-Setup-vX.Y.Z.exe`), data folder (`%LOCALAPPDATA%\GameRewind`), and repository (`adhamelgohary-dev/game-rewind`) to **GameRewind**.
  - Added automatic, lossless SQLite online-backup migration from legacy `%LOCALAPPDATA%\GameHub` (including integrity checks, media, overrides, and relocated `store-location.json`), plus quiet removal of legacy Game Hub shortcuts and uninstall entries during installation without touching user data.
  - Enabled choosing any writable local install folder (`DisableDirPage=no`, `UsePreviousAppDir=no`) with an optional **Create a desktop shortcut** task and automatic cleanup of a previous GameRewind install when moving to a new folder.
- **Simplified Translations & Mods Module (M20):**
  - Added a dedicated **Translations & Mods** sidebar page and per-game tab with jargon-free **On/Off** toggles, one-click **"Restore the original game"**, and a plain two-button conflict chooser in English and Arabic (RTL).
  - Added crash-safe `mod_journal` recovery on startup, atomic original-file backups under `<data_root>/mods/backups/`, and SQLite Schema v7 (`mod_items`, `mod_backups`, `mod_deployed_files`, `mod_conflict_choices`, `mod_journal`) with automatic `gamehub.db-v6.bak` pre-upgrade backup.
  - Hard-locked Translations & Mods for all protected/online/strict games (even if per-game protection is overridden) and blocked all file mutations while any game or anti-cheat service is active.

### Changed
- Reduced passive `ProtectionGuard` polling interval from `300 ms` to `150 ms` for faster pre-anti-cheat exit latency (`<250 ms`).
- Replaced `XboxDetector`'s `powershell.exe` subprocess inventory with direct read-only Windows Registry (`HKCU\...\AppModel\Repository\Packages`) + `MicrosoftGame.config` scanning (zero subprocess spawns).
- Expanded `protected_games.json` with **2XKO** (`lion`), `deadbydaylight-wingdk-shipping.exe`, additional Riot Client processes (`riot client.exe`, `riotclientuxrender.exe`, `leagueclientuxrender.exe`), Ubisoft/Battle.net/EA catalog IDs, and global `start_protected_game.exe`.

### Fixed
- **Vanguard `vgc` startup false-lockout:** Excluded persistent `vgc` service / `vgc.exe` from startup refusal triggers (matching the `EAAntiCheatService` precedent) while keeping Riot Client (`always_strict_launchers`) and Valorant/LoL/2XKO binaries strictly enforced, and named the exact blocking trigger (with system-tray hint for launchers) on refusal notifications.
- **Sleep / Modern Standby false watchdog trips:** Switched `ProtectionGuard`'s heartbeat clock to `kernel32.QueryUnbiasedInterruptTime` so Windows sleep/standby no longer triggers false fail-closed exits on resume.
- **Emergency shutdown blocking & races:** Eliminated modal `QMessageBox` hangs on startup refusal and fail-closed exits (using non-blocking Windows notifications instead), prevented `ThreadPoolExecutor`/`ProtectionGuard`/`SessionWatcher` shutdown waits from delaying emergency exits, exempted the "Test protection" dummy PID from `SessionWatcher`, suspended hotkeys/capture before protected Play launches, and prevented `NoteDialog` teardown from flashing the window during emergency exit.
- **Translations & Mods edge cases:** Handled Windows case-insensitive collisions (`fonts.cfg` vs `Fonts.cfg`), stored relative package/backup paths so **Restore the original game** keeps working after `StoreLocation.move()`, and added re-verification + per-operation locking.

### Security
- **Complete removal of `psutil`:** Removed `psutil` from runtime code, tests, `requirements.txt`, and `packaging/gamerewind.spec` (`excludes=['psutil']`), eliminating `_psutil_windows.pyd` (and its `AdjustTokenPrivileges("SeDebugPrivilege")` / `ReadProcessMemory` imports). Replaced process creation-time lookup with `kernel32.GetProcessTimes` on a single `PROCESS_QUERY_LIMITED_INFORMATION` (`0x1000`) handle restricted exclusively to verified Full-mode tracked games.
- **Zero-handle discipline:** Kept `CaptureScheduler` paused when zero Full-mode games are active, gated `WindowProbe.foreground()` strictly on `tracker.active_pids()`, prevented `ProcessProbe` from opening handles to OS/system/security/launcher/anti-cheat processes, and prevented per-game `"full"` overrides from stripping global anti-cheat binaries or always-strict launchers.
- **Fail-closed & override hardening:** Made `protected_games_override.json` strictly additive (never able to weaken bundled protection), rejected `bool` schema versions and deeply nested JSON, failed closed on empty Toolhelp snapshots / transitional SCM states / `StorageError` in `LifecycleCoordinator`, caught `BaseException` in `ProtectionGuard._loop()`, and enforced custom user-marked `strict` games at both startup and runtime.
- **Declarative-only mod pack enforcement:** Rejected renamed PE binaries (`MZ` + `PE\0\0` header check), expanded forbidden executable/script extensions (`.asi`, `.pyd`, `.pyc`, etc.), blocked `src`-reuse zip bombs, deep JSON recursion, invalid Windows/BiDi/device-name paths, file-vs-directory collisions, symlinks/junctions, and `install_dir` overlap with `data_root`, verifying SHA-256 before atomic replacement.
- **Installer, SteamGridDB, and CI hardening:** Blocked installing into drive roots, Desktop, `%USERPROFILE%`, `%LOCALAPPDATA%\GameRewind`, non-empty unrelated folders, or UNC paths; validated HKCU `UninstallString` targets strictly against `InstallLocation\unins*.exe`; disabled HTTP redirects and restricted SteamGridDB image downloads to `cdn.steamgriddb.com` / `cdn2.steamgriddb.com`; pinned all GitHub Actions to commit SHAs; and added CI PE `asInvoker`/`VERSIONINFO`/zero-UPX and Windows Defender (`MpCmdRun.exe`) gates.

## v1.2.0-rc.1

### Added
- **Zero-Presence Anti-Cheat Protocol (Layers 1–7):**
  - Fail-closed startup self-check (`ProtectedGamesCatalog` strict load + Toolhelp32 basename scan + read-only SCM service check for `EasyAntiCheat_EOS`, `EasyAntiCheat`, `BEService`, `vgc`) runs **before** `SingleInstance` activation, window creation, or any database write — refusing immediately if a protected game or Riot Client is already running.
  - Fast 300 ms passive `ProtectionGuard` with a 1-second main-thread heartbeat watchdog detects earliest launcher-stage processes (`FortniteBootstrapper.exe`, `FortniteLauncher.exe`, `VALORANT.exe`, `EAAntiCheat.GameServiceLauncher.exe`, `start_protected_game.exe`) and performs emergency teardown in under 500 ms before anti-cheat drivers initialize.
  - **Riot Client** is locked ALWAYS strict for Vanguard safety; **Epic**, **EA**, **Battle.net**, **Ubisoft**, and **Steam** remain allowed by default so single-player story games run in Full mode, with opt-in per-launcher strict toggles and confirmation-guarded per-game overrides in **Settings → Protected games**.
  - Added **"Test protection"** self-test button using harmless temporary dummy executables to confirm detection and exit latency on the user's PC, plus `docs/DEFENDER-SUBMISSION.md` click-only false-positive submission guide.
- **All-Launcher Read-Only Discovery & Scan Folders:**
  - Added read-only detectors for **Riot Games**, **GOG** (Galaxy SQLite + registry), **EA app**, **Ubisoft Connect**, **Battle.net**, and **itch.io** (`butler.db`), plus improved **Xbox** cover extraction from `MicrosoftGame.config`.
  - Added **Scan folders** (`Scan folder…` in Library & **Settings → Library and folders**) with depth-bounded symlink-safe `.exe` scanning, automatic filtering of uninstallers/crash reporters/redistributables/anti-cheat helpers, an editable candidate review dialog, and persisted include/ignore choices.
  - Replaced raw partial-scan warnings with plain-language English & Arabic banners featuring **Retry** and **Learn more** actions.
- **Fitting Cover Art, WebP Thumbnail Cache, Change Cover & Opt-In SteamGridDB:**
  - Switched Steam cover discovery to **landscape-first** across flat, per-AppID, and hashed `librarycache` directories before falling back to vertical capsules.
  - Replaced stretched card covers with resize-aware zero-stretch `CoverLabel`, added atomic `<data_root>/cache/covers/` WebP thumbnail caching, and upgraded fallback placeholders to render full game titles cleanly.
  - Added **"⋯ → Change cover…"** and **"Reset cover"** on every Library card and Game page backed by safe managed WebP storage (`<data_root>/media/<game_id>/cover.webp`, preserved across refreshes).
  - Added strictly **opt-in (off by default)** SteamGridDB cover art fetching in **Settings → Library and folders** requiring the user's own API key (password-masked, never logged).
- **Plain-Language Grouped Settings & Egyptian Arabic Guide:**
  - Reorganized **Settings** into 5 clear groups (**General**, **Capture and notes**, **Protected games**, **Library and folders**, **About and privacy**) with a one-line plain explanation under every setting in both English and Arabic.
  - Added **Reset to defaults** (with confirmation, keeping all notes and screenshots) and updated `docs/USER-GUIDE-AR.md` with a complete Egyptian Arabic **"شرح الإعدادات"** section.

### Changed
- Upgraded SQLite database to Schema v6 (`scan_folders`, `scan_folder_choices`, `games.custom_cover`, per-launcher strict toggles, optional SteamGridDB settings) with automatic `gamehub.db-v5.bak` pre-upgrade backup.
- Updated `WindowsLauncher` to support detached official Riot Client launches alongside Steam, Epic, GOG, EA, Ubisoft, Battle.net, and Xbox URIs.

### Fixed
- **Epic Games discovery:** Added modern per-user `HKCU\...\Uninstall\EpicGames-*` (`EpicAppId`) and `LauncherInstalled.dat` scanning alongside legacy `ProgramData` manifests so modern Epic Games installs (e.g., *Fortnite*, *Death Stranding*, *Hue*) appear automatically.
- **Steam false partial warnings:** Skipped offline, unmounted, removable, and mapped-network drive letters in `libraryfolders.vdf` (`GetDriveTypeW` in `{1, 2, 4, 5}`) without falsely marking the Steam scan as partial.
- **Emergency shutdown latency:** Skipped blocking on background library worker threads (`wait=False`) during emergency anti-cheat exits so Game Hub closes in milliseconds.

### Security
- Expanded static AST/regex security invariants in `tests/test_packaging.py` to enforce zero `SendInput`, `keybd_event`, `mouse_event`, `SetWindowsHookEx`, `ReadProcessMemory`, `WriteProcessMemory`, `CreateRemoteThread`, zero `OpenProcess` outside `processes.py`, `asInvoker` manifest, `upx=False`, and strictly isolated opt-in network access confined exclusively to `gamehub/core/library/steamgriddb.py`.

## v1.1.0-rc.2

### Added
- **Expanded Easy Anti-Cheat catalog (`protected_games.json`):** Added **ARMORED CORE VI FIRES OF RUBICON** (`1888160` / `armoredcore6.exe`), **ELDEN RING NIGHTREIGN** (`2622380` / `nightreign.exe`), **Lords of the Fallen** (`1501750` / `lotf2-win64-shipping.exe`), and **Warhammer 40,000: Space Marine 2** (`2183900`) alongside **ELDEN RING** (`1245620` / `eldenring.exe` / `start_protected_game.exe`) so all default to **Strict mode**. Verified **Dark Souls III** (`374320`), **Dark Souls: Remastered**, and **Sekiro** do not use Easy Anti-Cheat or a kernel driver and therefore remain in **Full mode** by default (`docs/research/anti-cheat.md`).

### Changed
- **Cleaner button and label typography:** Removed visible `&` mnemonic underlines across all UI surfaces (`Refresh`, `Add game…`, `Back to Library`, `Play…`, `Upload controls image…`, `Previous`, `Next`, `Save settings`, dialogs, and labels) while keeping full English/Arabic translation parity.
- **Updated README screenshots:** Regenerated `docs/screenshots/*.png` using the live `ProtectedGamesCatalog` so **Elden Ring** accurately displays **Strict** / **Auto (Strict)** and buttons render without mnemonic underlines.

### Fixed
- Ensured `ProtectedGamesCatalog.load()` explicitly checks `sys._MEIPASS` in frozen PyInstaller bundles so bundled `protected_games.json` always resolves reliably in packaged builds.
- Replaced Qt's built-in `QDialogButtonBox.StandardButton.Close` in `LastMomentsDialog` with a translated plain `"Close"` button to eliminate its default mnemonic underline.

### Security
- Preserved zero-background lifecycle, zero `OpenProcess` handles on protected/Strict games, zero game injection/hooks/memory reads, and 100% offline operation.

## v1.1.0-rc.1

### Added
- **Zero-background lifecycle:** Closing the main window exits Game Hub completely (no system tray, no Windows startup entry, no background services or helper processes). Upgrading over v1.0 automatically removes the legacy `HKCU\...\Run\GameHub` startup value (both in Inno Setup and on portable startup).
- **Anti-cheat safe Strict mode & protected-games catalog:** Ships an updatable catalog (`protected_games.json`) covering 34+ protected games (Valorant, League of Legends, Fortnite, Apex Legends, Call of Duty, Rainbow Six Siege, PUBG, Rust, EA SPORTS FC, CS2, Deadlock, Elden Ring, and more) plus cited anti-cheat research (`docs/research/anti-cheat.md`).
- **Game-aware Play-through flow & forgetful-case safeguard:** Launching via **Play** shows the Last-time card, minimizes Game Hub during play, offers the optional note prompt on exit (or next open when "Exit Game Hub after launching" is checked), and passively detects externally launched protected games via Toolhelp basenames (auto-exiting Game Hub by default, configurable to Strict mode or a passive Windows notification).
- **Windows 11 Fluent UI redesign:** Dark, Light, and System themes with live switching, persistent sidebar navigation, responsive cover-art Library card grid with search and All/Full/Strict filter chips, real local Steam/Epic cover art discovery with stylized fallbacks, clickable cards + **Details**, Game page `⋯` overflow menu, Last-time **"Last moments"** image carousel with arrows and pagination dots, **Settings → About and privacy**, full Arabic RTL parity, custom app icon (`GameHub.ico`), and Inno Setup wizard branding.
- **Public open-source release readiness:** MIT `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, embedded Windows EXE version metadata & manifest (`asInvoker`, `PerMonitorV2`), SemVer GitHub Releases with `SHA256SUMS.txt`, and SignPath Foundation application & CI signing scaffolding (`docs/SIGNPATH-APPLICATION.md`).

### Changed
- Upgraded local SQLite database to Schema v5 (`games.protection_mode`, `games.exit_after_launch`, `pending_notes`) with automatic pre-upgrade backup (`gamehub.db-v4.bak`).
- Switched Windows Graphics Capture to borderless mode (`draw_border=False`) on supported Windows 11 builds (20348+) with automatic cached fallback.
- Consolidated pre-SemVer milestone GitHub Releases (`m0–m8`) into `v1.0.0` while preserving all historical git tags.

### Fixed
- Eliminated horizontal card clipping on narrow/standard Library widths and fixed dark-mode `QTabWidget` scroll container contrast on the Game page.
- Prevented native WinRT `draw_border=False` async thread errors from failing screenshots on unsupported Windows builds.

### Security
- Verified zero secrets or personal data across full git history (`gitleaks 8.30.1` + blob audit) prior to publishing the repository.
- Guaranteed zero `OpenProcess` calls on protected or Strict-mode games (Toolhelp basename-only passive detection), zero game injection/hooks/memory reads, and 100% offline operation enforced by static AST tests.

## m8

- Release Game Hub v1.0.0 for Windows 10/11 x64 as a per-user installer (`GameHub-Setup.exe`) and portable bundle (`GameHub-Windows-x64.zip`).
- Harden Inno Setup for clean in-place upgrades (`_internal` cleanup) and clean uninstall (removing the per-user Windows startup entry while preserving local user data).
- Add Python-free `PATH` smoke testing, upgrade/uninstall verification, static offline/no-injection audits, and complete third-party license notices including Qt, FFmpeg, PortAudio, and libsndfile.
- Add updated English documentation (`README.md`) and a full Arabic user guide (`docs/USER-GUIDE-AR.md`).

## m7

- Add Settings for language, capture interval (5–300 s), screenshot ring size (1–50), voice autoplay, close prompt, all three global hotkeys, Windows startup, and data folder.
- Add atomic batch hotkey rebinding that supports swapping shortcuts and preserves working bindings when Windows reports a conflict.
- Add per-user Windows startup registration and verified offline data-folder relocation with `store-location.json` and integrity checks.
- Add live English and Arabic localization with full catalog parity, RTL layout mirroring, updated `QLocale`, and RTL-aware carousel navigation.

## m6

- Upgrade local SQLite storage to schema 4 with the `controls` table and automatic pre-upgrade backup.
- Pin a controls screenshot of the focused tracked game window with Ctrl+Alt+C reusing the exact-window capture gate.
- Upload local PNG, JPEG, WebP, or BMP controls images (sanitized and re-encoded to managed WebP) and save per-game strategy notes.
- Add the per-game Game page with Play, pinned Controls, and a paginated chronological Session Timeline showing screenshots, voice notes, text notes, and missing-media fallbacks.

## m5

- Show the always-on-top Last time card when a tracked game starts, with prior play summary, independent latest voice and text notes, screenshots carousel, and controls section.
- Play local Ogg voice notes through a bounded Qt Multimedia memory buffer with persisted autoplay preference, Stop, and Replay controls.
- Reopen the Last time card with Ctrl+Alt+L using focused, single active, selected, or last unambiguous game resolution.
- Add Play preview before explicit Launch with validated Steam URI, Epic URI, and executable dispatch and 90-second deduplication against watcher starts.

## m4

- Save text or voice notes from the optional game-close prompt.
- Start and stop a voice note for the tracked game with Ctrl+Alt+N.
- Keep notes attached to their original session through focus changes.
- Preserve the text draft or encoded clip after a failed save so it can be retried.

## m3

- Capture only the foreground window of a currently tracked game using Windows Graphics Capture.
- Keep up to ten recent screenshots per session and show them from the library's Last moments action.
- Preserve existing library and session data during the screenshot schema upgrade.

## m2

- Track registered games from the Windows tray.
- Record start, end, and observed playtime in the local database.
- Recover interrupted sessions from the last verified checkpoint.

## m1

- Discover installed Steam, Epic Games Store and supported local Xbox titles.
- Add a local executable manually and select an executable for a launcher game.
- Keep the library in SQLite across application restarts.

## m0

- Added the Game Hub starter window and tray.
- Added a Windows installer and portable bundle.

## Design

- Approved requirements, flows, architecture, data formats, interfaces, extension points, and test strategy before implementation.
