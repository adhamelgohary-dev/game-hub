# Changelog

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
