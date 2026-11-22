# M6 Controls card and timeline review

## Advocate

Schema v4 adds the `controls` table with automatic `gamehub.db-v3.bak` backup and transactional rollback protection. `Ctrl+Alt+C` reuses `CaptureService` through `CaptureScheduler`'s single capture worker so pinned controls obey the exact foreground HWND, active-session, freshness, and black-frame gates without overlapping periodic screenshots. Local image uploads validate, EXIF-transpose, preserve transparency, strip metadata, and re-encode to managed WebP. The Game page brings Play, Controls (image carousel + strategy notes), and paginated chronological Timeline (sessions, lazy screenshots, voice notes, text notes, and missing-media resilience) together, and pinned controls appear on the Last time card.

## Critic

An independent Critic audit raised six blockers on the initial implementation:

1. Switching Timeline voice notes, replaying, paginating, or refreshing could disable Stop buttons while playback continued. Fixed by tracking `_pending_voice_id` across synchronous stop-before-play transitions and syncing active button states after timeline rebuilds.
2. Separate `VoicePlayer` instances allowed overlapping Last time card and Timeline audio. Fixed by sharing one `VoicePlayer` across both surfaces and stopping Timeline playback on Play/Back.
3. `ControlsController.close()` used `wait=False, cancel_futures=True`, risking dropped writes on Quit and use-after-close signal emission; `CaptureScheduler.pin_foreground` could swallow unexpected exceptions. Fixed with `shutdown(wait=True)` on `ControlsController`, `_closed` guards before emitting signals, and bounded exception handling in `CaptureScheduler`.
4. Unsaved controls text could leak across games, and rapid saves could submit duplicate rows or wipe new drafts. Fixed by clearing/resetting `_control_input` on game switch and disabling editing while a controls note save is in flight.
5. `NotesController` did not publish `MemoryChanged`, leaving an open Game page Timeline stale after note saves. Fixed by publishing `MemoryChanged` on committed voice and text notes.
6. `ControlsController.import_image` surfaced untranslated exception strings from core storage. Fixed by mapping `ValueError` to a localized `self.tr(...)` message at the controller boundary.

Minor and defense-in-depth findings were also addressed: strict `formats=` allowlist on `Image.open`, `ImageOps.exif_transpose` + RGBA preservation, NUL-byte and length validation parity with `NoteRepository`, hidden-game check and page-size cap in `MemoryRepository.timeline()`, visible-page error routing, avoiding Timeline resets on control-only `MemoryChanged`, selecting newly pinned control images automatically, mnemonic de-duplication, word wrap, and localized templates on `GamePage`.

## Neutral Analyst

All 158 automated tests and Ruff pass, covering v3-to-v4 migration with backup and rollback, metadata-stripping image import, junction safety during `read_image` and `recover_files`, `CaptureScheduler.pin_foreground` gate reuse without polluting the screenshot ring, paginated newest-first timeline with missing voice/image resilience, voice track-switch and pagination Stop-button persistence, and cross-game draft isolation. Native Windows verification confirmed `Ctrl+Alt+C` registration and persistence of uploaded controls and timeline across database reopen. Interactive in-game `Ctrl+Alt+C` capture over a live game remains a manual acceptance check alongside M3 capture hardware checks.

## Judge

Initial verdict **APPROVE WITH CHANGES** for the six Critic blockers above. Re-review confirms all six blockers and the accompanying validation, accessibility, and lifecycle fixes are implemented and covered by tests. All 158 tests, Ruff, native hotkey/storage verification, and frozen startup pass. Verify the tagged Windows release packages before closing the milestone.

Final verdict **APPROVE**. The [tagged Windows run](https://github.com/adhamelgohary-dev/game-hub/actions/runs/45052424866) passed tests, lint, and startup from both the installer and portable bundle. Both packages are published in the [private m6 release](https://github.com/adhamelgohary-dev/game-hub/releases/tag/m6).
