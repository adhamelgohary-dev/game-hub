# Game Hub design

Game Hub is a Windows 10/11 desktop app that helps players return to a single-player game after a break. The library discovers supported local installations or accepts a manually selected executable. A tray process watches for known games and records play sessions. When a game opens, the Last time card brings up previous notes, screenshots, play history, and pinned controls. The game page offers the complete session timeline and a Play button that shows the card before launch.

The app uses Python and PySide6. A small core provides the library, process watcher, Windows capture, audio, hotkeys, and storage. The Memory module owns the player-facing experience. An in-process event bus announces completed state changes. SQLite stores structured data and references local media by relative path. Capture is gated by the exact foreground game window and keeps a bounded ring of images. English and Arabic share the same flows, with right-to-left layout for Arabic.

Version 1 runs offline and keeps player data under the local profile by default. Future modules consume core capabilities through explicit interfaces. Setup includes tests and a private Windows release. Later milestones exercise real launchers, capture, audio, hotkeys, accessibility, and clean-machine install.

## Read in order

1. [Requirements](01-requirements.md)
2. [User flows and screen sketches](02-user-flows.md)
3. [Architecture](03-architecture.md)
4. [Data model](04-data-model.md)
5. [Public interfaces](05-interfaces.md)
6. [Technology choices](06-tech-stack.md)
7. [Extensibility](07-extensibility.md)
8. [Implementation plan](08-implementation-plan.md)
9. [Testing and debugging](09-testing-and-debugging.md)
10. [Risks](10-risks.md)

The product spec is STRUCTURE.txt. The [decision log](../../DECISIONS.md) records implementation choices. Update the relevant design and log the change before changing a published interface or data format.
