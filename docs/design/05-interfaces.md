# Module interfaces

Use immutable value objects for IDs, timestamps and worker results. ID types distinguish a game, session, note, capture request, recording, and launch attempt. OS handles remain runtime values. Commands that fail return a typed failure with a localized message key. Adapter exceptions map to that result at their boundary. Worker completions carry their original request ID so the caller can discard stale results.

## Discovery, launch, and sessions

| Contract | Purpose |
| --- | --- |
| `GameDetector.source: GameSource` | Stable source identity |
| `GameDetector.discover() -> DiscoveryBatch` | Bounded local scan. Batch includes detected games, completion state (`complete`, `partial`, `unavailable`), and diagnostic codes without raw launcher content. |
| `LibraryService.refresh() -> RefreshResult` | Reconcile per source. Keep existing data when a source is incomplete. |
| `LibraryService.add_manual(exe: Path) -> Result[GameId]` | Validate `.exe` and canonicalize Windows path identity. In one write transaction, reuse the existing explicit target owner or insert the manual game and its target. |
| `LibraryService.assign_target(game_id: GameId, exe: Path) -> Result[GameId]` | Resolve tracking for a detected entry using an explicit executable selection. |
| `Launcher.launch(target: LaunchTarget, attempt_id: LaunchAttemptId) -> Result[LaunchReceipt]` | Dispatch a validated Steam or Epic URI through Windows, or an absolute `.exe` directly with `shell=False`. A receipt means accepted by Windows, with session starts determined by observation. |
| `ProcessProbe.snapshot(targets: Sequence[GameTarget]) -> ProcessSnapshot` | Return live `(PID, creation time)` identities with exact match keys, known exits and incomplete observations. An empty successful scan differs from a failed scan. |
| `WindowProbe.foreground() -> WindowIdentity \| None` | Read current visible non-minimized top-level HWND, owner PID and creation time. |
| `SessionTracker.observe(snapshot: ProcessSnapshot, time: ClockReading) -> None` | Reconcile per-game active process sets and enqueue state changes. A clock reading carries UTC and monotonic time. |
| `SessionTracker.active_for(window: WindowIdentity) -> ActiveSession \| None` | Confirm that identity belongs to a currently observed known game session. |

`GameTarget` contains `kind`, `match_key`, and origin. `LaunchTarget` is tagged with its allowed kind (`steam_uri`, `epic_uri`, `exe`) and validated value. Each `DetectedGame` carries source identity, display name, optional install directory, cover reference and launch target, and zero or more tracking targets. Parsers and detection stay independent of launching.

## Capture, notes, and native integration

| Contract | Purpose |
| --- | --- |
| `CaptureService.acquire() -> CaptureLease \| None` | Issue a short-lived lease carrying the exact foreground HWND and process identity, owning game and session IDs, a monotonic deadline, and the minimum compositor timestamp. The controls feature can reuse this acquisition path. |
| `CaptureService.is_current(lease: CaptureLease) -> bool` | Check live foreground, exact process identity, active session, and expiry. |
| `WgcCapture.capture_once(lease: CaptureLease, is_current: Callable[[CaptureLease], bool]) -> CaptureFrame \| None` | Bind the lease HWND. Check eligibility before binding and on arrival, return one fresh owned frame or skip, and release native resources on exit. |
| `CaptureService.sample(lease: CaptureLease) -> bool` | Request one frame, validate and encode it, and save it to the current session's bounded screenshot ring. Return whether the image was retained. |
| `Recorder.start(session_id: SessionId, source: NoteSource, limit_sec: int) -> Result[RecordingId]` | Start a single microphone-only recording. Bind the session and source at start and stop automatically at an application cap of 60 seconds. |
| `Recorder.stop(recording_id: RecordingId) -> Result[EncodedClip]` | Finish asynchronously, yielding an owned staged result. The recording retains its original session if game or window focus changes. |
| `NoteCommands.save_voice(clip: EncodedClip) -> Result[NoteId]` | Persist into the immutable target session using the managed file protocol. |
| `NoteCommands.save_text(session_id: SessionId, text: str) -> Result[NoteId]` | Validate and save explicit popup text against the supplied session. |
| `Player.play(note_id: NoteId) -> Result[PlaybackId]` / `Player.stop() -> None` | Resolve local media and play one voice note through Qt Multimedia. |
| `Hotkeys.apply(shortcuts: Mapping[HotkeyAction, Shortcut]) -> Result[None]` | Reserve new OS chords before changing any action, reuse existing registration IDs when actions swap chords, and release obsolete registrations after the replacement commits. A conflict releases only temporary registrations. If the previous registrations cannot be restored after an OS failure, disable affected actions and show the actual degraded status. |
| `StartupRegistration.apply(enabled: bool) -> Result[None]` | Apply or remove the per-user startup entry without elevation. |

