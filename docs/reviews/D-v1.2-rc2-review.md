# Review Council — D-v1.2-rc2 (GameRewind Rename, Custom-Folder Installer, Simplified Translations & Mods)

**Date:** 2026-11-24  
**Scope:** Updated designs in `docs/design/11-v1.2-plan.md`, `docs/design/12-mods-and-arabizations.md`, `docs/design/mockups/mods-arabizations.html` + 3 rendered PNGs (`mods-en-dark.png`, `mods-ar-rtl.png`, `mods-protected-lock.png`), `DECISIONS.md`, and `AGENTS.md`.

## Advocate
- Directly delivers all owner-approved v1.2-rc.2 changes with design-first discipline before touching code.
- Keeping internal Python package `gamehub` while renaming 100% of user-facing artifacts (`GameRewind.exe`, `GameRewind-Setup-vX.Y.Z.exe`, `GameRewind-Portable-vX.Y.Z.zip`, `%LOCALAPPDATA%\GameRewind`, Start Menu, About page, GitHub repo `game-rewind`) eliminates needless import-rename regression risk.
- Dedicated GameRewind `AppId` + silent legacy Game Hub uninstall in `PrepareToInstall` cleanly removes old Game Hub shortcuts and uninstall entries without risking `%LOCALAPPDATA%\GameHub` user data.
- Simplified Translations & Mods removes all profile/priority jargon and protects players with 4 hard invariants (protected-game lock, running-game lock, declarative-only manifest validator, crash-safe write-ahead journal).

## Critic
- **Migration safety:** What if the user previously relocated their data folder using `store-location.json` inside `%LOCALAPPDATA%\GameHub`? Design specifies copying `store-location.json` directly into `%LOCALAPPDATA%\GameRewind` so the custom folder continues working seamlessly without double-copying media. Must also handle reparse-point checks and partial failures cleanly.
- **Installer folder-change upgrade:** If the user installs GameRewind to Folder A, then upgrades and chooses Folder B (`UsePreviousAppDir=no`), stale binaries in Folder A would linger unless `PrepareToInstall` detects a previous GameRewind `InstallLocation != ExpandConstant('{app}')` and silently cleans it up first. Both fresh install, legacy Game Hub upgrade, folder-change upgrade, and uninstall must be tested in CI.
- **Mods lock on overridden protected games:** If a user manually set a protected game (e.g. Fortnite) to `full` mode in Settings, Translations & Mods must STILL stay permanently locked based on `catalog.match_game(...)` as well as `effective_mode == 'strict'`. Design enforces both.
- **Vanguard `vgc` edge case:** Must be explicitly audited by Red-Team Agent F before publishing `v1.2.0-rc.2` so an idle always-running `vgc`/`vgk` does not break normal single-player usage.

## Neutral Analyst
- All design changes are consistent with `AGENTS.md`, offline guarantees, zero-background rules, and Schema v6 → v7 additive migration (`gamehub.db-v6.bak`).
- The 3 rendered mockups (`mods-en-dark.png`, `mods-ar-rtl.png`, `mods-protected-lock.png`) were visually verified with native Windows Segoe UI and Arabic RTL shaping, confirming zero jargon and clean RTL layout.

## Judge Verdict
**APPROVED** — Proceed to **M19a** (Rename to GameRewind + Data Migration + Custom-Folder Installer), **M20** (Simplified Translations & Mods), **M21** (Independent 8-Agent Security Re-Audit + Remediation), and **M22** (Release `GameRewind v1.2.0-rc.2`).
