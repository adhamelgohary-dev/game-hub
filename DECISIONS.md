# Decisions

| Date | Decision | Reason and alternative |
| --- | --- | --- |
| 2026-11-22 | Complete D before M0 on a fresh workspace. | The setup resume rule points to M0 and the design gate explicitly precedes it. |
| 2026-11-22 | Ship the one-folder bundle and Inno installer from M0 on private milestone releases. | The build instructions make the installer mandatory and specify an early release. The product spec's M8 checks still apply to final clean-machine verification. The executable requires the bundled runtime files. |
| 2026-11-22 | Split private remote creation and the initial push. | This lets us confirm the owner, repository, and visibility before any code is uploaded. |
| 2026-11-22 | Target the exact foreground HWND through Windows Graphics Capture. | It satisfies window-only capture. Desktop duplication would expose pixels outside the game. Validate the pinned wheel in M3. |
| 2026-11-22 | Keep a local SQLite database, file-backed media and a single write coordinator. | SQLite enforces relations and allows atomic DB updates. Staging and reconciliation handle interrupted filesystem changes. JSON alone would make relationships and upgrades fragile. |
| 2026-11-22 | Target CPython 3.12 on Windows x64 first. | The spec permits 3.12 and later. Native wheels and packaged smoke tests gate adding further Python or Windows architectures. |
| 2026-11-22 | Keep repository content in English and reserve Arabic for product localization and the requested Arabic README/user guide. | This keeps technical handoff readable across tools and preserves the product's bilingual experience. |
| 2026-11-22 | Treat the data-folder setting as a managed local relocation. | The setting lists a data folder and the default path is specified. A validated copy can keep the DB and relative media references together. |
| 2026-11-22 | Make Play a preview with an explicit Launch action and deduplicate the corresponding watcher card. | This gives the player time to use the memory card and avoids repeated autoplay. Direct launch after a timer would interrupt reading. |
| 2026-11-22 | Use 1% of one logical core over a 120-second idle sample as the Windows acceptance budget. | This gives the stated near-zero CPU objective a reproducible criterion without hardware-specific percentages. |
| 2026-11-22 | Keep working copies of both inputs and remove the personal owner line from STRUCTURE.txt. | A future contributor can read the complete behavior spec without sharing the owner's identity in repository history. |
