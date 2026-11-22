# Module interfaces (v1.1)

Use immutable value objects for IDs, timestamps, protection classifications, and worker results. OS handles remain runtime values. Commands that fail return typed failures with localized message keys.

## Protection & Anti-Cheat Safety (`gamehub/core/protection/`)

| Contract | Purpose |
| --- | --- |
| `ProtectedGameEntry` | Immutable record: `id`, `name`, `anti_cheat`, `privilege` (`"kernel"` \| `"user"`), `starts_at` (`"boot"` \| `"launch"`), `default_mode` (`"strict"`), `steam_app_ids`, `epic_app_names`, `xbox_package_prefixes`, `exe_names`. |
| `ProtectedGamesCatalog.load(bundled_path, override_path=None) -> ProtectedGamesCatalog` | Load versioned JSON catalog plus optional user override file. Malformed overrides log a warning and fall back to bundled data. |
| `ProtectedGamesCatalog.match_game(source, source_id, exe_names) -> ProtectedGameEntry \| None` | Identify whether a library game is in the protected catalog using Steam AppID, Epic AppName, Xbox package prefix, or target executable basename. |
| `ProtectedGamesCatalog.match_exe_name(basename: str) -> ProtectedGameEntry \| None` | Case-insensitive basename lookup used by passive Toolhelp scanning. Never opens a process handle. |
| `ProtectedGamesCatalog.effective_mode(game: GameSummary, target_exes: Sequence[str]) -> Literal["strict", "full"]` | Resolve `'strict'` or `'full'` from `game.protection_mode` (`'auto'` → `'strict'` if catalog match else `'full'`; explicit `'strict'` / `'full'` wins). |
| `ProtectedGameDetected` (Event) | Published when passive basename scanning observes a protected game running that was not launched in Full mode (`entry_id`, `entry_name`, `game_id: str \| None`, `exe_name`). |

## Passive Notifications (`gamehub/core/notifications/`)

| Contract | Purpose |
| --- | --- |
| `WindowsNotifier.notify_protected_game(game_name: str, *, title: str, body: str) -> bool` | Deliver a passive Windows toast/balloon notification without creating a topmost window over a running game or installing a persistent tray icon. Returns whether the OS accepted the notification; falls back silently to strict mode without popping a window over the game. |

## Discovery, Launch, Sessions, and Lifecycle

| Contract | Purpose |
| --- | --- |
| `LibraryRepository.set_protection_mode(game_id: str, mode: str, *, exit_after_launch: bool \| None = None) -> None` | Persist per-game protection override (`auto`, `strict`, `full`) and optional strict-mode `exit_after_launch` flag. |
| `LibraryRepository.list_target_basenames() -> dict[str, tuple[str, ...]]` | Return lowercase target basenames per game for catalog matching and passive strict-mode tracking. |
| `PendingNoteRepository.add(game_id: str, launched_at: int) -> str` / `list_pending() -> tuple[PendingNote, ...]` / `consume(pending_id: str) -> None` | Queue and consume deferred note prompts created when Game Hub exits immediately after launching a Strict-mode game. |
| `ProcessProbe.snapshot(targets, *, protected_exes=frozenset(), strict_game_ids=frozenset()) -> ProcessSnapshot` | Perform one `CreateToolhelp32Snapshot` basename pass. For any basename matching `protected_exes` or belonging to a `strict_game_ids` target, record passive basename presence **without calling `OpenProcess` or `psutil.Process`**. Only non-strict Full-mode targets invoke `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`. |
| `SessionTracker` & `SessionWatcher` | Track both exact-identity Full-mode sessions and passive basename-only Strict-mode sessions; emit `ProtectedGameDetected` for externally launched protected games. |
| `GlobalHotkeys.suspend() -> None` / `resume() -> None` | Unregister all active Win32 hotkeys while Strict mode is active and re-register saved shortcuts when Strict mode ends. |
| `WgcCapture.capture_once(...)` | Pass `draw_border=False` on Windows builds >= 20348 with automatic single fallback to `draw_border=None` if rejected by the OS. |
| `remove_legacy_startup_entry() -> None` | Remove legacy v1.0 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\GameHub` value on startup if present (best-effort, never creates a key or entry). |

## Settings & UI Contracts

- `SettingsSnapshot` replaces `start_with_windows` with:
  - `theme: str = "dark"` (`"dark"`, `"light"`, `"system"`)
  - `external_protected_behavior: str = "exit_app"` (`"exit_app"`, `"strict_mode"`, `"ask_me"`)
- `GameHubWindow` has **no `QSystemTrayIcon`**; `closeEvent` accepts closure and triggers full process teardown (`quitOnLastWindowClosed = True`).
- `LastTimeController` supports `exit_after_play: bool` (from `--play <game_id>` or the Play card toggle) and `strict_mode: bool` (suppressing automatic in-game topmost popups, minimizing on launch, or saving a `pending_notes` row and exiting cleanly when `exit_after_launch=True`).
- All v1.0 repository contracts (`LibraryRead`, `SessionWrite`, `MemoryRead`, `ScreenshotRepository`, `NoteRepository`, `ControlsWrite`, `StoreLocation`, `EventBus`) remain backward-compatible.
