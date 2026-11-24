# Security Policy

## Supported Versions

Only the latest published semantic version release (`v1.1.x` and later) receives security fixes.

## Reporting a Vulnerability

Please report security issues privately using **GitHub Security Advisories** (`Security` → `Advisories` → `Report a vulnerability` on this repository). Do not open public issues for unpatched vulnerabilities.

Include:
- Affected GameRewind version and Windows build (`winver`)
- Steps to reproduce or proof of concept
- Potential impact (e.g., path traversal, launcher URI injection, privilege escalation, anti-cheat interaction)

We aim to acknowledge reports within 72 hours and publish fixes in a patch release (`vX.Y.Z`).

## Privacy & Anti-Cheat Safety Guarantees

GameRewind is designed to be **100% offline, zero-background, and non-invasive**:
- **Zero network calls** in v1.x (verified statically in `tests/test_packaging.py`).
- **Zero background processes**: no system tray icon, no Windows autostart registry entries, no Windows services, and no scheduled tasks. Closing the main window exits the process completely.
- **Zero game injection or memory access**: GameRewind never injects DLLs, installs keyboard/graphics hooks (`SetWindowsHookEx`), reads/writes game memory, or requests debug/write handles.
- **Zero `OpenProcess` handles on protected games**: known anti-cheat titles (`gamehub/core/protection/protected_games.json`) are detected passively via `CreateToolhelp32Snapshot` basenames only and default to Strict mode or automatic exit.
- **Local-only data**: all SQLite data, screenshots, voice notes, and logs stay inside `%LOCALAPPDATA%\GameRewind\` (or the user's chosen local folder).

## Code Signing Policy (SignPath Foundation)

GameRewind builds official Windows release artifacts exclusively inside reproducible **GitHub Actions** workflows (`.github/workflows/windows.yml`) triggered from signed/verified SemVer tags on `main`:
- **Authors / Maintainers:** Repository owner (`adhamelgohary-dev`) and reviewed pull-request contributors.
- **Reviewers & Approvers:** All milestone changes pass automated tests (`pytest`), linting (`ruff`), static security/offline/no-injection audits (`tests/test_packaging.py`), and documented Review Council approval (`docs/reviews/`) before a release tag is pushed. Only the repository owner may approve SignPath signing requests.
- **Privacy statement:** GameRewind does not collect, transmit, or share any user data. All user data remains local on the user's device.
- **Third-party notices:** All bundled open-source runtimes (CPython, PySide6/Qt, FFmpeg, PortAudio, libsndfile, Pillow, OpenCV, psutil, windows-capture) carry their verbatim licenses under `_internal/third-party/`.
