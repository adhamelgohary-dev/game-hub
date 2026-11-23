# Review Council — D-v1.2 (v1.2 Design, Anti-Cheat Research v2 & Part 6 Mods Design)

**Date:** 2026-11-24  
**Artifacts reviewed:** `docs/research/anti-cheat.md` (v2), `docs/design/11-v1.2-plan.md`, `docs/design/12-mods-and-arabizations.md`, `docs/design/mockups/mods-arabizations.html`, `docs/DEFENDER-SUBMISSION.md`, `DECISIONS.md`.

## Advocate
- Directly solves the owner's highest priority (**zero ban risk**) with defense-in-depth across 7 testable layers: static code-scan test, fail-closed startup self-check + 1 s watchdog, pre-single-instance refuse-to-start, 300 ms Toolhelp32 + read-only SCM service monitoring, launcher-stage earliest-exit (`FortniteBootstrapper.exe`, `FortniteLauncher.exe`, `EAAntiCheat.GameServiceLauncher.exe`), Riot Client always-strict, and Epic/EA/Steam allowed by default so story games continue working in Full mode.
- Real-PC diagnosis uncovered three critical facts that prevent shipping broken behavior: (1) modern Epic Launcher stores games in `HKCU\...\Uninstall\EpicGames-*`, (2) Steam's `libraryfolders.vdf` keeps offline drives causing false `partial` warnings, and (3) `EAAntiCheatService` stays `Running` in the background even when EA FC is closed.
- Part 6 Mods & Arabizations design is strictly design-only (zero premature code), bans modding on protected games, enforces SHA-256 backups and one-click vanilla restore, and explicitly models the Mafia II Arabization-vs-mod conflict case.

## Critic
- **Watch out for Case 4 (`SingleInstance`) ordering:** In `gamehub/app.py`, `SingleInstance.claim_or_activate()` currently runs *before* the catalog is loaded. In v1.2, the startup protection gate + self-check MUST run **before** `SingleInstance.claim_or_activate()` so a desktop shortcut click while Fortnite/Valorant/Riot Client is running refuses immediately and exits.
- **Watch out for `Test protection` self-test vs. fail-closed live guard:** Clicking "Test protection" in Settings must NOT accidentally close the user's own Game Hub window without showing the result! Solution: the button launches a harmless renamed dummy executable (`FortniteLauncher.exe` copy of a tiny benign helper/no-op binary) in a temp folder and tests an isolated `ProtectionGuard` instance (or a fresh `GameHub --protection-self-test` child process) and measures real detection + exit latency in milliseconds, displaying `"Protection OK — Game Hub closed in X ms"` clearly in Settings!
- **Watch out for SteamGridDB privacy rule:** SteamGridDB must default to OFF, make zero network requests unless both enabled AND the user saved their own API key, and never log the API key.

## Neutral Analyst
- All design constraints from `AGENTS.md` are preserved: offline by default (with SteamGridDB explicitly opt-in per owner prompt), zero background processes, zero `OpenProcess` on protected games, MIT license, Schema v5→v6 atomic migration with backup, and non-blocking `"Rewind"` trademark conflict check with clean alternatives (`GameRewind`, `Rewind Games`, `PlayRewind`).
- Breaking implementation into 4 clean, incremental milestones (`M14` Part 1 Anti-Cheat, `M15` Part 2 Launchers & Scan Folders, `M16` Part 3 Covers & SteamGridDB, `M17` Part 4 Plain Settings & Arabic Guide) followed by `M18` (`v1.2.0-rc.1` verification + Desktop copy) keeps diffs small, testable, and reversible.

## Judge
**Verdict: APPROVE (with Critic's 3 implementation invariants mandatory).**
1. Startup protection check and fail-closed self-check MUST execute before `SingleInstance.claim_or_activate()` and before showing any main window.
2. `"Test protection"` in Settings MUST run a real dummy-process check measuring real guard detection/exit latency without unexpectedly terminating the user's open Settings screen, and report `"Protection OK — Game Hub closed in X ms"`.
3. SteamGridDB MUST stay strictly OFF by default, require explicit user API key + opt-in consent, and never leak the key to logs.

Proceed to **M14 (Part 1 — Zero-Presence Anti-Cheat Protocol)**.
