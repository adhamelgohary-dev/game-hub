# Implementation plan

| Milestone | Ordered work and owners | Gate |
| --- | --- | --- |
| D Design | Architect and data designer specify contracts and storage. Software designer maps features and UI. UX, QA, Security & Privacy, and the Council inspect the integrated design. | Eleven design files, a test plan, decisions, and two approved design reviews. |
| M0 Setup | Integration initializes main, private GitHub, CI, packaging and the installer. UI implements the single-instance window and tray. QA adds the smoke test. | Passing Windows CI, visible window and tray, and downloadable tagged executable and installer. |
| M1 Library | Library builds Steam/Epic parsers, Xbox best-effort discovery, manual add, and normalized repository writes. UI can build against detector doubles in parallel. | Fixture parsing and persistence pass. Verify actual installed games, with any unavailable launcher recorded as unverified, and verify manual add. |
| M2 Sessions | Sessions implements polling and transitions. Storage implements session writes and recovery. UI hooks tray status once events are ready. | One correct row per observed play session, reliable restart behavior, and negligible idle overhead measured on Windows. |
| M3 Capture | Sessions & Capture validates WindowsGraphicsCapture HWND support, implements foreground gate, then bounded ring and persistence. UI can build the carousel against fake frames. | Last ten successful captures appear after play. Unfocused, minimized, closed and protected targets produce no retained captures. |
| M4 Notes | Audio, Notes & Hotkeys supplies recording, registration and note commands. UI can create popup and keyboard interactions in parallel. | Voice/text attach to the correct session, the hotkey works in a focused known game, and denied microphones produce a recoverable message. |
| M5 Last time and Play | UI builds and deduplicates the card. Library implements launcher adapters. Audio delivers playback and preference handling against agreed contracts. | Launching a Steam title externally and from Play shows the correct prior snapshot. Reopen and playback behavior verified. |
| M6 Controls and timeline | UI builds timeline and controls views. Capture reuses the foreground gate for pins. Storage handles imports and retrieval, which can start against fakes. | Hotkey and image upload pin to the correct game. The timeline includes all recorded sessions and handles missing media. |
| M7 Settings and languages | UI integrates English/Arabic catalogs and layout. Integration handles startup and data folder operations. QA exercises setting persistence and RTL. | All UI text and layout direction switch appropriately and settings survive restart. |
| M8 Packaging and release | Integration verifies clean Windows installs, upgrades, and uninstall. UI supplies screenshots and English/Arabic user guide. | GameHub.exe runs without Python on clean Windows. Installer and portable bundle appear on the verified private release. |

All milestone gates require a passing relevant suite, documented Windows evidence where applicable, Council approval, a progress update, a handoff with the exact next action, and a Tutor entry. The lead checks staged diffs before each commit. D is a design-only milestone. Tags m0 through m8 trigger Windows packaging and changelog-based GitHub Releases. QA and Integration own the tag-specific smoke check and record installer, installed startup, and portable startup evidence. Pushes run only the test/lint workflow. Keep ordinary test jobs read-only and grant the release job only the permissions required to publish assets.

GitHub setup runs at M0. Check the authenticated account for an existing repository with the requested name. Use it if it is private and history can be joined without rewriting. Otherwise create a private remote if there is no matching repository. Verify visibility after creation or metadata edits and immediately before the first push. If verification fails or history diverges, preserve the local work and document the blocker. Update the repository description and topics with GitHub CLI.

### Team routing

- Orchestrator resolves sequencing, integrates work, and keeps resumable state.
- Architect owns core and OS boundaries. Software Designer owns requirements, UX, and implementation planning. Data & Extensibility Designer owns storage and extension seams.
- Library, Sessions & Capture, Audio/Notes/Hotkeys, and UI implementers work against the agreed contracts. The platform adapters can progress independently from widget wiring.
- Tutor keeps the learning notes. Security & Privacy checks paths, data, dependencies and releases. UX & Accessibility checks keyboard, DPI, errors and Arabic. QA owns tests and verification evidence. Integration & Packaging owns the Windows build and distribution.
- The Council hears Advocate, Critic and Neutral Analyst separately. The Judge uses requirements and gates, records fixes, and requests up to two rounds of re-review.
