# Changelog

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
