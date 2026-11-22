# Changelog

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
