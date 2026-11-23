# Review Council — M12c (`v1.1.0-rc.2` Pre-release Polish)

Date: 2026-11-23  
Milestone: **M12c — `v1.1.0-rc.2` (EAC Strict defaults + mnemonic-free buttons + regenerated screenshots)**  
Branch / Head: `main` (pre-commit review for `v1.1.0-rc.2`)

## Scope Reviewed
- Protected-games catalog & frozen loader: `gamehub/core/protection/protected_games.json`, `gamehub/core/protection/catalog.py`, `docs/research/anti-cheat.md`, `README.md`.
- Mnemonic underline removal & Arabic parity: `gamehub/ui/library_view.py`, `gamehub/ui/game_page.py`, `gamehub/ui/settings_view.py`, `gamehub/ui/last_moments.py`, `gamehub/modules/memory/last_time_card.py`, `gamehub/modules/memory/note_dialog.py`, `gamehub/core/i18n/catalog.py`.
- Regenerated real-app screenshots: `docs/screenshots/{library-dark-en,library-light-en,game-page-dark-en,library-dark-ar-rtl}.png`.
- Regression tests & release prep: `tests/test_protection_and_lifecycle.py`, `tests/test_i18n_and_settings_ui.py`, `tests/test_note_dialog.py`, `tests/test_packaging.py`, `gamehub/__init__.py`, `CHANGELOG.md`.

## Role Deliberations

### Advocate
- Directly addresses both owner items before `v1.1.0` without expanding scope:
  1. Verified **ELDEN RING** (`1245620`, `eldenring.exe`, `start_protected_game.exe`) defaults to **Strict**, added **ARMORED CORE VI FIRES OF RUBICON** (`1888160`, `armoredcore6.exe`), **ELDEN RING NIGHTREIGN** (`2622380`, `nightreign.exe`), **Lords of the Fallen** (`1501750`, `lotf2-win64-shipping.exe`), and **Warhammer 40,000: Space Marine 2** (`2183900`) to `protected_games.json`, and confirmed **Dark Souls III** (`374320`), **Dark Souls: Remastered**, and **Sekiro** do not use EAC or a kernel anti-cheat driver (so they remain in **Full** mode).
  2. Removed every `&` mnemonic underline from buttons, dialogs, and labels across all UI surfaces (including replacing Qt's `QDialogButtonBox.StandardButton.Close` in `LastMomentsDialog` with a translated plain `"Close"` button), updated `AR_CATALOG` to keep 100% Arabic parity, and added an AST test blocking mnemonic `&` regressions.
- Hardened `ProtectedGamesCatalog.load()` with an explicit `sys._MEIPASS` lookup for frozen PyInstaller bundles.
- Regenerated all four README screenshots with native Windows font rendering and the live `ProtectedGamesCatalog`, visually verified crisp rendering, Elden Ring showing `Strict` / `Auto (Strict)`, Dark Souls III showing `Full`, and zero button underlines.

### Critic
- **Checked `start_protected_game.exe` collision:** Kept `start_protected_game.exe` exclusively on `elden_ring` rather than duplicating it across `armored_core_6` and `elden_ring_nightreign` so `self._by_exe` maps deterministically without overwriting the entry name while still catching any EAC game launched via `start_protected_game.exe` as Strict.
- **Checked scope discipline:** Left `steam.py` and unrelated modules untouched as explicitly requested by the owner ("Fix only these").
- **Residual note:** `v1.1.0-rc.2` remains a SemVer `--prerelease`; final `v1.1.0` (M13) still waits for the owner's `"verified"` reply after running the 10-item checklist.

### Neutral Analyst
- Automated verification: **184 passed** (`pytest -q`), **Ruff clean** (`All checks passed!`), **AST mnemonic-free & Arabic catalog parity verified**, **PyInstaller bundle + offscreen `GameHub.exe --smoke-test` exit 0**, and **`_internal/gamehub/core/protection/protected_games.json` present**.
- Repository visibility confirmed `PUBLIC` with zero network imports, zero injection/memory-read calls, and zero tray/background regressions.

### Judge
- **Verdict: APPROVED**
- Proceed to commit on `main`, push `main`, tag and push `v1.1.0-rc.2`, wait for Windows CI to publish `Game Hub v1.1.0-rc.2` (pre-release), verify `SHA256SUMS.txt`, copy `GameHub-Setup-v1.1.0-rc.2.exe` to `%USERPROFILE%\Desktop\`, and deliver the 10-item click checklist to the owner.
