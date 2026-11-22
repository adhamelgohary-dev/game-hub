# M4 notes review

## Advocate

Keep explicit recording actions, session ownership when focus changes, the queued non-activating prompt, and an always-available text fallback. Recording status is visible in the prompt and tray. Save retry holds an encoded clip in memory and never starts a new recording.

## Critic

The first version could start a queued microphone operation after the prompt had already closed. The worker now checks cancellation before and after opening input, and the dismissal test verifies that an unstarted operation opens no stream. Audio input is bounded to one channel and at most 60 seconds. Managed Ogg files use the same pinned storage path as screenshots. PortAudio and libsndfile are bundled for local use.

## Neutral Analyst

Native Ctrl+Alt+N started and stopped the recorder flow while the synthetic window had focus. The generated Ogg clip was linked to its original SQLite session. Tests cover focus changes, permission-denial behavior, text fallback, opt-out, dismissal and retry after storage failure. Codec verification uses generated samples and input doubles. A physical microphone recording was outside the verification run.

## Judge

Initial verdict **APPROVE WITH CHANGES**. Cancel queued input on dismissal or quit, preserve a successfully encoded clip if saving fails, and show the processing state apart from active capture. Re-review confirms the fixes. All 110 tests, Ruff and source startup passed. Verify the final frozen build and tagged packages before closing the milestone.

The native shortcut passed again after the asynchronous save change. The isolated frozen build loaded PortAudio and confirmed Ogg Vorbis support. The hosted release verification remains open.