`CaptureFrame` contains packed owned BGRA pixels and dimensions. The adapter interprets native timestamps while the buffer is mapped and releases the mapping after copying. `HotkeyAction` has `record_note`, `last_time`, and `pin_controls`. Relevant recoverable outcomes include `no_active_game`, `ambiguous_game`, `focus_lost`, `capture_unavailable`, `protected_or_empty_frame`, `mic_unavailable`, `audio_busy`, `shortcut_conflict`, `launch_unavailable`, `media_missing`, and `storage_unavailable`.

## Repositories and settings

| Contract | Responsibility |
| --- | --- |
| `LibraryRead.list_games() -> Sequence[GameSummary]` | Display name, source, install location, local cover, playtime, last-played time and launch/tracking capability |
| `LibraryRead.get_game(game_id: GameId) -> GameDetails \| None` | Read a specific game and its current capabilities |
| `SessionWrite.open(game_id: GameId, at: ClockReading) -> SessionId` | Commit one open row per game |
| `SessionWrite.checkpoint(session_id: SessionId, seen_at: UtcMillis, duration_sec: int) -> None` | Persist observed time for recovery |
| `SessionWrite.finish(session_id: SessionId, end: SessionEnd) -> SessionSummary` | Idempotent terminal transition and atomic marking of retained screenshots |
| `MemoryRead.last_time(game_id: GameId, exclude_session_id: SessionId \| None) -> LastTimeData` | Fetch prior terminal session, latest eligible note of each kind, screenshots, controls, and display stats from a consistent snapshot |
| `MemoryRead.timeline(game_id: GameId, cursor: SessionCursor \| None, limit: int) -> TimelinePage` | Return newest-first session summaries and their saved memories. The cursor combines UTC start and ID to break ties. |
| `ScreenshotRepository.append(game_id: str, session_id: str, data: bytes, captured_at: int, limit: int) -> bool` | Write a WebP only for the matching open session and prune its active ring to the limit |
| `ScreenshotRepository.last_moments(game_id: str) -> tuple[Path, ...]` and `read_image(path: Path) -> bytes \| None` | List canonical slots from the latest terminal session, then lazily read one image through protected storage. Preserve missing slots and return an unavailable result when a protected read fails. |
| `ControlsWrite.pin_image(game_id: GameId, image: EncodedImage) -> Result[ControlId]` / `ControlsWrite.pin_text(game_id: GameId, text: str) -> Result[ControlId]` | Save controls through the same managed media boundary |
| `MediaRead.open(ref: MediaRef) -> Result[LocalMedia]` | Resolve a managed reference after containment validation |
| `Settings.read() -> SettingsSnapshot` / `Settings.update(patch: SettingsPatch) -> Result[SettingsSnapshot]` | Read or update a validated setting set with a runtime revision. Coordinate startup and hotkey side effects before publishing changes. |
| `StoreLocation.current() -> Path` / `StoreLocation.move(destination: Path) -> Result[RestartRequired]` | Show selected data root and perform the offline verified move |

The [data model](04-data-model.md) defines the persisted settings schema and defaults. `SettingsPatch` contains only submitted keys and typed scalar values. Rejected patches leave the last valid settings active. `MediaRef` contains the managed relative path and media kind. Repository readers expose that value rather than guessing filenames. `SessionEnd` carries terminal status, end time, and the final observed duration. SQL, OS paths and native interfaces stay in adapters or their owning core services.

## Event bus and module host

`EventBus.subscribe(event_type: type[E], handler: Callable[[E], None]) -> Subscription` registers a listener. `Subscription.close() -> None` removes it. `EventBus.publish(event: Event) -> None` queues dispatch in publication order on the Qt thread. Events are local, typed notifications. The event producer publishes durable changes only after the owning transaction commits. Startup consumers query current data instead of requiring replay of old events.

| Event | Payload |
| --- | --- |
| `LibraryChanged` | Affected game IDs |
| `GameStarted` | Game ID, new session ID, start time, optional matching launch attempt ID |
| `GameStopped` | Game ID, session ID, end time, duration, terminal status and reason (`process_exit`, `app_quit`, `observation_lost`, `recovered`) |
| `LaunchRequested` / `LaunchFinished` | Launch attempt ID, game ID and, on finish, acceptance or diagnostic code |
| `MemoryChanged` | Game ID, optional session ID, item kind and item ID |
| `SettingsChanged` | Changed keys and settings revision |
| `HotkeyInvoked` | Configured action. The handler resolves the foreground again for recording start and pinning. |

`GameHubModule.start(context: ModuleContext) -> ModuleContribution` receives permitted event, library, session, settings and media ports. `GameHubModule.stop() -> None` disconnects subscriptions and cancels its work. Contributions are named game actions and views scoped by game ID, plus optional settings panels. The app hosts them through one bundled registration list. A module can declare its own storage namespace, migrations and settings prefix as part of registration when needed. v1 has no user-provided module loading.
