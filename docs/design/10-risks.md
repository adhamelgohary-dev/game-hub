# Risks and mitigations

| Risk | Mitigation and acceptance check |
| --- | --- |
| Capturing an unrelated window during focus changes or HWND reuse | Bind window handle to process identity. Validate at request and receipt. Reject stale and minimized windows, and use exact-window WGC. Exercise forced focus changes and duplicate titles in M3. |
| WGC wheel, unsupported driver, or black/protected frames | Check pinned wheel and Windows builds in M3. Skip failed frames and log safe reason codes. Leave other memory features usable. |
| Exclusive fullscreen covers the card | Offer reopen hotkey and show the card before Play. Test with exclusive fullscreen and document focus limits. |
| Incomplete or ambiguous Xbox metadata | Use available user-readable evidence only. Offer manual add and show supported and unsupported cases in the launcher guide. |
| Missed short sessions, PID reuse, or clock drift | Key by PID and creation time, use monotonic elapsed time, reconcile stale sessions on restart. Test denied process queries and time changes. |
| DB and media diverge after a crash, disk full, or AV file lock | Use staged writes and startup reconciliation with bounded cleanup. Use fault injection across transaction and move boundaries. |
| Untrusted path, image or launcher metadata | Validate targets and image dimensions, confine managed paths to the resolved data root, refuse reparse escapes, and pass structured launch values. Redact paths, text and identifiers from logs. |
| Conflicting shortcuts, denied microphone, playback codec mismatch | Register each shortcut separately, keep visible fallback actions, and test mic denial, missing devices and installed-package playback. |
| Resource pressure or UI stalls | Poll every 2–3 seconds, use bounded capture and audio workers, and page timeline reads and thumbnail work. Profile actual Windows idle use and long sessions. |
| Arabic text clips or reverses paths and shortcuts | Apply Qt RTL, keep technical values directionally isolated, and verify keyboard focus, screen-reader names and multiple scale factors. |
| Installer fails, violates a dependency license, or loses saved data | Audit pinned dependencies and included notices. Make per-user installation and uninstall independent of data storage. Smoke test on clean Windows and verify install, upgrade and uninstall. |
| Private repository is misdirected or becomes visible | Verify intended owner/name and PRIVATE before first push and after changes. Review staged changes and keep build/user data out of history. |
