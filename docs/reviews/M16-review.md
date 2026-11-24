# Review Council — M16 (Part 3: Cover Art That Fits — Landscape Covers, Cache, Change Cover & Opt-In SteamGridDB)

**Date:** 2026-11-24  
**Test verification:** `208 passed in 14.21s`, `ruff check .` clean (0 errors).

## Advocate
- **Landscape-first Steam discovery (`steam.py`):** `_find_cover()` now searches wide assets (`header.jpg`, `library_header.jpg`, `library_hero.jpg`) across flat, per-AppID, and hashed subdirectories before falling back to vertical capsules (`library_capsule.jpg`, `library_600x900.jpg`). Verified live on this PC: **26 / 26** Steam games resolved to wide landscape covers (`wide=26, vertical=0, none=0`).
- **Zero-stretch center-crop + disk WebP cache (`ui/covers.py`):** Replaced `setScaledContents(True)` stretching on `GameCard` with resize-aware `CoverLabel`, added atomic disk WebP thumbnail caching under `<data_root>/cache/covers/` keyed by path/mtime/size/dimensions, and upgraded fallback placeholders to render the full game name cleanly.
- **"⋯ → Change cover…" & "Reset cover":** Added safe managed `CoverStore` (`core/storage/covers.py`) using bounded reads, Pillow EXIF-transpose, metadata stripping, WebP encoding, and pinned atomic staging to `<data_root>/media/<game_id>/cover.webp` (`custom_cover = 1`, preserved across refreshes), wired into both `GameCard` and `GamePage`.
- **Optional off-by-default SteamGridDB (`core/library/steamgriddb.py`):** Strictly gated on both `enabled=True` and user-supplied `api_key`, HTTPS-only, bounded responses, wide grid preference (`460x215,920x430`), and zero API-key logging.

## Critic
- Verified offline security invariant in `tests/test_packaging.py`: `urllib` is permitted exclusively inside `gamehub/core/library/steamgriddb.py`, every other module under `gamehub/` stays 100% network-import-free, and unit tests prove zero network calls occur when disabled or missing a key.
- Checked `CoverStore` safety: rejects invalid UUIDs, enforces 12 MiB / 24 MP caps, strips EXIF/metadata, and uses Windows directory pinning via `media.stage_file`.
- Checked EN/AR parity and `QFileDialog` glob filter safety (zero BiDi characters inside `(*.png *.jpg *.jpeg *.webp)`).

## Neutral Analyst
- All 208 tests and `ruff check .` pass cleanly with zero regressions.

## Judge
**Verdict: APPROVE.** Tag `m16` and proceed immediately to **M17 (Part 4 — Plain-Language Grouped Settings & Egyptian Arabic Settings Guide)**.
