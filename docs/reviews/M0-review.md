# M0 setup review

## Advocate

Keep the independent tray and single-instance responsibilities, disposable test data, and checks of the installed and portable packages. The one-folder bundle gives users a no-terminal path and makes it possible to replace shared Qt libraries.

## Critic

The initial portable archive name differed from the README, and the installer could run on Windows builds older than the selected Qt version supports. The final package names agree, and the installer requires build 17763 or later. The first hosted run passed pytest and stopped on an import-order lint issue. Local tests used standard desktop permissions because the Codex AppContainer rejects the user's restricted named-pipe ACL.

The staged source has no credential or personal-path matches. The workflow uses pinned actions, verifies PRIVATE before release, and packages local notices. The Qt 6.12.0 advisories checked concern HTTP response processing and Qt5Compat XML input, which the starter does not use. Recheck when adding Qt input paths. [Qt HTTP advisory](https://www.qt.io/blog/security-issue-cve-2026-116337) · [Qt XML advisory](https://www.qt.io/blog/security-advisory-cve-2026-105925)

## Neutral Analyst

Three local Python tests passed, covering window/tray structure, second-instance activation, and source startup. Native Windows verification confirmed the window and tray, close to tray, reopen, and exit. Ruff passes after correcting the import order. The tag workflow tests the built installer and portable bundle before publication.

## Judge

**APPROVE WITH CHANGES.** The original build needed consistent release filenames, the Qt Windows floor, and passing lint. These changes are in place. Re-review the completed tagged Windows workflow and verify that both assets are present before marking M0 done.
