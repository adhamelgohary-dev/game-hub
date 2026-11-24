# Game Hub design

Game Hub is a Windows 10/11 desktop app that helps players return to a single-player game after a break. The library discovers supported local installations (Steam, Epic, Xbox) or accepts a manually selected executable. Starting in v1.1, Game Hub runs with **zero background footprint**: there is no system tray icon, no "start with Windows" registry entry, and no background service or helper process. Closing the main window exits the process completely.

When the user plays through Game Hub, the **Last time** card brings up previous voice/text notes, screenshots, play history, and pinned controls before launching the game. While the game runs, Game Hub minimizes and uses per-game **Protection modes** informed by [anti-cheat research](../research/anti-cheat.md):
- **Full mode** (default for single-player / non-anti-cheat titles): foreground-only Windows Graphics Capture screenshots (borderless where Windows supports `draw_border=False`), in-game global hotkeys, and end-of-session note prompt.
- **Strict mode** (default for known protected / kernel anti-cheat games): zero periodic screenshots, zero in-game hotkeys, zero topmost overlays over the game, zero in-game microphone access, and zero `OpenProcess` handles on protected games — only the Last-time card before launch and the note prompt after exit (or on next open when "exit after launch" is enabled).
- **Forgetful-case safeguard**: if Game Hub is open and the user starts a protected game outside Game Hub, a passive basename-only scan detects it and follows the user's setting (default: **Exit Game Hub automatically**, or switch to Strict mode, or ask via a passive Windows notification).

The app uses Python and PySide6 with a modern Windows 11 / Fluent QSS interface supporting Dark and Light themes and full English/Arabic RTL mirroring, keeping the repository cleanly MIT-licensed. SQLite (schema v5) stores structured data and references local media by relative path under `%LOCALAPPDATA%\GameHub\`. Version 1.x runs completely offline with zero network calls.

## Read in order

1. [Anti-cheat research](../research/anti-cheat.md)
2. [Requirements](01-requirements.md)
3. [User flows and screen sketches](02-user-flows.md)
4. [Architecture](03-architecture.md)
5. [Data model](04-data-model.md)
6. [Public interfaces](05-interfaces.md)
7. [Technology choices](06-tech-stack.md)
8. [Extensibility](07-extensibility.md)
9. [Implementation plan](08-implementation-plan.md)
10. [Testing and debugging](09-testing-and-debugging.md)
11. [Risks](10-risks.md)
12. [UI Mockups (v1.1)](mockups/index.html)
13. [Game Hub v1.2 Plan (Zero-Presence Anti-Cheat, Launchers, Covers, Settings, Rename Check)](11-v1.2-plan.md)
14. [Mods & Arabizations Module (Part 6 — Design Only)](12-mods-and-arabizations.md) and [Mods Mockup](mockups/mods-arabizations.html)
15. [v1.2.0-rc.3 Speed, Size & Security Re-Check Design](13-v1.2-rc3-speed-size.md)

The original v1 product spec is `STRUCTURE.txt`. The [decision log](../../DECISIONS.md) records implementation choices. Update the relevant design and log the change before changing a published interface or data format.
