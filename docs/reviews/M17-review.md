# Review Council — M17 (Part 4: Plain-Language Grouped Settings, Reset to Defaults & Arabic Guide)

**Date:** 2026-11-24  
**Test verification:** `211 passed in 14.01s`, `ruff check .` clean (0 errors).

## Advocate
- Reorganized `SettingsView` into 5 clear groups with a **one-line plain-language explanation under every setting** in both English and Arabic:
  1. **General** (Display language, Theme)
  2. **Capture and notes** (Screenshot interval, Screenshot ring size, Autoplay voice notes, Ask for a note when a game closes, Global shortcuts)
  3. **Protected games** (External behavior, per-launcher strict toggles with Riot locked ON, detected protected games list, **Test protection** button)
  4. **Library and folders** (Scan folders manager with Add/Rescan/Remove, optional off-by-default SteamGridDB toggle + password-masked API key + consent note + Fetch missing covers button, Data folder Open/Move)
  5. **About and privacy** (Zero-background & offline/anti-cheat guarantees, version & MIT license, **Reset to defaults** button with confirmation)
- Wired Scan folders, optional SteamGridDB cover fetch, and **Reset to defaults** (`SettingsService.reset_to_defaults()` + `library.reset_protection_defaults()` preserving all notes and screenshots) in `gamehub/app.py`.
- Rewrote `docs/USER-GUIDE-AR.md` for v1.2 (removing stale v1.0 System Tray notes and adding a full Egyptian Arabic **"شرح الإعدادات"** section covering every setting).

## Critic
- Verified zero `&` mnemonic underlines across all new Settings strings (`test_arabic_catalog_has_full_key_and_placeholder_parity` passes 100%).
- Verified SteamGridDB API key input is password-masked (`QLineEdit.EchoMode.Password`), disabled unless enabled checkbox is ticked, and never written to logs.
- Verified Reset to defaults requires explicit confirmation and preserves all saved games, sessions, notes, and screenshots.

## Neutral Analyst
- All 211 tests and `ruff check .` pass cleanly with zero regressions.

## Judge
**Verdict: APPROVE.** Tag `m17` and proceed immediately to **M18 (`v1.2.0-rc.1` packaging, full verification, Desktop installer copy, pre-release publish & Council review)**.
