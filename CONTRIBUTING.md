# Contributing to GameRewind

Thank you for helping improve GameRewind!

## Ground Rules

1. **Design before code:** For behavior, data-model, or interface changes, update the relevant document in `docs/design/` and log architectural decisions in `DECISIONS.md` first.
2. **Offline & zero-background invariants (v1.x):**
   - No network imports or outbound requests.
   - No system tray icon, autostart registry writes (`winreg.SetValueEx`), Windows services, or background helpers.
   - Closing the main window must exit the process completely.
3. **Anti-cheat safety invariants (hard rules):**
   - Never inject DLLs, hook games (`SetWindowsHookEx`), read/write process memory, or open handles with write/VM/debug rights.
   - Never call `OpenProcess` on protected/Strict-mode games — use passive `CreateToolhelp32Snapshot` basename matching only.
   - Updating the protected-games list only requires editing `gamehub/core/protection/protected_games.json`.
4. **Bilingual UI (English + Arabic RTL):** Every user-facing `self.tr(...)` string must have a matching Arabic entry in `gamehub/core/i18n/catalog.py` (verified automatically by `tests/test_i18n_and_settings_ui.py`).
5. **Privacy in commits:** Never commit personal paths, secrets, real launcher files, or user data. Use synthetic fixtures in `tests/fixtures/`.

## Local Development Setup (Windows 10/11, Python 3.12 x64)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m gamehub.app
```

## Pull Request Checklist

- [ ] Relevant tests added/updated and `python -m pytest -q` passes
- [ ] `python -m ruff check .` reports zero errors
- [ ] Arabic translations added for any new UI text (`tests/test_i18n_and_settings_ui.py` passes)
- [ ] Static offline/no-injection/zero-background audit passes (`tests/test_packaging.py`)
- [ ] `CHANGELOG.md` updated if user-facing behavior changed
