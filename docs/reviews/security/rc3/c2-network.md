# Red-Team Report C2 — Network & Websites Audit (`v1.2.0-rc.3`)

**Role:** Independent Network & Websites Red-Team Auditor (C2 — fresh eyes)  
**Date:** 2026-11-24  
**Scope:** Full-repo scan for URLs, network clients, QtNetwork, Steam covers, SteamGridDB, `QDesktopServices`, and secret handling.

## Complete Outgoing Connection Inventory
AST + string audit of the entire `gamehub/` package confirmed **exactly ONE** outbound network path exists in the entire application:

| Component | Target Hosts | Protocol | Default State | Offline Behavior |
| --- | --- | --- | --- | --- |
| `gamehub/core/library/steamgriddb.py` (`fetch_steamgriddb_cover`) | `www.steamgriddb.com` (API), `cdn.steamgriddb.com`, `cdn2.steamgriddb.com` (images) | HTTPS only (port 443) | **OFF by default** (`steamgriddb_enabled=False`, requires explicit user opt-in + user API key + button click) | Zero network calls; graceful `None` fallback if unreachable |
| `gamehub/core/library/steam.py` (`_find_cover`) | **None (local filesystem only)** | Local disk (`appcache/librarycache`) | Always local | 100% offline |
| `gamehub/ui/covers.py` (thumbnail cache) | **None (local filesystem only)** | Local disk WebP cache | Always local | 100% offline |
| `gamehub/single_instance.py` | **None (local IPC only)** | `QLocalServer` / `QLocalSocket` (`UserAccessOption`) | Local same-user pipe | 100% offline |
| `gamehub/app.py` (`QDesktopServices.openUrl`) | **None (local folder only)** | `QUrl.fromLocalFile(store_location.current())` | User click only | 100% offline |
| Telemetry / analytics / update checks | **None** | N/A | N/A | Zero telemetry |

## Round 1 Findings

### `[MEDIUM] C2-01` — SteamGridDB API key stored in plaintext in SQLite
- **Evidence:** `gamehub/core/settings.py` persisted `covers.steamgriddb_api_key` as plaintext JSON in `gamehub.db`.
- **Fix Applied:** Added `gamehub/core/secrets.py` using Windows-native user-scoped DPAPI (`crypt32.CryptProtectData` / `CryptUnprotectData` with `CRYPTPROTECT_UI_FORBIDDEN = 0x01`), transparently encrypting `covers.steamgriddb_api_key` on write (`dpapi:<base64>`) and decrypting on read. Restricted `crypt32` DLL access strictly to `gamehub/core/secrets.py` in `tests/test_packaging.py`. API key remains masked (`QLineEdit.Password`), never logged, and SteamGridDB remains OFF by default.
- **Verification:** `tests/test_security_rc3.py::test_steamgriddb_key_encrypted_at_rest_with_dpapi_and_strict_network_validation` PASS.

### `[MEDIUM] C2-02` — SteamGridDB URL/header/image-type defense-in-depth gaps
- **Evidence:** `_validate_https_host` did not reject URL userinfo (`user:pass@host`) or non-443 ports; `fetch_steamgriddb_cover` did not re-validate `api_key` against CRLF/non-ASCII if called directly; `_default_get_bytes` did not explicitly bind `ssl.create_default_context()`; CDN responses were returned without magic-byte verification before reaching `CoverStore`.
- **Fix Applied:** Hardened `_validate_https_host` to reject userinfo and non-443 ports, bound explicit `ssl.create_default_context()` alongside `_NoRedirectHandler`, enforced ASCII/length/CRLF validation on `api_key`, checked `type(sgdb_id) is int and sgdb_id > 0`, and enforced PNG/JPEG/WebP magic-byte verification (`_is_valid_image_magic`) before returning downloaded bytes (with 6 s timeout, 256 KB JSON cap, 8 MB image cap, zero redirects).
- **Verification:** `tests/test_security_rc3.py` + `tests/test_v12_covers.py` + `tests/test_packaging.py` PASS.

## Round 2 Verdict: **PASS — 0 Open Findings**
