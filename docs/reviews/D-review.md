# Milestone D review

## Advocate

The eleven design files connect observable player behavior to the platform adapters and data contracts. Keep the exact-window capture lease, explicit interrupted-session recovery, bounded media buffer, and separately testable Windows adapters. The roadmap leaves the screenshot, recorder, launcher, and watcher contracts in place.

## Critic

The first draft gave the schema version its own commit and released the future backup's media lease before the bytes were secured. A crash could cause an already-applied migration to run twice. Concurrent screenshot eviction could make a backup incomplete. The draft also needed explicit handling for duplicate manual entries, hotkey conflicts during rebinding, and ownership of file-backed media.

Re-review confirmed that schema and version commit together, rollback is tested by reopening the database, and backup protects references through immutable staging. Duplicate manual adds reuse the existing record, hotkey rebinding preserves working chords, and managed media has one owner per relative path. The replay, search, transcription, diagnostics, and patching extension points leave the v1 adapters independent.

## Neutral Analyst

The specification is traceable from R1–R11 through flows and test cases. The data model supplies keys, relations, indexes, settings, file formats, recovery and migrations. The architecture and interface documents specify module boundaries and enumerate each later feature. Windows device, launcher and release checks are assigned to the milestones where the behavior first exists.

## Judge

Initial verdict **APPROVE WITH CHANGES**. Required fixes were to make schema versioning atomic and hold the future backup lease through media staging.

Re-review verdict **APPROVE**. Both changes are present and have explicit regression checks. The Council approves starting M0. WGC wheel and driver compatibility, real launcher discovery, and Windows release behavior remain implementation gates.
