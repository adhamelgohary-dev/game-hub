# M1 library detection review

## Advocate

Keep separate launcher adapters, synthetic fixtures, asynchronous scans, user-selected executable targets, and stable SQLite IDs. A failed launcher does not remove games previously seen from that source. The controller integration test follows manual add from the Qt view to the database and back.

## Critic

An inaccessible folder in the Steam index originally dropped valid sibling folders. The detector now skips that entry, marks the scan partial, and retains other folders. Added a regression fixture. The app now renders saved rows before refreshing. The local scanners validate paths, accept fixed launcher identities, and log diagnostic codes without including manifest values or personal paths.

## Neutral Analyst

The library displays name, source, install path, last played and playtime. It identifies unavailable tracking targets and offers executable assignment. Live verification used 25 Steam entries, a temporary SQLite database, and a manual Windows executable. On this machine Epic manifests were unavailable and no accessible Xbox title was found. Both adapters passed synthetic fixture tests and the Xbox limits are documented.

## Judge

Initial verdict **APPROVE WITH CHANGES**. Preserve valid Steam siblings when one index entry is inaccessible, display cached library rows before refresh, and make missing tracking targets visible. The fixes are in place. Re-review after final local, hosted, and release verification.

Source re-review passed. All 41 local tests, Ruff, and the local frozen application smoke passed. The hosted tagged installer and release checks are the remaining gate.
